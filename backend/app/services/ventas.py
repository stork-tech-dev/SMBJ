"""
El flujo de venta: del primer código escaneado hasta el stock descontado.

Dos ideas gobiernan este archivo.

**La venta se arma sobre la base, no en memoria.** Desde el primer producto
hay una fila `en_curso` con sus ítems. Una vendedora a la que se le cierra
la app o se le cae la sesión encuentra su venta donde la dejó, y el banner
"tenés una venta sin concluir" del home sale de acá.

**Nada pasa hasta confirmar.** Mientras la venta está `en_curso` no se tocó
el stock, ni los puntos, ni el saldo de ninguna seña: es un carrito. Al
confirmar, esas tres cosas y la auditoría se escriben en UNA transacción. Si
cualquiera falla, no queda ninguna aplicada — una venta que descontó stock
pero no sumó puntos es peor que una venta que no ocurrió.

Los importes se recalculan enteros en `_recalcular()` después de cada cambio,
y no se van parcheando de a poco. Es más trabajo por request y es a propósito:
un total que se ajusta sumando y restando deltas se despega de sus ítems al
primer camino que alguien se olvide de actualizar, y el error no se ve hasta
que la caja no cierra.
"""

import secrets
import string
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.codigos import codigo_es_valido
from app.core.device_scope import DeviceScope
from app.core.utils import ahora_db, redondear
from app.models.cliente import TipoPunto
from app.models.dispositivo import Dispositivo
from app.models.medio_pago import MedioDePago, PlanCuotas
from app.models.producto import Variante
from app.models.promocion import Promocion
from app.models.sena import Sena
from app.models.stock import TipoMovimiento
from app.models.usuario import Usuario
from app.models.venta import EstadoVenta, Venta, VentaItem, VentaPago
from app.services import clientes as servicio_clientes
from app.services import configuracion as servicio_configuracion
from app.services import descuentos as servicio_descuentos
from app.services import medios_pago as servicio_medios
from app.services import promociones as servicio_promociones
from app.services import senas as servicio_senas
from app.services import stock as servicio_stock
from app.services.roles import NoEncontrado, ReglaDeNegocio
from app.services.turnos import verificar_bloqueo_turno

# Alfabeto del código de cambio. Sin I, O, 0 ni 1: la vendedora lo copia a
# mano al ticket de papel y después alguien lo tipea para hacer el cambio.
# Un cero que se lee como O es un cambio que no se puede buscar.
_ALFABETO_CAMBIO = "".join(
    c for c in (string.ascii_uppercase + string.digits) if c not in "IO01"
)
LARGO_CODIGO_CAMBIO = 8

# Cuántos medios de pago admite una venta. Dos: efectivo + tarjeta cubre lo
# que pasa en el mostrador, y con tres la pantalla del celular se vuelve
# impracticable.
MAX_MEDIOS_DE_PAGO = 2


# ============================================================================
# NUMERACIÓN Y CÓDIGO DE CAMBIO
# ============================================================================


def _siguiente_numero(db: Session) -> str:
    """
    Correlativo de la venta, formato V-000001.

    De una SEQUENCE y no de MAX(numero)+1: dos cajas confirmando al mismo
    tiempo sacan números distintos sin bloquearse.
    """
    numero = db.execute(select(func.nextval("ventas_numero_seq"))).scalar_one()
    return f"V-{numero:06d}"


def generar_codigo_cambio(db: Session) -> str:
    """
    Código alfanumérico de 8 caracteres, único, para el ticket de cambio.

    No se imprime: en los locales no hay impresoras conectadas al sistema.
    La vendedora lo copia a mano al ticket de papel, y por eso el alfabeto
    excluye los caracteres que se confunden al leer una letra manuscrita.

    Es aleatorio y no correlativo a propósito: un código secuencial dejaría
    adivinar el de la venta siguiente, y con él se puede pedir un cambio.

    Reintenta ante una colisión en vez de confiar en que no va a pasar. Con
    32^8 combinaciones es improbable, pero "improbable" no es "imposible" y
    el UNIQUE de la base cortaría la confirmación de una venta real.
    """
    for _ in range(10):
        codigo = "".join(secrets.choice(_ALFABETO_CAMBIO) for _ in range(LARGO_CODIGO_CAMBIO))
        existe = db.execute(
            select(Venta.id).where(Venta.codigo_cambio == codigo)
        ).scalar_one_or_none()
        if existe is None:
            return codigo
    raise ReglaDeNegocio(
        "No se pudo generar un código de cambio único: reintentá la confirmación"
    )


# ============================================================================
# LECTURA
# ============================================================================


def obtener_venta(db: Session, venta_id: int, scope: DeviceScope | None = None) -> Venta:
    """
    Una venta, verificando que este dispositivo pueda verla.

    El scope se exige acá y no solo en el endpoint: es la última barrera
    antes de devolver datos de otro local, y así cualquier camino nuevo que
    llame a esta función lo respeta sin tener que acordarse.
    """
    venta = db.get(Venta, venta_id)
    if venta is None:
        raise NoEncontrado("Venta inexistente")
    if scope is not None:
        scope.exigir(venta.punto_de_venta_id)
    return venta


