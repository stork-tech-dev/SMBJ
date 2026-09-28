"""
Reglas de negocio del stock.

Lo central de este módulo es `aplicar_movimiento()`: es el ÚNICO camino por
el que la columna `stock.cantidad` cambia. Ningún otro service, endpoint ni
script escribe esa columna directamente.

No es una convención de estilo. El stock es el dato que decide si se puede
vender algo, y su historia es lo que permite explicar una diferencia de
inventario. Un UPDATE suelto en cualquier rincón del sistema rompe las dos
cosas a la vez: deja el número cambiado y sin registro de por qué.

Cada movimiento suma o resta según su TIPO, nunca según el signo de la
cantidad — que siempre se guarda positiva. Así un signo mal puesto no puede
invertir el sentido de una operación.
"""

from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.device_scope import DeviceScope
from app.core.utils import ahora_db
from app.models.producto import Producto, Variante
from app.models.punto_de_venta import PuntoDeVenta, TipoPuntoVenta
from app.models.stock import (
    COLUMNA_MINIMO,
    MINIMO_POR_DEFECTO,
    MovimientoStock,
    Stock,
    TipoMovimiento,
    minimo_aplicable_sql,
)
from app.models.usuario import Usuario
from app.services.roles import NoEncontrado, ReglaDeNegocio

# Qué le hace cada tipo de movimiento al stock de cada punta.
#
# La tabla está acá y explícita en vez de repartida en `if`: es la regla que
# define el significado de cada tipo, y verla junta es lo que permite
# revisarla de un vistazo. `origen` resta y `destino` suma; un tipo con las
# dos puntas es una transferencia.
#
#                                    resta del origen | suma al destino
EFECTO: dict[TipoMovimiento, tuple[bool, bool]] = {
    TipoMovimiento.INGRESO_PROVEEDOR: (False, True),
    TipoMovimiento.ENVIO_CD_LOCAL: (True, True),
    TipoMovimiento.DEVOLUCION_LOCAL_CD: (True, True),
    TipoMovimiento.VENTA: (True, False),
    TipoMovimiento.DEVOLUCION_VENTA: (False, True),
    TipoMovimiento.BAJA: (True, False),
    # El ajuste de auditoría es el único que puede ir para cualquier lado: si
    # se contó menos que lo que decía el sistema resta, y si se contó más
    # suma. La punta la elige quien lo llama (ver `UNA_SOLA_PUNTA`).
    TipoMovimiento.AJUSTE_AUDITORIA: (True, True),
    # Una empleada se lleva un producto: sale del local y no entra a ningún lado.
    TipoMovimiento.RETIRO_MERCADERIA: (True, False),
}

# Tipos cuya dirección NO la fija la tabla de arriba sino el caso concreto.
# El ajuste de auditoría se aplica a una sola ubicación —la que se contó— y
# el signo de la diferencia decide si suma o resta, así que exigirle las dos
# puntas como a una transferencia sería pedirle un dato que no tiene.
UNA_SOLA_PUNTA = frozenset({TipoMovimiento.AJUSTE_AUDITORIA})


def obtener_punto(db: Session, punto_de_venta_id: int) -> PuntoDeVenta:
    punto = db.get(PuntoDeVenta, punto_de_venta_id)
    if punto is None:
        raise NoEncontrado("Punto de venta inexistente")
    return punto


def obtener_variante(db: Session, variante_id: int) -> Variante:
    variante = db.get(Variante, variante_id)
    if variante is None:
        raise NoEncontrado("Variante inexistente")
    return variante


def inicializar_stock(db: Session, variante_id: int) -> list[Stock]:
    """
    Crea la fila de stock de una variante NUEVA en cada punto de venta
    activo —locales, CD y tienda online—, en cero y con mínimo 1, para que
    desde el alta avise cuando falta en cualquier sucursal.

    Las Ubicaciones Especiales (p. ej. Productos Fallados) quedan afuera: no
    son stock vendible y no se reponen. Los tres mínimos nacen en
    `MINIMO_POR_DEFECTO` (default de la columna); cuál rige lo decide el tipo
    de la ubicación (`COLUMNA_MINIMO`).
    """
    puntos = db.execute(
        select(PuntoDeVenta.id).where(
            PuntoDeVenta.activo.is_(True),
            PuntoDeVenta.tipo.in_(list(COLUMNA_MINIMO)),
        )
    ).scalars().all()
    filas = [
        Stock(
            variante_id=variante_id,
            punto_de_venta_id=punto_id,
            cantidad=0,
            stock_minimo_cd=MINIMO_POR_DEFECTO,
            stock_minimo_local=MINIMO_POR_DEFECTO,
            stock_minimo_online=MINIMO_POR_DEFECTO,
            updated_at=ahora_db(),
        )
        for punto_id in puntos
    ]
    db.add_all(filas)
    db.flush()
    return filas


