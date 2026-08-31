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

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, joinedload

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.device_scope import DeviceScope
from app.core.utils import ahora_db
from app.models.producto import Producto, Variante
from app.models.punto_de_venta import PuntoDeVenta, TipoPuntoVenta
from app.models.stock import MovimientoStock, Stock, TipoMovimiento
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


def fila_de_stock(db: Session, variante_id: int, punto_de_venta_id: int) -> Stock:
    """
    La fila de stock de esa variante en esa ubicación, creándola en cero si
    todavía no existe.

    Se crea al primer movimiento y no al dar de alta el producto: un catálogo
    de 5.000 variantes por 6 ubicaciones serían 30.000 filas en cero que no
    dicen nada. "Sin fila" y "cantidad 0" significan lo mismo, y el que
    pregunta recibe 0 en los dos casos.
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
    puntas: tuple[str, ...] | None = None,
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

    if aplica_origen and lleva_cuenta:
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


def minimo_aplicable(punto: PuntoDeVenta, fila: Stock) -> int:
    """
    Cuál de los dos mínimos rige en esta ubicación.

    El CD abastece a todos los locales, así que su colchón es de otro orden
    que el de una góndola. Cuál aplica lo decide el TIPO del punto de venta y
    no quien carga el dato: si fuera una elección manual, dos locales con el
    mismo artículo podrían estar mirando columnas distintas.
    """
    if punto.tipo == TipoPuntoVenta.CD:
        return fila.stock_minimo_cd
    return fila.stock_minimo_local


def _minimo_sql():
    """La misma regla que `minimo_aplicable`, para usar dentro de una query."""
    return case(
        (PuntoDeVenta.tipo == TipoPuntoVenta.CD, Stock.stock_minimo_cd),
        else_=Stock.stock_minimo_local,
    )


def definir_minimos(
    db: Session,
    autor: Usuario,
    variante_id: int,
    punto_de_venta_id: int,
    *,
    stock_minimo_cd: int | None = None,
    stock_minimo_local: int | None = None,
    ip_origen: str | None = None,
) -> Stock:
    """
    Cambia los mínimos de una fila de stock.

    Es lo único que se edita a mano en esta tabla: la CANTIDAD nunca se toca
    así —para eso están los movimientos—, pero el mínimo es una decisión de
    reposición, no un hecho del depósito.
    """
    for valor in (stock_minimo_cd, stock_minimo_local):
        if valor is not None and valor < 0:
            raise ReglaDeNegocio("El stock mínimo no puede ser negativo")

    obtener_variante(db, variante_id)
    obtener_punto(db, punto_de_venta_id)

    fila = fila_de_stock(db, variante_id, punto_de_venta_id)
    antes = snapshot(fila)

    if stock_minimo_cd is not None:
        fila.stock_minimo_cd = stock_minimo_cd
    if stock_minimo_local is not None:
        fila.stock_minimo_local = stock_minimo_local
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
    return fila


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
    pagina: int = 1,
    tamano: int = 50,
) -> tuple[list[Stock], int]:
    """Filtros del Principio 5, todos resueltos en el backend."""
    consulta = _consulta_base(scope)

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
        # productos: código de etiqueta, SKU o parte de la descripción.
        patron = f"%{busqueda.strip()}%"
        consulta = consulta.where(
            Variante.codigo_completo.ilike(patron)
            | Producto.sku.ilike(patron)
            | Producto.descripcion.ilike(patron)
        )
    if solo_bajo_minimo:
        consulta = consulta.where(Stock.cantidad <= _minimo_sql())
    if not incluir_sin_stock:
        consulta = consulta.where(Stock.cantidad > 0)

    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()

    filas = (
        db.execute(
            consulta.order_by(
                func.lower(Producto.descripcion), Variante.codigo_completo, PuntoDeVenta.codigo
            )
            .limit(tamano)
            .offset((pagina - 1) * tamano)
        )
        .unique()
        .scalars()
        .all()
    )
    return list(filas), total


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
        .where(Stock.cantidad <= _minimo_sql(), _minimo_sql() > 0)
        .order_by((Stock.cantidad - _minimo_sql()), func.lower(Producto.descripcion))
        .limit(limite)
    )
    return list(db.execute(consulta).unique().scalars().all())


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