def venta_en_curso(db: Session, usuario_id: int, punto_de_venta_id: int) -> Venta | None:
    """
    La venta sin concluir de esta vendedora en este local, si la hay.

    Es lo que alimenta el banner del home mobile. Va por (usuario, local) y
    no por dispositivo: la vendedora puede haber arrancado la venta en un
    celular y seguirla en otro del mismo local.
    """
    return (
        db.execute(
            select(Venta)
            .where(
                Venta.usuario_id == usuario_id,
                Venta.punto_de_venta_id == punto_de_venta_id,
                Venta.estado == EstadoVenta.EN_CURSO,
            )
            .order_by(Venta.created_at.desc())
        )
        .scalars()
        .first()
    )


def por_codigo_cambio(db: Session, codigo: str) -> Venta:
    """
    La venta original a partir del código del ticket de cambio.

    Insensible a mayúsculas: quien lo tipea lo está copiando de un papel
    escrito a mano.
    """
    limpio = (codigo or "").strip().upper()
    if not limpio:
        raise NoEncontrado("Hay que ingresar un código de cambio")

    venta = db.execute(
        select(Venta).where(Venta.codigo_cambio == limpio)
    ).scalar_one_or_none()
    if venta is None:
        raise NoEncontrado(f"No hay ninguna venta con el código de cambio {limpio}")
    return venta


def listar_ventas(
    db: Session,
    scope: DeviceScope,
    *,
    punto_de_venta_id: int | None = None,
    cliente_id: int | None = None,
    usuario_id: int | None = None,
    estado: EstadoVenta | None = None,
    numero: str | None = None,
    total_desde: Decimal | None = None,
    total_hasta: Decimal | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    pagina: int = 1,
    tamano: int = 50,
) -> tuple[list[Venta], int]:
    """
    Listado con los filtros del Principio 5, todos resueltos en el backend.

    Un vendedor sin local asignado recibe la lista vacía y no un 403: tiene
    que poder abrir la pantalla y leer por qué no hay nada.
    """
    if scope.restringido and scope.sin_asignacion:
        return [], 0

    consulta = select(Venta).options(
        joinedload(Venta.cliente),
        joinedload(Venta.punto_de_venta),
        joinedload(Venta.usuario),
    )

    if scope.restringido:
        consulta = consulta.where(Venta.punto_de_venta_id == scope.punto_de_venta_id)
    elif punto_de_venta_id is not None:
        consulta = consulta.where(Venta.punto_de_venta_id == punto_de_venta_id)

    if cliente_id is not None:
        consulta = consulta.where(Venta.cliente_id == cliente_id)
    if usuario_id is not None:
        consulta = consulta.where(Venta.usuario_id == usuario_id)
    if estado is not None:
        consulta = consulta.where(Venta.estado == estado)
    if numero:
        consulta = consulta.where(Venta.numero.ilike(f"%{numero.strip()}%"))
    if total_desde is not None:
        consulta = consulta.where(Venta.total >= total_desde)
    if total_hasta is not None:
        consulta = consulta.where(Venta.total <= total_hasta)
    if fecha_desde is not None:
        consulta = consulta.where(func.date(Venta.created_at) >= fecha_desde)
    if fecha_hasta is not None:
        consulta = consulta.where(func.date(Venta.created_at) <= fecha_hasta)

    total = db.execute(select(func.count()).select_from(consulta.subquery())).scalar_one()

    filas = (
        db.execute(
            consulta.order_by(Venta.created_at.desc(), Venta.id.desc())
            .offset((pagina - 1) * tamano)
            .limit(tamano)
        )
        .unique()
        .scalars()
        .all()
    )
    return list(filas), total


# ============================================================================
# ARMADO DEL CARRITO
# ============================================================================


def iniciar_venta(
    db: Session,
    autor: Usuario,
    dispositivo: Dispositivo,
    scope: DeviceScope,
    ip_origen: str | None = None,
) -> Venta:
    """
    Abre una venta, o devuelve la que ya estaba abierta.

    Devolver la existente en vez de crear otra no es una comodidad: dos
    ventas `en_curso` de la misma vendedora en el mismo local significan que
    una quedó huérfana, con productos que nadie va a cobrar y que tampoco
    están reservados. El banner del home lleva justamente a esta.
    """
    punto_de_venta_id = dispositivo.punto_de_venta_id
    if punto_de_venta_id is None:
        raise ReglaDeNegocio(
            "Este dispositivo no tiene un local asignado: no se puede vender desde acá"
        )
    scope.exigir(punto_de_venta_id)

    abierta = venta_en_curso(db, autor.id, punto_de_venta_id)
    if abierta is not None:
        return abierta

    venta = Venta(
        numero=_siguiente_numero(db),
        punto_de_venta_id=punto_de_venta_id,
        usuario_id=autor.id,
        dispositivo_id=dispositivo.id,
        estado=EstadoVenta.EN_CURSO,
        subtotal=Decimal("0"),
        descuento_total=Decimal("0"),
        recargo_total=Decimal("0"),
        total=Decimal("0"),
        puntos_acumulados=0,
        created_at=ahora_db(),
        updated_at=ahora_db(),
    )
    db.add(venta)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="venta.iniciar",
        entidad="ventas",
        entidad_id=venta.id,
        estado_nuevo=venta,
        ip_origen=ip_origen,
    )
    return venta