def fila_de_stock(db: Session, variante_id: int, punto_de_venta_id: int) -> Stock:
    """
    La fila de stock de esa variante en esa ubicación, creándola en cero si
    todavía no existe.

    Las variantes nuevas ya nacen con fila en cada punto de venta vendible
    (`inicializar_stock`); esto cubre el resto: Ubicaciones Especiales y
    puntos de venta creados o reactivados después. La fila nueva nace con los
    mínimos en `MINIMO_POR_DEFECTO`. "Sin fila" y "cantidad 0" significan lo
    mismo, y el que pregunta recibe 0 en los dos casos.
    """
    fila = db.execute(
        select(Stock).where(
            Stock.variante_id == variante_id,
            Stock.punto_de_venta_id == punto_de_venta_id,
        )
    ).scalar_one_or_none()

    if fila is None:
        fila = Stock(
            variante_id=variante_id,
            punto_de_venta_id=punto_de_venta_id,
            cantidad=0,
            stock_minimo_cd=MINIMO_POR_DEFECTO,
            stock_minimo_local=MINIMO_POR_DEFECTO,
            stock_minimo_online=MINIMO_POR_DEFECTO,
            updated_at=ahora_db(),
        )
        db.add(fila)
        db.flush()
    return fila


def cantidad_en(db: Session, variante_id: int, punto_de_venta_id: int) -> int:
    """Cuánto hay, sin crear la fila si no existe."""
    return db.execute(
        select(func.coalesce(func.sum(Stock.cantidad), 0)).where(
            Stock.variante_id == variante_id,
            Stock.punto_de_venta_id == punto_de_venta_id,
        )
    ).scalar_one()


