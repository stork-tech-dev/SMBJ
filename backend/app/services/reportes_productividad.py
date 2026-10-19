"""
Reportes de Productividad: cuánto hizo cada usuario en un período.

Dos reportes, los dos por rango de fechas (inclusive) y con una fila por
usuario que tuvo actividad, ordenadas por nombre, más los totales:

1. Centro de Distribución — variantes vendibles que dio de alta y remitos
   que mandó desde el CD (cantidad y unidades).
2. Vendedores — ventas confirmadas (cantidad, unidades, importe), señas
   (cantidad, importe) y cambios confirmados, opcionalmente de un local.

Solo lectura: cuentan lo que ya está en la base, no persisten nada
(Principio 4).
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria
from app.models.cambio import Cambio, EstadoCambio
from app.models.producto import Variante
from app.models.punto_de_venta import PuntoDeVenta, TipoPuntoVenta
from app.models.remito import Remito, RemitoItem
from app.models.sena import Sena
from app.models.usuario import Usuario
from app.models.venta import EstadoVenta, Venta, VentaItem

CERO = Decimal("0")


def _en_rango(columna, desde: date, hasta: date):
    """El día de `columna` entre desde y hasta, los dos inclusive."""
    return func.date(columna).between(desde, hasta)


def _por_usuario(consulta) -> dict[int, tuple]:
    """Filas `(usuario_id, *valores)` → `{usuario_id: valores}`."""
    return {fila[0]: tuple(fila[1:]) for fila in consulta if fila[0] is not None}


def _filas(db: Session, por_usuario: dict[int, dict], vacia: dict) -> list[dict]:
    """Una fila por usuario con actividad, con su nombre, ordenadas por nombre."""
    if not por_usuario:
        return []
    nombres = dict(
        db.execute(select(Usuario.id, Usuario.nombre).where(Usuario.id.in_(por_usuario)))
        .all()
    )
    filas = [
        {"usuario_id": uid, "usuario_nombre": nombres.get(uid, "—"), **vacia, **valores}
        for uid, valores in por_usuario.items()
    ]
    return sorted(filas, key=lambda f: f["usuario_nombre"].lower())


def _totales(filas: list[dict], vacia: dict) -> dict:
    return {campo: sum((f[campo] for f in filas), cero) for campo, cero in vacia.items()}


# ---------------------------------------------------------------------------
# 1. Centro de Distribución
# ---------------------------------------------------------------------------


def _variantes_dadas_de_alta(db: Session, desde: date, hasta: date) -> dict[int, int]:
    """
    Variantes vendibles dadas de alta por cada usuario: las que EXISTEN hoy,
    atribuidas por la auditoría de su alta.

    Se cuentan variantes y no altas porque al agregar la primera variante
    real la BASE se borra (`agregar_variante`): un producto con 3 talles
    tiene 3 variantes y cuenta 3, aunque en la auditoría haya 4 altas (el
    producto y sus tres variantes). Un producto sin talles conserva su BASE
    y cuenta 1.
    """
    # Variantes reales: la auditoría apunta a la variante.
    reales = (
        select(Auditoria.usuario_id, Variante.id.label("variante_id"))
        .join(Variante, Variante.id == Auditoria.entidad_id)
        .where(Auditoria.accion == "variante.crear", _en_rango(Auditoria.timestamp, desde, hasta))
    )
    # BASE: la auditoría apunta al producto; cuenta solo si la BASE sigue.
    bases = (
        select(Auditoria.usuario_id, Variante.id.label("variante_id"))
        .join(
            Variante,
            and_(Variante.producto_id == Auditoria.entidad_id, Variante.es_base.is_(True)),
        )
        .where(Auditoria.accion == "producto.crear", _en_rango(Auditoria.timestamp, desde, hasta))
    )
    altas = reales.union(bases).subquery()
    consulta = select(altas.c.usuario_id, func.count(altas.c.variante_id)).group_by(
        altas.c.usuario_id
    )
    return {uid: cantidad for uid, cantidad in db.execute(consulta) if uid is not None}


def centro_distribucion(db: Session, desde: date, hasta: date) -> dict:
    """Por usuario: variantes dadas de alta y remitos enviados desde el CD."""
    vacia = {"productos": 0, "remitos": 0, "unidades_remitidas": 0}

    remitos = _por_usuario(
        db.execute(
            select(
                Remito.usuario_envio_id,
                func.count(func.distinct(Remito.id)),
                func.coalesce(func.sum(RemitoItem.cantidad_enviada), 0),
            )
            .join(RemitoItem, RemitoItem.remito_id == Remito.id)
            .join(PuntoDeVenta, PuntoDeVenta.id == Remito.punto_venta_origen_id)
            # Lo que sale del CD: un envío entre locales no es trabajo del CD.
            .where(PuntoDeVenta.tipo == TipoPuntoVenta.CD,
                   _en_rango(Remito.fecha_envio, desde, hasta))
            .group_by(Remito.usuario_envio_id)
        )
    )

    por_usuario: dict[int, dict] = {}
    for uid, cantidad in _variantes_dadas_de_alta(db, desde, hasta).items():
        por_usuario.setdefault(uid, {})["productos"] = cantidad
    for uid, (cantidad, unidades) in remitos.items():
        por_usuario.setdefault(uid, {}).update(remitos=cantidad, unidades_remitidas=int(unidades))

    filas = _filas(db, por_usuario, vacia)
    return {
        "fecha_desde": desde,
        "fecha_hasta": hasta,
        "filas": filas,
        "totales": _totales(filas, vacia),
    }


# ---------------------------------------------------------------------------
# 2. Vendedores
# ---------------------------------------------------------------------------


def vendedores(
    db: Session, desde: date, hasta: date, punto_de_venta_id: int | None = None
) -> dict:
    """
    Por usuario: ventas confirmadas (cantidad, unidades, importe), señas
    (cantidad, importe) y cambios confirmados. Ni anuladas ni en curso: una
    venta anulada se revirtió y una en curso todavía no es una venta.
    """
    vacia = {
        "ventas": 0, "unidades": 0, "importe": CERO,
        "senas": 0, "importe_senas": CERO, "cambios": 0,
    }

    def _del_local(columna):
        return columna == punto_de_venta_id if punto_de_venta_id is not None else True

    confirmadas = and_(
        Venta.estado == EstadoVenta.CONFIRMADA,
        _en_rango(Venta.created_at, desde, hasta),
        _del_local(Venta.punto_de_venta_id),
    )
    # Importe y unidades en consultas separadas: sumar `total` sobre el join
    # con los ítems lo multiplicaría por la cantidad de ítems de cada venta.
    ventas = _por_usuario(db.execute(
        select(Venta.usuario_id, func.count(Venta.id), func.coalesce(func.sum(Venta.total), 0))
        .where(confirmadas)
        .group_by(Venta.usuario_id)
    ))
    unidades = _por_usuario(db.execute(
        select(Venta.usuario_id, func.count(VentaItem.id))
        .join(VentaItem, VentaItem.venta_id == Venta.id)
        .where(confirmadas)
        .group_by(Venta.usuario_id)
    ))
    senas = _por_usuario(db.execute(
        select(Sena.usuario_id, func.count(Sena.id), func.coalesce(func.sum(Sena.monto), 0))
        .where(_en_rango(Sena.created_at, desde, hasta), _del_local(Sena.punto_de_venta_id))
        .group_by(Sena.usuario_id)
    ))
    cambios = _por_usuario(db.execute(
        select(Cambio.usuario_id, func.count(Cambio.id))
        .where(
            Cambio.estado == EstadoCambio.CONFIRMADO,
            _en_rango(Cambio.created_at, desde, hasta),
            _del_local(Cambio.punto_de_venta_id),
        )
        .group_by(Cambio.usuario_id)
    ))

    por_usuario: dict[int, dict] = {}
    for uid, (cantidad, importe) in ventas.items():
        por_usuario.setdefault(uid, {}).update(ventas=cantidad, importe=Decimal(importe))
    for uid, (cantidad,) in unidades.items():
        por_usuario.setdefault(uid, {})["unidades"] = cantidad
    for uid, (cantidad, importe) in senas.items():
        por_usuario.setdefault(uid, {}).update(senas=cantidad, importe_senas=Decimal(importe))
    for uid, (cantidad,) in cambios.items():
        por_usuario.setdefault(uid, {})["cambios"] = cantidad

    filas = _filas(db, por_usuario, vacia)
    return {
        "fecha_desde": desde,
        "fecha_hasta": hasta,
        "filas": filas,
        "totales": _totales(filas, vacia),
    }