def _exigir_en_curso(venta: Venta) -> None:
    """
    Una venta confirmada o anulada ya no se arma.

    Sin esto, agregar un ítem a una venta cobrada cambiaría su total después
    de que el cliente pagó, y el stock descontado dejaría de coincidir con el
    detalle.
    """
    if venta.estado != EstadoVenta.EN_CURSO:
        raise ReglaDeNegocio(
            f"La venta {venta.numero} está {venta.estado.value}: ya no se puede modificar"
        )


def buscar_variante(db: Session, codigo: str) -> Variante:
    """
    La variante que corresponde a un código escaneado o tipeado.

    Acepta las dos formas que llegan del mostrador: la etiqueta completa con
    su dígito verificador (`SAB123R7`, lo que emite el lector) y el código
    sin dígito, que es como queda si alguien lo copia a mano y se le pierde
    el último carácter. El dígito NO se persiste: la columna guarda el cuerpo.
    """
    texto = (codigo or "").strip().upper()
    if not texto:
        raise NoEncontrado("Hay que ingresar un código")

    condiciones = [Variante.codigo_completo == texto]
    if codigo_es_valido(texto):
        condiciones.append(Variante.codigo_completo == texto[:-1])

    variante = (
        db.execute(
            select(Variante)
            .options(joinedload(Variante.producto))
            .where(or_(*condiciones))
        )
        .scalars()
        .first()
    )
    if variante is None:
        raise NoEncontrado(f"No hay ningún producto con el código {texto}")
    return variante


def agregar_item(
    db: Session,
    autor: Usuario,
    venta: Venta,
    *,
    codigo: str | None = None,
    variante_id: int | None = None,
    ip_origen: str | None = None,
) -> tuple[VentaItem, str | None]:
    """
    Suma UNA unidad al carrito. Devuelve el ítem y un aviso, si lo hay.

    El aviso de stock en cero NO bloquea, y eso es deliberado: la vendedora
    tiene el producto en la mano, así que el que está mal es el sistema, no
    ella. Frenar la venta ahí significaría no vender algo que está sobre el
    mostrador. Lo que sí hace el aviso es pedirle que controle el código,
    porque la otra explicación posible es que escaneó otra cosa.

    Cada unidad es una fila. Dos anillos iguales son dos ítems, porque la
    promoción 2x1 tiene que poder dejar uno en $0 y cobrar el otro.
    """
    _exigir_en_curso(venta)

    if variante_id is not None:
        variante = servicio_stock.obtener_variante(db, variante_id)
    else:
        assert codigo is not None, "Se requiere variante_id o codigo"
        variante = buscar_variante(db, codigo)

    producto = variante.producto
    if not producto.activo or not variante.activo:
        raise ReglaDeNegocio(
            f"'{producto.descripcion}' está dado de baja: no se puede vender"
        )

    aviso = None
    if not producto.stock_infinito:
        disponible = servicio_stock.cantidad_en(db, variante.id, venta.punto_de_venta_id)
        # Los que ya están en el carrito también cuentan: si hay 1 y es el
        # segundo que se escanea, el aviso corresponde igual.
        ya_en_carrito = sum(1 for i in venta.items if i.variante_id == variante.id)
        if disponible <= ya_en_carrito:
            aviso = (
                f"Sin stock de '{producto.descripcion}' en este local: controlá bien "
                "el código antes de continuar."
            )

    precio_lista = Decimal(variante.precio_venta_efectivo)
    redondeo = _redondeo(db)

    # El descuento propio del producto ya está en el precio de la etiqueta:
    # `precio_unitario` es lo que dice el cartel, y `precio_lista` es el
    # precio sin ningún descuento, que es el que vale para un cambio.
    precio_unitario = servicio_descuentos.aplicar_descuentos(
        precio_lista, Decimal(producto.descuento_producto), Decimal("0"), redondeo
    )

    item = VentaItem(
        venta_id=venta.id,
        variante_id=variante.id,
        precio_lista=precio_lista,
        precio_unitario=precio_unitario,
        descuento_item=Decimal("0"),
        precio_final=precio_unitario,
        en_promocion=False,
        orden=_proximo_orden(venta),
    )
    db.add(item)
    db.flush()
    # `venta.items` está cacheada por la relación: sin esto el recálculo
    # siguiente no vería el ítem recién agregado.
    db.refresh(venta)

    _recalcular(db, venta)
    return item, aviso