def aplicar_movimiento(
    db: Session,
    autor: Usuario,
    *,
    tipo: TipoMovimiento,
    variante_id: int,
    cantidad: int,
    punto_venta_origen_id: int | None = None,
    punto_venta_destino_id: int | None = None,
    remito_id: int | None = None,
    motivo_baja_id: int | None = None,
    auditoria_id: int | None = None,
    referencia_venta_id: int | None = None,
    compra_id: int | None = None,
    retiro_mercaderia_id: int | None = None,
    puntas: tuple[str, ...] | None = None,
    permitir_faltante: bool = False,
    notas: str | None = None,
    ip_origen: str | None = None,
) -> MovimientoStock:
    """
    Registra un movimiento y actualiza el stock, en la misma transacción.

    ÚNICO camino por el que `stock.cantidad` cambia. Todo lo que mueva
    mercadería —un remito, una baja, un ajuste de auditoría, y mañana una
    venta— entra por acá.

    `puntas` acota cuáles de los dos lados se aplican AHORA, y existe por los
    remitos: la mercadería sale del origen cuando se arma el envío y entra al
    destino cuando el local la confirma, que pueden ser días distintos. En el
    medio no está en ninguna de las dos puntas, y sumarla al destino antes de
    que llegue sería dejar vender algo que está en un camión. Cada momento
    registra su propio movimiento, los dos con el mismo `remito_id`.

    En None se aplican las dos puntas que el tipo indique, que es lo que
    corresponde a todo el resto.

    `permitir_faltante` deja que el stock quede en negativo. Lo usa UNA sola
    cosa: la confirmación de una venta. Cuando el sistema dice 0 y la
    vendedora tiene el producto en la mano, el que está mal es el sistema, y
    frenar la venta significaría no vender algo que está sobre el mostrador.
    El negativo que queda no es un error tolerado: es la señal visible de
    que ese artículo necesita una auditoría de inventario. Para cualquier
    otro tipo de movimiento el faltante sigue cortando la operación, que es
    lo correcto — un remito no puede mandar mercadería que no está.

    No hace commit: lo hace el endpoint. Así el movimiento, el stock y la
    auditoría del Principio 3 se confirman o se descartan juntos: si algo
    falla después, no queda un movimiento sin su efecto ni un efecto sin su
    registro.

    Se valida ANTES de tocar nada: con el stock ya restado, un error dejaría
    la transacción a medias esperando el rollback, y el mensaje sería peor.
    """
    if cantidad <= 0:
        raise ReglaDeNegocio("La cantidad de un movimiento tiene que ser mayor a cero")

    resta_origen, suma_destino = EFECTO[tipo]

    # `puntas` solo puede ACOTAR lo que el tipo permite: pedir que un ingreso
    # de proveedor reste de un origen sería inventar un efecto que ese tipo
    # no tiene.
    if puntas is not None:
        desconocidas = set(puntas) - {"origen", "destino"}
        if desconocidas:
            raise ValueError(f"Puntas inválidas: {sorted(desconocidas)}")
        aplica_origen = resta_origen and "origen" in puntas
        aplica_destino = suma_destino and "destino" in puntas
    else:
        aplica_origen, aplica_destino = resta_origen, suma_destino

    if tipo in UNA_SOLA_PUNTA:
        # Exactamente una: el ajuste corrige el stock de la ubicación que se
        # contó. Con las dos sería una transferencia, y con ninguna no movería
        # nada.
        dadas = [p for p in (punto_venta_origen_id, punto_venta_destino_id) if p]
        if len(dadas) != 1:
            raise ReglaDeNegocio(
                f"Un movimiento '{tipo.value}' se aplica a UNA ubicación: resta de "
                "la de origen o suma a la de destino, según el signo de la diferencia"
            )
        aplica_origen = punto_venta_origen_id is not None
        aplica_destino = punto_venta_destino_id is not None
    else:
        if resta_origen and punto_venta_origen_id is None:
            raise ReglaDeNegocio(
                f"Un movimiento '{tipo.value}' necesita ubicación de origen"
            )
        if suma_destino and punto_venta_destino_id is None:
            raise ReglaDeNegocio(
                f"Un movimiento '{tipo.value}' necesita ubicación de destino"
            )

    variante = obtener_variante(db, variante_id)

    if punto_venta_origen_id is not None:
        obtener_punto(db, punto_venta_origen_id)
    if punto_venta_destino_id is not None:
        obtener_punto(db, punto_venta_destino_id)

    if resta_origen and suma_destino and punto_venta_origen_id == punto_venta_destino_id:
        raise ReglaDeNegocio("Una transferencia con origen y destino iguales no mueve nada")

    # El stock infinito no se lleva la cuenta: son servicios o productos a
    # pedido, y descontarles unidades sería inventar un inventario que no
    # existe. El movimiento igual se registra, para que quede la trazabilidad.
    lleva_cuenta = not variante.producto.stock_infinito

    if aplica_origen and lleva_cuenta and not permitir_faltante:
        assert punto_venta_origen_id is not None
        disponible = cantidad_en(db, variante_id, punto_venta_origen_id)
        if disponible < cantidad:
            punto = obtener_punto(db, punto_venta_origen_id)
            raise ReglaDeNegocio(
                f"No hay stock suficiente en {punto.nombre}: "
                f"hay {disponible} y se piden {cantidad}"
            )

    movimiento = MovimientoStock(
        tipo=tipo,
        variante_id=variante_id,
        punto_venta_origen_id=punto_venta_origen_id,
        punto_venta_destino_id=punto_venta_destino_id,
        cantidad=cantidad,
        remito_id=remito_id,
        compra_id=compra_id,
        retiro_mercaderia_id=retiro_mercaderia_id,
        motivo_baja_id=motivo_baja_id,
        auditoria_id=auditoria_id,
        referencia_venta_id=referencia_venta_id,
        usuario_id=autor.id,
        timestamp=ahora_db(),
        notas=notas,
    )
    db.add(movimiento)

    if lleva_cuenta:
        if aplica_origen:
            assert punto_venta_origen_id is not None
            origen = fila_de_stock(db, variante_id, punto_venta_origen_id)
            origen.cantidad -= cantidad
            origen.updated_at = ahora_db()
        if aplica_destino:
            assert punto_venta_destino_id is not None
            destino = fila_de_stock(db, variante_id, punto_venta_destino_id)
            destino.cantidad += cantidad
            destino.updated_at = ahora_db()

    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion=f"stock.{tipo.value}",
        entidad="movimientos_stock",
        entidad_id=movimiento.id,
        estado_nuevo=movimiento,
        ip_origen=ip_origen,
    )
    return movimiento


