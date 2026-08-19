"""
Remitos: mercadería que viaja de una ubicación a otra.

El flujo tiene cuatro estados y cada paso mueve stock o lo deja quieto:

  1. `pendiente`  — se armó el envío. El stock YA SALIÓ del origen: la
     mercadería se bajó de la estantería aunque el camión no haya arrancado.
     Es lo que evita que dos envíos comprometan las mismas unidades.
  2. `en_camino`  — se despachó. Se genera el PDF que viaja con la carga.
  3. `confirmado` — el local contó y coincide. El stock entra al destino.
     `con_diferencia` si no coincide: entra lo que efectivamente llegó y la
     diferencia queda registrada para revisar.

Entre 1 y 3 la mercadería no está en ninguna de las dos puntas, y eso es a
propósito: sumarla al destino antes de que llegue habilitaría a venderla
mientras está en un camión.

Para confirmar hay que tipear el NÚMERO del remito. No es un secreto
criptográfico: es el papel que viaja con la carga, así que tenerlo es la
prueba de que la mercadería llegó a destino.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.device_scope import DeviceScope
from app.core.utils import ahora_db, normalizar_texto
from app.models.producto import Variante
from app.models.punto_de_venta import TipoPuntoVenta
from app.models.remito import EstadoRemito, Remito, RemitoItem
from app.models.stock import TipoMovimiento
from app.models.usuario import Usuario
from app.services import stock as servicio_stock
from app.services.roles import NoEncontrado, ReglaDeNegocio


class CodigoIncorrecto(Exception):
    """
    El número tipeado no es el del remito que se quiere confirmar (403).

    Excepción propia y no `ReglaDeNegocio` porque el endpoint la traduce a un
    código distinto: no es que la operación sea inválida, es que quien la
    pide no demostró tener el remito en la mano.
    """


def obtener_remito(db: Session, remito_id: int) -> Remito:
    remito = db.execute(
        select(Remito)
        .where(Remito.id == remito_id)
        .options(
            joinedload(Remito.origen),
            joinedload(Remito.destino),
            joinedload(Remito.items).joinedload(RemitoItem.variante).joinedload(
                Variante.producto
            ),
        )
    ).unique().scalar_one_or_none()

    if remito is None:
        raise NoEncontrado("Remito inexistente")
    return remito


def _siguiente_numero(db: Session) -> str:
    """
    Correlativo del remito, con el formato R-000001.

    Sale de una SEQUENCE y no de MAX(numero)+1: dos envíos simultáneos sacan
    números distintos sin bloquearse, y no puede haber dos remitos con el
    mismo número ni con concurrencia. Mismo criterio que los SKU.
    """
    numero = db.execute(select(func.nextval("remitos_numero_seq"))).scalar_one()
    return f"R-{numero:06d}"


def _tipo_de_movimiento(origen, destino) -> TipoMovimiento:
    """
    Qué clase de transferencia es, según de dónde a dónde va.

    Del CD a cualquier lado es un envío; de un local al CD es una devolución.
    Entre dos locales se registra como envío: es mercadería que se reparte, y
    el tipo `devolucion_local_cd` mentiría sobre el destino.
    """
    if origen.tipo == TipoPuntoVenta.CD:
        return TipoMovimiento.ENVIO_CD_LOCAL
    if destino.tipo == TipoPuntoVenta.CD:
        return TipoMovimiento.DEVOLUCION_LOCAL_CD
    return TipoMovimiento.ENVIO_CD_LOCAL


def crear_remito(
    db: Session,
    autor: Usuario,
    scope: DeviceScope,
    *,
    punto_venta_origen_id: int,
    punto_venta_destino_id: int,
    items: list[dict],
    notas: str | None = None,
    ip_origen: str | None = None,
) -> Remito:
    """
    Arma el envío y descuenta el stock del origen en el acto.

    `items` es una lista de {variante_id, cantidad}.

    El descuento va acá y no al confirmar la recepción porque la mercadería
    sale del depósito ahora: si se descontara al final, el CD seguiría
    ofreciendo unidades que ya están en un camión y dos envíos podrían
    comprometer las mismas.
    """
    if not items:
        raise ReglaDeNegocio("Un remito sin ítems no mueve nada")

    origen = servicio_stock.obtener_punto(db, punto_venta_origen_id)
    destino = servicio_stock.obtener_punto(db, punto_venta_destino_id)

    if origen.id == destino.id:
        raise ReglaDeNegocio("El origen y el destino tienen que ser distintos")
    if not destino.activo:
        raise ReglaDeNegocio(f"{destino.nombre} está inactivo: no puede recibir mercadería")

    # Quien arma el envío tiene que estar habilitado en el ORIGEN: es de ahí
    # de donde sale la mercadería.
    scope.exigir(origen.id)

    # Una variante repetida serían dos líneas para el mismo código, y al
    # contar la recepción no habría forma de saber a cuál corresponde lo que
    # llegó. Lo ata un UNIQUE, pero el mensaje se da acá.
    vistas = [i["variante_id"] for i in items]
    if len(vistas) != len(set(vistas)):
        raise ReglaDeNegocio("Hay una variante repetida en el remito")

    remito = Remito(
        numero=_siguiente_numero(db),
        punto_venta_origen_id=origen.id,
        punto_venta_destino_id=destino.id,
        estado=EstadoRemito.PENDIENTE,
        usuario_envio_id=autor.id,
        fecha_envio=ahora_db(),
        notas=normalizar_texto(notas),
        created_at=ahora_db(),
        updated_at=ahora_db(),
    )
    db.add(remito)
    db.flush()

    tipo = _tipo_de_movimiento(origen, destino)

    for item in items:
        cantidad = int(item["cantidad"])
        if cantidad <= 0:
            raise ReglaDeNegocio("Las cantidades del remito tienen que ser mayores a cero")

        db.add(
            RemitoItem(
                remito_id=remito.id,
                variante_id=item["variante_id"],
                cantidad_enviada=cantidad,
            )
        )

        # Solo la punta del origen: el destino suma cuando confirme. Si acá
        # se aplicaran las dos, la mercadería estaría en el local antes de
        # llegar.
        servicio_stock.aplicar_movimiento(
            db,
            autor,
            tipo=tipo,
            variante_id=item["variante_id"],
            cantidad=cantidad,
            punto_venta_origen_id=origen.id,
            punto_venta_destino_id=destino.id,
            remito_id=remito.id,
            puntas=("origen",),
            notas=f"Salida por remito {remito.numero}",
            ip_origen=ip_origen,
        )

    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="remito.crear",
        entidad="remitos",
        entidad_id=remito.id,
        estado_nuevo=remito,
        ip_origen=ip_origen,
    )
    return remito


def despachar(
    db: Session,
    autor: Usuario,
    scope: DeviceScope,
    remito_id: int,
    ip_origen: str | None = None,
) -> Remito:
    """
    Confirma que la mercadería salió y genera el PDF que la acompaña.

    No mueve stock: ya se descontó al armar el envío. Lo que cambia es que
    desde acá el remito es un documento imprimible con su número.
    """
    remito = obtener_remito(db, remito_id)
    scope.exigir(remito.punto_venta_origen_id)

    if remito.estado != EstadoRemito.PENDIENTE:
        raise ReglaDeNegocio(
            f"El remito {remito.numero} ya está {remito.estado.value}: "
            "solo se despacha uno pendiente"
        )

    antes = snapshot(remito)
    remito.estado = EstadoRemito.EN_CAMINO
    remito.updated_at = ahora_db()

    # El PDF se genera acá y se guarda: el que viajó con la mercadería tiene
    # que poder reimprimirse igual meses después, aunque los precios o los
    # nombres hayan cambiado desde entonces.
    from app.reports.remito_pdf import generar_pdf_remito

    remito.pdf_url = generar_pdf_remito(db, remito)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="remito.despachar",
        entidad="remitos",
        entidad_id=remito.id,
        estado_anterior=antes,
        estado_nuevo=remito,
        ip_origen=ip_origen,
    )
    return remito


def confirmar_recepcion(
    db: Session,
    autor: Usuario,
    scope: DeviceScope,
    remito_id: int,
    *,
    numero_confirmacion: str,
    recibidos: dict[int, int],
    notas: str | None = None,
    ip_origen: str | None = None,
) -> Remito:
    """
    El local cuenta lo que llegó y el stock entra a destino.

    `recibidos` es {variante_id: cantidad}. Las variantes que no vengan se
    toman como recibidas completas: lo normal es que todo llegue, y obligar a
    tipear cada línea para el caso habitual invita a equivocarse.

    `numero_confirmacion` es el número del remito, el que está impreso en el
    papel que viaja con la carga. Tenerlo es la prueba de que la mercadería
    llegó a destino; si no coincide, 403.
    """
    remito = obtener_remito(db, remito_id)

    # Confirma el local que RECIBE, no el que mandó.
    scope.exigir(remito.punto_venta_destino_id)

    if remito.estado not in (EstadoRemito.PENDIENTE, EstadoRemito.EN_CAMINO):
        raise ReglaDeNegocio(
            f"El remito {remito.numero} ya está {remito.estado.value}: "
            "no se puede volver a confirmar"
        )

    if (numero_confirmacion or "").strip().upper() != remito.numero.upper():
        raise CodigoIncorrecto(
            "El número de remito no coincide con el que se está confirmando"
        )

    antes = snapshot(remito)
    tipo = _tipo_de_movimiento(remito.origen, remito.destino)
    hubo_diferencia = False

    for item in remito.items:
        cantidad = recibidos.get(item.variante_id, item.cantidad_enviada)
        if cantidad < 0:
            raise ReglaDeNegocio("Las cantidades recibidas no pueden ser negativas")
        if cantidad > item.cantidad_enviada:
            raise ReglaDeNegocio(
                f"Llegaron {cantidad} de un código del que se enviaron "
                f"{item.cantidad_enviada}: no puede recibirse más de lo que salió"
            )

        item.cantidad_recibida = cantidad
        if cantidad != item.cantidad_enviada:
            hubo_diferencia = True

        # Solo lo que efectivamente llegó entra al destino. Lo que falta NO
        # se devuelve al origen: ya salió de ahí, y darlo por presente en los
        # dos lados sería inventar mercadería. Queda como diferencia a
        # revisar, que es lo que un faltante es.
        if cantidad > 0:
            servicio_stock.aplicar_movimiento(
                db,
                autor,
                tipo=tipo,
                variante_id=item.variante_id,
                cantidad=cantidad,
                punto_venta_origen_id=remito.punto_venta_origen_id,
                punto_venta_destino_id=remito.punto_venta_destino_id,
                remito_id=remito.id,
                puntas=("destino",),
                notas=f"Recepción del remito {remito.numero}",
                ip_origen=ip_origen,
            )

    remito.estado = (
        EstadoRemito.CON_DIFERENCIA if hubo_diferencia else EstadoRemito.CONFIRMADO
    )
    remito.usuario_recepcion_id = autor.id
    remito.fecha_recepcion = ahora_db()
    if notas:
        # Se suma a lo que ya había: la nota del que recibe explica la
        # diferencia, y pisar la del que envió perdería el contexto.
        remito.notas = "\n".join(filter(None, [remito.notas, normalizar_texto(notas)]))
    remito.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="remito.confirmar",
        entidad="remitos",
        entidad_id=remito.id,
        estado_anterior=antes,
        estado_nuevo=remito,
        ip_origen=ip_origen,
    )
    return remito


def listar_remitos(
    db: Session,
    scope: DeviceScope,
    estado: str | None = None,
    punto_venta_origen_id: int | None = None,
    punto_venta_destino_id: int | None = None,
    desde=None,
    hasta=None,
    pagina: int = 1,
    tamano: int = 50,
) -> tuple[list[Remito], int]:
    """
    Filtros del Principio 5. Un vendedor ve los remitos de su local por
    cualquiera de las dos puntas: los que le mandaron y los que él mandó.
    """
    consulta = select(Remito).options(
        joinedload(Remito.origen),
        joinedload(Remito.destino),
    )

    if scope.restringido:
        if scope.sin_asignacion:
            return [], 0
        propio = scope.punto_de_venta_id
        consulta = consulta.where(
            (Remito.punto_venta_origen_id == propio)
            | (Remito.punto_venta_destino_id == propio)
        )

    if estado:
        consulta = consulta.where(Remito.estado == EstadoRemito(estado))
    if punto_venta_origen_id is not None:
        consulta = consulta.where(Remito.punto_venta_origen_id == punto_venta_origen_id)
    if punto_venta_destino_id is not None:
        consulta = consulta.where(Remito.punto_venta_destino_id == punto_venta_destino_id)
    if desde is not None:
        consulta = consulta.where(Remito.fecha_envio >= desde)
    if hasta is not None:
        consulta = consulta.where(Remito.fecha_envio <= hasta)

    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()

    filas = (
        db.execute(
            # El más reciente primero: lo que está por llegar es lo que se
            # mira. El id desempata los del mismo instante.
            consulta.order_by(Remito.fecha_envio.desc(), Remito.id.desc())
            .limit(tamano)
            .offset((pagina - 1) * tamano)
        )
        .unique()
        .scalars()
        .all()
    )
    return list(filas), total