def _proximo_orden(venta: Venta) -> int:
    """
    El siguiente número de orden de carga.

    Se calcula sobre el máximo y no sobre la cantidad de ítems: quitar uno
    del medio dejaría dos ítems con el mismo orden, y el desempate de las
    promociones dejaría de ser estable.
    """
    return max((i.orden for i in venta.items), default=0) + 1


def quitar_item(
    db: Session, autor: Usuario, venta: Venta, item_id: int, ip_origen: str | None = None
) -> None:
    """Saca una unidad del carrito y vuelve a calcular todo."""
    _exigir_en_curso(venta)

    item = next((i for i in venta.items if i.id == item_id), None)
    if item is None:
        raise NoEncontrado("Ese ítem no está en esta venta")

    venta.items.remove(item)
    db.flush()
    db.refresh(venta)

    _recalcular(db, venta)


def asociar_cliente(
    db: Session,
    autor: Usuario,
    venta: Venta,
    cliente_id: int | None,
    ip_origen: str | None = None,
) -> Venta:
    """
    Asocia (o desasocia, con None) el cliente de la venta.

    Vuelve a calcular porque el cliente puede traer promociones propias: la
    misma bolsa de productos puede valer distinto según quién compre.
    """
    _exigir_en_curso(venta)

    if cliente_id is None:
        venta.cliente_id = None
    else:
        cliente = servicio_clientes.obtener_cliente(db, cliente_id)
        if not cliente.activo:
            raise ReglaDeNegocio(
                f"{cliente.nombre} está dado de baja: no se le puede facturar"
            )
        venta.cliente_id = cliente.id

    db.flush()
    _recalcular(db, venta)
    return venta


def aplicar_descuento_item(
    db: Session,
    autor: Usuario,
    venta: Venta,
    item_id: int,
    *,
    motivo_id: int | None,
    porcentaje: Decimal | None = None,
    ip_origen: str | None = None,
) -> VentaItem:
    """
    Aplica —o saca, con `motivo_id=None`— el descuento de una unidad.

    El orden importa y es el de la pantalla: primero el motivo, después el
    porcentaje. Sin motivo no hay descuento, porque un descuento que no se
    puede explicar no sirve para nada en el reporte de fin de mes.

    Las tres barreras, en este orden:
      1. El ítem no puede estar en promoción (serían dos beneficios).
      2. El porcentaje tiene que estar en la lista (nada de campo libre).
      3. La suma con el descuento propio del producto no puede pasar del tope.
    """
    _exigir_en_curso(venta)

    item = next((i for i in venta.items if i.id == item_id), None)
    if item is None:
        raise NoEncontrado("Ese ítem no está en esta venta")

    if motivo_id is None:
        item.motivo_descuento_id = None
        item.descuento_item = Decimal("0")
        item.porcentaje_modificado = False
        db.flush()
        _recalcular(db, venta)
        return item

    if item.en_promocion:
        raise ReglaDeNegocio(
            "Ese producto ya está en una promoción: una unidad no puede llevar "
            "promoción y descuento a la vez"
        )

    motivo = servicio_descuentos.obtener_motivo(db, motivo_id)
    elegido, modificado = servicio_descuentos.resolver_porcentaje(motivo, porcentaje)

    descuento_producto = Decimal(item.variante.producto.descuento_producto)
    servicio_descuentos.validar_tope(descuento_producto, elegido)

    item.motivo_descuento_id = motivo.id
    item.descuento_item = elegido
    item.porcentaje_modificado = modificado
    db.flush()

    _recalcular(db, venta)

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="venta.descuento",
        entidad="venta_items",
        entidad_id=item.id,
        estado_nuevo={
            "venta": venta.numero,
            "motivo": motivo.nombre,
            "porcentaje": elegido,
            "porcentaje_modificado": modificado,
            "precio_final": item.precio_final,
        },
        ip_origen=ip_origen,
    )
    return item


def elegir_promocion(
    db: Session,
    autor: Usuario,
    venta: Venta,
    promocion_id: int | None,
    ip_origen: str | None = None,
) -> Venta:
    """
    Fija a mano qué promoción se aplica, o la saca con None.

    El sistema ya elige sola la que más conviene cada vez que cambia el
    carrito (ver `_recalcular`). Esto existe para el caso en que el local
    quiera aplicar otra —o ninguna—, y **vale hasta el próximo cambio del
    carrito**: agregar o quitar un producto vuelve a disparar la elección
    automática. Es la única forma de que el total nunca quede peor de lo que
    corresponde por una promo elegida a mano y después olvidada.
    """
    _exigir_en_curso(venta)

    if promocion_id is None:
        _recalcular(db, venta, promocion=None, automatica=False)
        return venta

    promocion = servicio_promociones.obtener_promocion(db, promocion_id)
    aplicables = servicio_promociones.promociones_aplicables(db, venta.cliente_id)
    if promocion.id not in {p.id for p in aplicables}:
        raise ReglaDeNegocio(
            f"La promoción '{promocion.nombre}' no está vigente o no corresponde a "
            "esta venta"
        )

    _recalcular(db, venta, promocion=promocion, automatica=False)
    return venta