# ============================================================================
# MÍNIMOS
# ============================================================================


def minimos_de_variante(
    db: Session, variante_id: int, punto_de_venta_id: int | None = None
) -> dict:
    """
    Los mínimos de una variante tal como rigen en cada ubicación —lo mismo
    que muestra la columna "Mínimo" del listado—, para precargar el modal.

    No se leen de UNA fila: cada fila guarda las tres columnas pero solo la
    de su tipo rige (`COLUMNA_MINIMO`), y las otras quedan con valores viejos
    que no significan nada. Por eso el CD sale de la fila del CD, el online
    de la online y el de local de la fila de `punto_de_venta_id` si es un
    local, o si no, del valor común de los locales (None con
    `locales_distintos` si no coinciden). None también si no hay fila.
    """
    obtener_variante(db, variante_id)
    filas = db.execute(
        select(Stock)
        .where(Stock.variante_id == variante_id)
        .options(joinedload(Stock.punto_de_venta))
    ).unique().scalars().all()

    def del_tipo(tipo):
        return {f.stock_minimo for f in filas if f.punto_de_venta.tipo == tipo}

    def unico(valores):
        return next(iter(valores)) if len(valores) == 1 else None

    locales = del_tipo(TipoPuntoVenta.LOCAL)
    elegida = next(
        (f for f in filas
         if f.punto_de_venta_id == punto_de_venta_id
         and f.punto_de_venta.tipo == TipoPuntoVenta.LOCAL),
        None,
    )
    return {
        "stock_minimo_cd": unico(del_tipo(TipoPuntoVenta.CD)),
        "stock_minimo_online": unico(del_tipo(TipoPuntoVenta.ONLINE)),
        "stock_minimo_local": elegida.stock_minimo if elegida else unico(locales),
        "locales_distintos": len(locales) > 1,
    }


def definir_minimos(
    db: Session,
    autor: Usuario,
    variante_id: int,
    *,
    stock_minimo_cd: int | None = None,
    stock_minimo_online: int | None = None,
    stock_minimo_local: int | None = None,
    solo_punto_de_venta_id: int | None = None,
    ip_origen: str | None = None,
) -> list[Stock]:
    """
    Cambia los mínimos de las filas de stock de una variante: el de CD en
    las filas de depósito, el online en las de la tienda online y el de
    local en las de los locales. Las Ubicaciones Especiales no llevan mínimo.
    Es lo único que se edita a mano en esta tabla: la CANTIDAD nunca se toca
    así —para eso están los movimientos—, pero el mínimo es una decisión de
    reposición, no un hecho del depósito.

    `solo_punto_de_venta_id` acota el mínimo de LOCAL a ese único local (tiene
    que ser de tipo local); los de CD y online siguen aplicando a todas sus
    filas. Sin él, el de local va a todos los locales.

    Solo toca filas que ya existen — no crea stock en ubicaciones que nunca
    tuvieron esta variante; para eso ya está `fila_de_stock` en el flujo de
    movimientos.
    """
    valores = {
        TipoPuntoVenta.CD: stock_minimo_cd,
        TipoPuntoVenta.ONLINE: stock_minimo_online,
        TipoPuntoVenta.LOCAL: stock_minimo_local,
    }
    for valor in valores.values():
        if valor is not None and valor < 0:
            raise ReglaDeNegocio("El stock mínimo no puede ser negativo")

    obtener_variante(db, variante_id)

    if solo_punto_de_venta_id is not None:
        punto = obtener_punto(db, solo_punto_de_venta_id)
        if punto.tipo != TipoPuntoVenta.LOCAL:
            raise ReglaDeNegocio(
                "El mínimo de un solo local se define desde la fila de un local"
            )

    filas = db.execute(
        select(Stock)
        .where(Stock.variante_id == variante_id)
        .options(joinedload(Stock.punto_de_venta))
    ).unique().scalars().all()

    tocadas = []
    for fila in filas:
        tipo = fila.punto_de_venta.tipo
        columna = COLUMNA_MINIMO.get(tipo)
        valor_nuevo = valores.get(tipo)
        if columna is None or valor_nuevo is None:
            continue
        if (
            tipo == TipoPuntoVenta.LOCAL
            and solo_punto_de_venta_id is not None
            and fila.punto_de_venta_id != solo_punto_de_venta_id
        ):
            continue
        if getattr(fila, columna) == valor_nuevo:
            continue

        antes = snapshot(fila)
        setattr(fila, columna, valor_nuevo)
        fila.updated_at = ahora_db()
        db.flush()

        registrar_auditoria(
            db,
            usuario_id=autor.id,
            accion="stock.minimos",
            entidad="stock",
            entidad_id=fila.id,
            estado_anterior=antes,
            estado_nuevo=fila,
            ip_origen=ip_origen,
        )
        tocadas.append(fila)

    return tocadas


# ============================================================================
# CONSULTAS
# ============================================================================


def _consulta_base(scope: DeviceScope):
    """
    El SELECT de stock con el aislamiento por dispositivo ya aplicado.

    El filtro se pone acá y no en cada endpoint: es la diferencia entre "un
    vendedor ve su local" y "un vendedor ve todo porque este endpoint se
    olvidó del filtro".
    """
    consulta = (
        select(Stock)
        .join(PuntoDeVenta, PuntoDeVenta.id == Stock.punto_de_venta_id)
        .join(Variante, Variante.id == Stock.variante_id)
        .join(Producto, Producto.id == Variante.producto_id)
        .where(PuntoDeVenta.tipo != TipoPuntoVenta.ESPECIAL)
        .options(
            joinedload(Stock.punto_de_venta),
            joinedload(Stock.variante).joinedload(Variante.producto),
        )
    )

    if scope.restringido:
        if scope.sin_asignacion:
            # Sin ubicación asignada no hay nada que mostrar. Se filtra con
            # un imposible en vez de devolver la lista vacía a mano para que
            # el conteo, el paginado y el orden sigan un solo camino.
            return consulta.where(Stock.id.is_(None))
        return consulta.where(Stock.punto_de_venta_id == scope.punto_de_venta_id)
    return consulta