# ============================================================================
# CÁLCULO
# ============================================================================


def _redondeo(db: Session) -> Decimal:
    """El múltiplo al que se redondean los precios, de la configuración."""
    config = servicio_configuracion.obtener_configuracion(db)
    return Decimal(config.redondeo) if config else Decimal("1")


def _recalcular(
    db: Session,
    venta: Venta,
    *,
    promocion: Promocion | None = None,
    automatica: bool = True,
) -> Venta:
    """
    Recalcula la venta entera: promoción, precios de cada ítem e importes.

    Entera y no por partes. Ajustar el total sumando y restando deltas es más
    barato y se despega de los ítems al primer camino que se olvide de
    actualizarlo — y ese error no se ve hasta que la caja no cierra.

    El orden no es casual:
      1. Se limpia la promoción de todos los ítems y se recalcula el precio
         de cada uno con sus descuentos. Sin este reset, sacar un producto
         del carrito dejaría regalado uno que ya no completa ningún grupo.
      2. Se elige la promoción y se ponen en $0 las unidades que van gratis.
      3. Se suman los importes.
    """
    redondeo = _redondeo(db)

    # ---- 1. Precio de cada unidad, sin promoción -------------------------
    for item in venta.items:
        item.en_promocion = False
        descuento_producto = Decimal(item.variante.producto.descuento_producto)
        item.precio_unitario = servicio_descuentos.aplicar_descuentos(
            Decimal(item.precio_lista), descuento_producto, Decimal("0"), redondeo
        )
        item.precio_final = servicio_descuentos.aplicar_descuentos(
            Decimal(item.precio_lista),
            descuento_producto,
            Decimal(item.descuento_item),
            redondeo,
        )

    # ---- 2. Promoción ----------------------------------------------------
    elegida = _mejor_promocion(db, venta) if automatica else promocion
    venta.promocion_id = elegida.id if elegida else None

    if elegida is not None:
        for item in _items_alcanzados(db, venta, elegida):
            item.en_promocion = True
            item.precio_final = Decimal("0")

    # ---- 3. Importes -----------------------------------------------------
    venta.subtotal = redondear(sum((Decimal(i.precio_lista) for i in venta.items), Decimal("0")))
    cobrable = redondear(sum((Decimal(i.precio_final) for i in venta.items), Decimal("0")))
    venta.descuento_total = venta.subtotal - cobrable

    # Los pagos ya cargados dejan de valer si el total cambió: sus montos
    # sumaban el total viejo. Se descartan en vez de arrastrarse, para que no
    # quede una venta que dice estar paga por un importe que ya no es.
    if venta.pagos and cobrable != _suma_pagos(venta):
        venta.pagos.clear()
        db.flush()

    venta.recargo_total = redondear(
        sum((Decimal(p.recargo) for p in venta.pagos), Decimal("0"))
    )
    venta.total = cobrable + venta.recargo_total
    venta.updated_at = ahora_db()
    db.flush()
    return venta


def _suma_pagos(venta: Venta) -> Decimal:
    """Lo que cubren los pagos cargados, antes de recargos."""
    return redondear(sum((Decimal(p.monto) for p in venta.pagos), Decimal("0")))


def _items_alcanzados(db: Session, venta: Venta, promocion: Promocion) -> list[VentaItem]:
    """
    Las unidades que la promoción deja en $0.

    Un ítem con descuento aplicado queda AFUERA del agrupamiento, no solo sin
    regalo: si entrara, ocuparía un lugar en un grupo y podría empujar fuera
    de la promoción a otro que sí tenía derecho. Promoción y descuento son
    excluyentes, y esta es la mitad de esa regla que no está en el CHECK.
    """
    productos = servicio_promociones.productos_alcanzados(db, promocion)
    candidatos = [
        i
        for i in venta.items
        if i.variante.producto_id in productos and Decimal(i.descuento_item) == 0
    ]
    return servicio_promociones.elegir_unidades_gratis(candidatos, promocion)


def _mejor_promocion(db: Session, venta: Venta) -> Promocion | None:
    """
    La promoción vigente que más le conviene al cliente con este carrito.

    Se elige sola y se elige la MEJOR: el sistema no puede cobrarle de más a
    alguien porque la vendedora no se acordó de activar la promo del mes.
    Con empate gana la de menor id, que es la más vieja — un criterio
    estable, para que el mismo carrito dé siempre el mismo detalle.

    Devuelve None si ninguna deja algo en $0: marcar una promoción que no
    regala nada haría que el ticket dijera que hubo promoción cuando no la
    hubo.
    """
    if not venta.items:
        return None

    mejor: Promocion | None = None
    mejor_ahorro = Decimal("0")

    for promocion in servicio_promociones.promociones_aplicables(db, venta.cliente_id):
        gratis = _items_alcanzados(db, venta, promocion)
        ahorro = sum((Decimal(i.precio_final) for i in gratis), Decimal("0"))
        if ahorro > mejor_ahorro or (
            ahorro == mejor_ahorro and ahorro > 0 and mejor is not None
            and promocion.id < mejor.id
        ):
            mejor, mejor_ahorro = promocion, ahorro

    return mejor if mejor_ahorro > 0 else None


# ============================================================================
# COBRO
# ============================================================================


def registrar_pagos(
    db: Session,
    autor: Usuario,
    venta: Venta,
    pagos: list[dict],
    ip_origen: str | None = None,
) -> Venta:
    """
    Define con qué se paga. Reemplaza lo que hubiera cargado antes.

    Cada pago trae `medio_de_pago_id`, `monto` y, opcionalmente,
    `plan_cuotas_id` y `sena_id`. Los montos tienen que sumar EXACTAMENTE lo
    que valen los productos, sin recargos: el recargo lo calcula el sistema
    sobre cada parte y se suma después. Pedirle a la vendedora que cargue el
    monto con recargo incluido sería pedirle que haga la cuenta que el
    sistema tiene que hacer, y cualquier diferencia terminaría en la caja.

    Las señas NO se descuentan acá: se reservan y recién se consumen al
    confirmar, dentro de la misma transacción. Si se descontaran ahora, una
    venta abandonada se llevaría el saldo puesto.
    """
    _exigir_en_curso(venta)

    if not venta.items:
        raise ReglaDeNegocio("La venta no tiene productos: no hay nada que cobrar")
    if not pagos:
        raise ReglaDeNegocio("Hay que elegir al menos un medio de pago")
    if len(pagos) > MAX_MEDIOS_DE_PAGO:
        raise ReglaDeNegocio(
            f"Una venta admite hasta {MAX_MEDIOS_DE_PAGO} medios de pago"
        )

    cobrable = redondear(
        sum((Decimal(i.precio_final) for i in venta.items), Decimal("0"))
    )
    suma = redondear(sum((Decimal(p["monto"]) for p in pagos), Decimal("0")))
    if suma != cobrable:
        raise ReglaDeNegocio(
            f"Los medios de pago suman ${suma} y la venta es de ${cobrable}: "
            "tienen que coincidir"
        )

    habilita_sin_interes = _habilita_cuotas_sin_interes(venta)
    nuevos: list[VentaPago] = []

    for datos in pagos:
        monto = redondear(Decimal(datos["monto"]))
        if monto <= 0:
            raise ReglaDeNegocio("Cada medio de pago tiene que cubrir un monto mayor a cero")

        medio = servicio_medios.obtener_medio(db, datos["medio_de_pago_id"])
        if not medio.activo:
            raise ReglaDeNegocio(f"El medio de pago '{medio.nombre}' está inactivo")

        plan = _resolver_plan(
            db, medio, datos.get("plan_cuotas_id"), monto, habilita_sin_interes
        )
        sena = _resolver_sena(db, venta, medio, datos.get("sena_id"), monto)

        recargo = servicio_medios.calcular_recargo(monto, plan)
        nuevos.append(
            VentaPago(
                venta_id=venta.id,
                medio_de_pago_id=medio.id,
                plan_cuotas_id=plan.id if plan else None,
                monto=monto,
                recargo=recargo,
                monto_total=monto + recargo,
                sena_id=sena.id if sena else None,
            )
        )

    # Se reemplaza la lista entera: los pagos son una decisión, no un
    # historial, y el `delete-orphan` de la relación limpia los anteriores.
    venta.pagos.clear()
    db.flush()
    venta.pagos.extend(nuevos)
    db.flush()

    venta.recargo_total = redondear(sum((p.recargo for p in nuevos), Decimal("0")))
    venta.total = cobrable + venta.recargo_total
    venta.updated_at = ahora_db()
    db.flush()
    return venta


def _habilita_cuotas_sin_interes(venta: Venta) -> bool:
    """
    Si algún motivo de descuento de la venta habilita los planes sin interés
    por debajo de su monto mínimo.

    Alcanza con uno: el beneficio es del cliente ("Empleada", "Cumpleaños"),
    no del producto, así que no tendría sentido exigir que TODOS los ítems lo
    tengan para reconocérselo.
    """
    return any(
        i.motivo_descuento is not None and i.motivo_descuento.habilita_cuotas_sin_interes
        for i in venta.items
    )