def listar_stock(
    db: Session,
    scope: DeviceScope,
    punto_de_venta_id: int | None = None,
    categoria_id: int | None = None,
    proveedor_id: int | None = None,
    busqueda: str | None = None,
    solo_bajo_minimo: bool = False,
    incluir_sin_stock: bool = True,
    todos_los_locales: bool = False,
    usuario_id: int | None = None,
    punto_de_venta_dispositivo: int | None = None,
    pagina: int = 1,
    tamano: int | None = 50,
) -> tuple[list[Stock], int]:
    """
    Filtros del Principio 5, todos resueltos en el backend.

    `todos_los_locales=True` es la única excepción al aislamiento por
    dispositivo de todo el módulo: una vendedora consultando si OTRO local
    tiene stock para el cliente que tiene enfrente ("acá no hay, ¿dónde
    sí?"). Es de solo lectura — no toca `DeviceScope.exigir()`, que sigue
    bloqueando cualquier baja, remito o movimiento sobre un local ajeno
    exactamente igual que siempre.

    `usuario_id` + `punto_de_venta_dispositivo` (los dos juntos, o ninguno)
    calculan `StockResponse.reservado_carrito`: cuánto de cada variante ya
    tiene ESE usuario en SU venta en curso en ESA ubicación. No toca
    `Stock.cantidad` — la columna sigue siendo el stock real, así la
    pantalla general de stock no se ve afectada; es dato adicional para que
    la consulta de stock del celular no ofrezca vender lo que ya se está
    vendiendo.
    """
    consulta_scope = DeviceScope(restringido=False) if todos_los_locales else scope
    consulta = _consulta_base(consulta_scope)

    if punto_de_venta_id is not None:
        # Si un vendedor pide otra ubicación, el scope ya la descartó arriba;
        # este filtro solo acota dentro de lo que puede ver.
        consulta = consulta.where(Stock.punto_de_venta_id == punto_de_venta_id)
    if categoria_id is not None:
        from app.services.categorias import rama_de_ids

        consulta = consulta.where(Producto.categoria_id.in_(rama_de_ids(db, categoria_id)))
    if proveedor_id is not None:
        consulta = consulta.where(Producto.proveedor_id == proveedor_id)
    if busqueda:
        # Las mismas tres formas de nombrar un artículo que el listado de
        # productos: código de etiqueta (con o sin dígito verificador), SKU
        # o parte de la descripción — mismo criterio, un solo lugar
        # (Principio 2: `condiciones_codigo_variante`).
        from app.services.productos import condiciones_codigo_variante

        texto = busqueda.strip().upper()
        patron = f"%{texto}%"
        consulta = consulta.where(
            or_(
                *condiciones_codigo_variante(texto),
                Producto.sku.ilike(patron),
                Producto.descripcion.ilike(patron),
            )
        )
    if solo_bajo_minimo:
        # `minimo_aplicable_sql() > 0` deja afuera los que nunca tuvieron un mínimo
        # configurado (columna no nullable, default 0): sin esto, cualquier
        # producto en cero aparecería como "bajo mínimo" aunque nadie haya
        # definido ninguno. Mismo criterio que `alertas()`, más abajo.
        consulta = consulta.where(Stock.cantidad <= minimo_aplicable_sql(), minimo_aplicable_sql() > 0)
    if not incluir_sin_stock:
        consulta = consulta.where(Stock.cantidad > 0)

    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()

    consulta_ordenada = consulta.order_by(
        func.lower(Producto.descripcion), Variante.codigo_completo, PuntoDeVenta.codigo
    )
    # `tamano=None` trae todo lo filtrado sin paginar — lo usa la
    # exportación a Excel, que necesita las filas completas y no solo la
    # página que se ve en pantalla.
    if tamano is not None:
        consulta_ordenada = consulta_ordenada.limit(tamano).offset((pagina - 1) * tamano)

    filas = (
        db.execute(consulta_ordenada)
        .unique()
        .scalars()
        .all()
    )
    filas = list(filas)

    # Precio con el descuento propio del producto ya aplicado — mismo
    # cálculo que `agregar_item` en ventas.py, para que el precio de esta
    # consulta y el que se termina cobrando sean el mismo número.
    from app.services import configuracion as servicio_configuracion
    from app.services import descuentos as servicio_descuentos

    config = servicio_configuracion.obtener_configuracion(db)
    redondeo = Decimal(config.redondeo) if config else Decimal("1")

    # Lo que el usuario ya tiene en SU carrito en curso en esa ubicación
    # puntual, variante por variante.
    reservas: dict[int, int] = {}
    if usuario_id is not None and punto_de_venta_dispositivo is not None:
        from app.services.ventas import venta_en_curso

        venta = venta_en_curso(db, usuario_id, punto_de_venta_dispositivo)
        if venta is not None:
            for item in venta.items:
                reservas[item.variante_id] = reservas.get(item.variante_id, 0) + 1

    for fila in filas:
        producto = fila.variante.producto
        fila.precio_con_descuento = servicio_descuentos.aplicar_descuentos(
            Decimal(fila.variante.precio_venta_efectivo),
            Decimal(producto.descuento_producto),
            Decimal("0"),
            redondeo,
        )
        fila.reservado_carrito = (
            reservas.get(fila.variante_id, 0)
            if fila.punto_de_venta_id == punto_de_venta_dispositivo
            else 0
        )

    return filas, total


def opciones_locales(db: Session) -> list[PuntoDeVenta]:
    """
    Todas las ubicaciones activas (CD incluido), para el combo de filtro de
    los reportes de stock. Sirve para que el frontend arme el combo sin
    pedirle nada a `/api/v1/puntos-de-venta` — ese endpoint exige permiso
    de Configuración, que un perfil con solo Reportes no tiene.
    """
    return list(
        db.execute(
            select(PuntoDeVenta)
            .where(PuntoDeVenta.activo.is_(True))
            .order_by(func.lower(PuntoDeVenta.nombre))
        ).scalars()
    )


def alertas(db: Session, scope: DeviceScope, limite: int = 200) -> list[Stock]:
    """
    Lo que hay que reponer: cantidad en el mínimo o por debajo.

    Con `<=` y no `<`: estar justo en el mínimo ya es la señal de reponer —
    es lo que significa haber puesto ese número.

    Deja afuera las filas con mínimo en cero, que son las que nadie
    configuró: si entraran, todo artículo sin stock aparecería como alerta y
    la lista dejaría de servir para decidir qué pedir.
    """
    consulta = (
        _consulta_base(scope)
        .where(Stock.cantidad <= minimo_aplicable_sql(), minimo_aplicable_sql() > 0)
        .order_by((Stock.cantidad - minimo_aplicable_sql()), func.lower(Producto.descripcion))
        .limit(limite)
    )
    return list(db.execute(consulta).unique().scalars().all())


def consulta_cruzada(
    db: Session,
    busqueda: str | None = None,
    categoria_id: int | None = None,
    proveedor_id: int | None = None,
    punto_de_venta_id: int | None = None,
    pagina: int = 1,
    tamano: int | None = 10,
) -> tuple[list[dict], list[PuntoDeVenta], int, list[PuntoDeVenta]]:
    """
    Tabla pivotada: variantes × puntos de venta.

    Sin aislamiento por dispositivo: es una vista de reporting global para
    roles con acceso al módulo REPORTES.

    `tamano=None` trae todas las filas que matchean los filtros, sin
    paginar: lo usa la exportación a Excel, que necesita el total filtrado
    y no solo la página que se ve en pantalla.

    `punto_de_venta_id` angosta las COLUMNAS (no las filas): con un local
    elegido, la tabla compara ese local contra el CD en vez de mostrar
    todos los puntos de venta — el CD queda siempre porque es contra lo que
    se compara cualquier local. Sin filtro, las Ubicaciones Especiales
    (ej. Productos Fallados) quedan afuera de las columnas por defecto —
    no son stock vendible — pero se pueden elegir igual: para eso están en
    `opciones_locales`, la lista completa para el combo del filtro.

    Retorna (filas_pivot, columnas, total_variantes, opciones_locales).
    """
    from sqlalchemy import case as sa_case, literal

    # 1. Columnas: todos los PdV activos, CD primero, luego alpha por nombre.
    # Con punto_de_venta_id, se acota a ese local + el/los CD. Sin filtro,
    # las Ubicaciones Especiales quedan afuera (no cuentan como vendible).
    consulta_columnas = select(PuntoDeVenta).where(PuntoDeVenta.activo.is_(True))
    if punto_de_venta_id is not None:
        consulta_columnas = consulta_columnas.where(
            (PuntoDeVenta.tipo == TipoPuntoVenta.CD)
            | (PuntoDeVenta.id == punto_de_venta_id)
        )
    else:
        consulta_columnas = consulta_columnas.where(
            PuntoDeVenta.tipo != TipoPuntoVenta.ESPECIAL
        )

    columnas = db.execute(
        consulta_columnas.order_by(
            sa_case((PuntoDeVenta.tipo == TipoPuntoVenta.CD, literal(0)), else_=literal(1)),
            func.lower(PuntoDeVenta.nombre),
        )
    ).scalars().all()

    col_ids = [c.id for c in columnas]

    # Opciones del combo de filtro: todo lo no-CD activo, especiales
    # incluidas — independiente de qué columnas se estén mostrando ahora.
    # Sirve para que el frontend arme el combo sin pedirle nada a
    # /api/v1/puntos-de-venta (exige permiso de Configuración, que un
    # perfil con solo Reportes no tiene).
    opciones_locales = db.execute(
        select(PuntoDeVenta)
        .where(PuntoDeVenta.activo.is_(True), PuntoDeVenta.tipo != TipoPuntoVenta.CD)
        .order_by(func.lower(PuntoDeVenta.nombre))
    ).scalars().all()

    # 2. Variantes que cumplen los filtros
    consulta_variantes = (
        select(Variante)
        .join(Producto, Producto.id == Variante.producto_id)
        .where(Producto.activo.is_(True))
        .options(
            # Las fotos, para la miniatura (`Variante.foto_url`): en tandas
            # y no una consulta por fila.
            joinedload(Variante.producto).selectinload(Producto.fotos),
            selectinload(Variante.fotos),
        )
    )
    if busqueda:
        # Mismo criterio que `listar_stock` (Principio 2): código de
        # etiqueta con o sin dígito verificador, SKU o descripción.
        from app.services.productos import condiciones_codigo_variante

        texto = busqueda.strip().upper()
        patron = f"%{texto}%"
        consulta_variantes = consulta_variantes.where(
            or_(
                *condiciones_codigo_variante(texto),
                Producto.sku.ilike(patron),
                Producto.descripcion.ilike(patron),
            )
        )
    if categoria_id is not None:
        from app.services.categorias import rama_de_ids
        consulta_variantes = consulta_variantes.where(
            Producto.categoria_id.in_(rama_de_ids(db, categoria_id))
        )
    if proveedor_id is not None:
        consulta_variantes = consulta_variantes.where(
            Producto.proveedor_id == proveedor_id
        )

    total = db.execute(
        select(func.count()).select_from(consulta_variantes.order_by(None).subquery())
    ).scalar_one()

    consulta_variantes = consulta_variantes.order_by(
        func.lower(Producto.descripcion), Variante.codigo_completo
    )
    if tamano is not None:
        consulta_variantes = consulta_variantes.limit(tamano).offset((pagina - 1) * tamano)

    variantes = db.execute(consulta_variantes).unique().scalars().all()

    if not variantes:
        return [], list(columnas), total, list(opciones_locales)

    # 3. Stock de esas variantes en todos los PdV (una sola query)
    variante_ids = [v.id for v in variantes]
    filas_stock = db.execute(
        select(Stock.variante_id, Stock.punto_de_venta_id, Stock.cantidad)
        .where(
            Stock.variante_id.in_(variante_ids),
            Stock.punto_de_venta_id.in_(col_ids),
        )
    ).all()

    # 4. Pivot en Python: {variante_id: {punto_id: cantidad}}
    pivot: dict[int, dict[int, int]] = {v.id: {} for v in variantes}
    for fila in filas_stock:
        pivot[fila.variante_id][fila.punto_de_venta_id] = fila.cantidad

    # 5. Armar las filas resultado
    resultado = []
    for v in variantes:
        resultado.append({
            "variante_id": v.id,
            "codigo_completo": v.codigo_completo,
            "verificador": v.verificador,
            "descripcion": v.producto.descripcion,
            "descripcion_sufijo": None if v.es_base else v.descripcion_sufijo,
            "foto_url": v.foto_url,
            "stocks": pivot[v.id],
        })

    return resultado, list(columnas), total, list(opciones_locales)