def _resolver_plan(
    db: Session,
    medio: MedioDePago,
    plan_id: int | None,
    monto: Decimal,
    habilita_sin_interes: bool,
) -> PlanCuotas | None:
    """
    Valida el plan elegido contra los que ese monto realmente habilita.

    Se revalida acá aunque la pantalla ya haya filtrado: la pantalla es un
    cliente más de la API, y un plan que no corresponde cobrado igual es
    plata de más al cliente.
    """
    if plan_id is None:
        return None

    if not medio.soporta_cuotas:
        raise ReglaDeNegocio(f"'{medio.nombre}' no se cobra en cuotas")

    disponibles = servicio_medios.planes_disponibles(
        db, medio.id, monto, habilita_sin_interes
    )
    plan = next((p for p in disponibles if p.id == plan_id), None)
    if plan is None:
        raise ReglaDeNegocio(
            f"Ese plan de cuotas no está disponible para un pago de ${monto} "
            f"con '{medio.nombre}'"
        )
    return plan


def _resolver_sena(
    db: Session, venta: Venta, medio: MedioDePago, sena_id: int | None, monto: Decimal
) -> Sena | None:
    """
    Valida la seña que se quiere usar: que exista, que sea del cliente de la
    venta y que tenga saldo suficiente para la parte que se le asignó.

    Que la seña sea del MISMO cliente es lo que impide pagar con la seña de
    otro. Y por eso una seña obliga a que la venta tenga cliente asociado.
    """
    if not medio.es_sena:
        if sena_id is not None:
            raise ReglaDeNegocio(
                f"'{medio.nombre}' no es el medio de pago de las señas"
            )
        return None

    if sena_id is None:
        raise ReglaDeNegocio("Hay que indicar de qué seña se descuenta")
    if venta.cliente_id is None:
        raise ReglaDeNegocio(
            "Para pagar con una seña hay que asociar el cliente a la venta"
        )

    sena = servicio_senas.obtener_sena(db, sena_id)
    if sena.cliente_id != venta.cliente_id:
        raise ReglaDeNegocio("Esa seña es de otro cliente")
    if not sena.activo or Decimal(sena.saldo) <= 0:
        raise ReglaDeNegocio("Esa seña ya no tiene saldo disponible")
    if Decimal(sena.saldo) < monto:
        raise ReglaDeNegocio(
            f"La seña tiene ${sena.saldo} de saldo y se le asignaron ${monto}: "
            "el resto hay que cubrirlo con otro medio de pago"
        )
    return sena


# ============================================================================
# CONFIRMACIÓN Y ANULACIÓN
# ============================================================================


def confirmar_venta(
    db: Session,
    autor: Usuario,
    venta: Venta,
    scope: DeviceScope,
    ip_origen: str | None = None,
) -> Venta:
    """
    Cierra la venta: descuenta stock, suma puntos, consume señas y genera el
    código de cambio. TODO en la misma transacción.

    La atomicidad no es un detalle técnico: una venta que descontó stock pero
    no sumó los puntos, o que consumió una seña y después falló, deja al
    negocio con datos que nadie puede arreglar sin reconstruir a mano qué
    pasó. No hay commit acá — lo hace el endpoint, sobre todo el bloque.

    Se valida ANTES de tocar nada. Con el stock ya restado, un error dejaría
    la transacción a medias esperando el rollback y el mensaje sería peor.
    """
    _exigir_en_curso(venta)
    scope.exigir(venta.punto_de_venta_id)

    # Bloqueo duro: turno del día anterior sin cerrar bloquea la confirmación
    verificar_bloqueo_turno(venta.punto_de_venta_id, db)

    if not venta.items:
        raise ReglaDeNegocio("No se puede confirmar una venta sin productos")
    if not venta.pagos:
        raise ReglaDeNegocio("Hay que registrar los medios de pago antes de confirmar")

    cobrable = redondear(sum((Decimal(i.precio_final) for i in venta.items), Decimal("0")))
    if _suma_pagos(venta) != cobrable:
        raise ReglaDeNegocio(
            "Los medios de pago no cubren el total de la venta: volvé a registrarlos"
        )

    antes = snapshot(venta)

    # ---- Stock -----------------------------------------------------------
    # Agrupado por variante: tres anillos iguales son UN movimiento de 3 y no
    # tres de 1. El movimiento describe lo que salió del local, y partirlo en
    # filas de a una solo llenaría el historial.
    for variante_id, cantidad in _unidades_por_variante(venta).items():
        servicio_stock.aplicar_movimiento(
            db,
            autor,
            tipo=TipoMovimiento.VENTA,
            variante_id=variante_id,
            cantidad=cantidad,
            punto_venta_origen_id=venta.punto_de_venta_id,
            referencia_venta_id=venta.id,
            permitir_faltante=True,
            notas=f"Venta {venta.numero}",
            ip_origen=ip_origen,
        )

    # ---- Señas -----------------------------------------------------------
    for pago in venta.pagos:
        if pago.sena_id is not None:
            servicio_senas.consumir(
                db,
                autor,
                servicio_senas.obtener_sena(db, pago.sena_id),
                Decimal(pago.monto),
                venta_id=venta.id,
                ip_origen=ip_origen,
            )

    # ---- Puntos ----------------------------------------------------------
    puntos = 0
    if venta.cliente_id is not None:
        puntos = servicio_clientes.puntos_por_venta(venta.total)
        if puntos > 0:
            servicio_clientes.registrar_movimiento_puntos(
                db,
                autor,
                cliente_id=venta.cliente_id,
                tipo=TipoPunto.ACUMULACION,
                cantidad=puntos,
                venta_id=venta.id,
                ip_origen=ip_origen,
            )
    venta.puntos_acumulados = puntos

    # ---- Cierre ----------------------------------------------------------
    venta.codigo_cambio = generar_codigo_cambio(db)
    venta.estado = EstadoVenta.CONFIRMADA
    venta.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="venta.confirmada",
        entidad="ventas",
        entidad_id=venta.id,
        estado_anterior=antes,
        estado_nuevo=venta,
        ip_origen=ip_origen,
    )
    return venta