def listar_movimientos(
    db: Session,
    scope: DeviceScope,
    variante_id: int | None = None,
    punto_de_venta_id: int | None = None,
    tipo: str | None = None,
    desde=None,
    hasta=None,
    pagina: int = 1,
    tamano: int = 50,
) -> tuple[list[MovimientoStock], int]:
    """
    El historial. Un vendedor ve los movimientos que tocan su local, de
    cualquiera de las dos puntas: lo que le llegó y lo que salió de ahí.
    """
    consulta = select(MovimientoStock).options(
        joinedload(MovimientoStock.variante).joinedload(Variante.producto),
        joinedload(MovimientoStock.origen),
        joinedload(MovimientoStock.destino),
        joinedload(MovimientoStock.usuario),
        joinedload(MovimientoStock.motivo_baja),
    )

    if scope.restringido:
        if scope.sin_asignacion:
            return [], 0
        propio = scope.punto_de_venta_id
        consulta = consulta.where(
            (MovimientoStock.punto_venta_origen_id == propio)
            | (MovimientoStock.punto_venta_destino_id == propio)
        )

    if variante_id is not None:
        consulta = consulta.where(MovimientoStock.variante_id == variante_id)
    if punto_de_venta_id is not None:
        consulta = consulta.where(
            (MovimientoStock.punto_venta_origen_id == punto_de_venta_id)
            | (MovimientoStock.punto_venta_destino_id == punto_de_venta_id)
        )
    if tipo:
        consulta = consulta.where(MovimientoStock.tipo == TipoMovimiento(tipo))
    if desde is not None:
        consulta = consulta.where(MovimientoStock.timestamp >= desde)
    if hasta is not None:
        consulta = consulta.where(MovimientoStock.timestamp <= hasta)

    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()

    filas = (
        db.execute(
            # Del más reciente al más viejo: el historial se lee empezando por
            # lo último que pasó. El id desempata los del mismo instante.
            consulta.order_by(MovimientoStock.timestamp.desc(), MovimientoStock.id.desc())
            .limit(tamano)
            .offset((pagina - 1) * tamano)
        )
        .unique()
        .scalars()
        .all()
    )
    return list(filas), total


def valorizado(db: Session, scope: DeviceScope) -> Decimal:
    """
    Cuánto vale lo que hay, a precio de venta.

    Usa el precio EFECTIVO de cada variante —el propio si tiene, el del
    producto si no—, la misma regla que el listado de productos.
    """
    precio = func.coalesce(Variante.precio_venta, Producto.precio_venta)
    consulta = _consulta_base(scope).with_only_columns(
        func.coalesce(func.sum(Stock.cantidad * precio), 0)
    )
    return db.execute(consulta.order_by(None)).scalar_one()