def _unidades_por_variante(venta: Venta) -> dict[int, int]:
    """Cuántas unidades de cada variante se llevan, para mover el stock."""
    conteo: dict[int, int] = {}
    for item in venta.items:
        conteo[item.variante_id] = conteo.get(item.variante_id, 0) + 1
    return conteo


def anular_venta(
    db: Session,
    autor: Usuario,
    venta: Venta,
    motivo: str | None = None,
    ip_origen: str | None = None,
) -> Venta:
    """
    Revierte una venta confirmada: devuelve el stock, saca los puntos y
    repone el saldo de las señas usadas.

    La fila NO se borra ni se le cambian los importes. La venta ocurrió, y
    el día que alguien pregunte por qué la caja de ese día cerró como cerró,
    la respuesta tiene que estar. Lo que cambia es el estado y lo que se
    revierte son sus efectos.

    Todo en la misma transacción, por el mismo motivo que la confirmación:
    revertir el stock sin revertir los puntos deja al cliente con puntos de
    una compra que no existió.
    """
    if venta.estado == EstadoVenta.ANULADA:
        raise ReglaDeNegocio(f"La venta {venta.numero} ya está anulada")
    if venta.estado != EstadoVenta.CONFIRMADA:
        raise ReglaDeNegocio(
            f"La venta {venta.numero} está {venta.estado.value}: solo se anulan las "
            "confirmadas"
        )

    antes = snapshot(venta)

    # ---- Stock de vuelta al local ---------------------------------------
    for variante_id, cantidad in _unidades_por_variante(venta).items():
        servicio_stock.aplicar_movimiento(
            db,
            autor,
            tipo=TipoMovimiento.DEVOLUCION_VENTA,
            variante_id=variante_id,
            cantidad=cantidad,
            punto_venta_destino_id=venta.punto_de_venta_id,
            referencia_venta_id=venta.id,
            notas=f"Anulación de la venta {venta.numero}",
            ip_origen=ip_origen,
        )

    # ---- Señas -----------------------------------------------------------
    for pago in venta.pagos:
        if pago.sena_id is not None:
            servicio_senas.devolver(
                db,
                autor,
                servicio_senas.obtener_sena(db, pago.sena_id),
                Decimal(pago.monto),
                ip_origen=ip_origen,
            )

    # ---- Puntos ----------------------------------------------------------
    # Con un ajuste de signo contrario y no borrando la acumulación:
    # `puntos_cliente` es de solo inserción y la base lo hace cumplir con un
    # trigger. El historial tiene que mostrar que se sumaron y que se
    # sacaron, no que nunca se sumaron.
    if venta.cliente_id is not None and venta.puntos_acumulados > 0:
        servicio_clientes.registrar_movimiento_puntos(
            db,
            autor,
            cliente_id=venta.cliente_id,
            tipo=TipoPunto.AJUSTE,
            cantidad=-venta.puntos_acumulados,
            venta_id=venta.id,
            descripcion=f"Anulación de la venta {venta.numero}"
            + (f": {motivo}" if motivo else ""),
            ip_origen=ip_origen,
        )

    venta.estado = EstadoVenta.ANULADA
    venta.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="venta.anular",
        entidad="ventas",
        entidad_id=venta.id,
        estado_anterior=antes,
        estado_nuevo={**(snapshot(venta) or {}), "motivo": motivo},
        ip_origen=ip_origen,
    )
    return venta


def descartar_venta(
    db: Session, autor: Usuario, venta: Venta, ip_origen: str | None = None
) -> None:
    """
    Tira una venta que quedó `en_curso`.

    Se borra de verdad, a diferencia de la anulación: nunca tocó el stock ni
    los puntos, así que no hay nada que revertir ni nada que explicar
    después. Lo que sí queda es el registro de auditoría de que se descartó
    —y el número de venta, que se consumió y no se recicla—.
    """
    _exigir_en_curso(venta)

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="venta.descartar",
        entidad="ventas",
        entidad_id=venta.id,
        estado_anterior=venta,
        ip_origen=ip_origen,
    )
    db.delete(venta)
    db.flush()
