"""
Bajas de stock y el catálogo de motivos.

Una baja es mercadería que deja de estar: rotura, robo, muestra, merma. No
se corrige el número y listo — se registra un movimiento con su motivo, para
que después se pueda explicar la diferencia entre lo que se compró y lo que
se vendió.

El movimiento lo aplica `stock.aplicar_movimiento()`, como todo lo que toca
el stock. Acá vive lo propio de la baja: que el motivo exista, que esté
activo y que la ubicación sea la que corresponde.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.device_scope import DeviceScope
from app.core.utils import normalizar_texto, sin_tildes, sin_tildes_sql
from app.models.motivo_baja import MotivoBaja
from app.models.stock import MovimientoStock, TipoMovimiento
from app.models.usuario import Usuario
from app.services import stock as servicio_stock
from app.services.roles import NoEncontrado, ReglaDeNegocio


def listar_motivos(
    db: Session, activo: bool | None = None, nombre: str | None = None
) -> list[MotivoBaja]:
    """
    El catálogo, con los filtros por defecto del Principio 5. Tabla chica:
    sin paginación, se devuelve todo lo filtrado.
    """
    consulta = select(MotivoBaja)

    if activo is not None:
        consulta = consulta.where(MotivoBaja.activo.is_(activo))
    if nombre:
        # Las dos caras de la comparación se limpian igual —la columna con
        # `translate()` en SQL y el texto tipeado en Python— para que "merma"
        # encuentre "Mermá" y al revés, como pide el Principio 5.
        consulta = consulta.where(
            sin_tildes_sql(MotivoBaja.nombre).ilike(f"%{sin_tildes(nombre)}%")
        )

    return list(db.execute(consulta.order_by(MotivoBaja.nombre)).scalars().all())


def obtener_motivo(db: Session, motivo_id: int) -> MotivoBaja:
    motivo = db.get(MotivoBaja, motivo_id)
    if motivo is None:
        raise NoEncontrado("Motivo de baja inexistente")
    return motivo


def _validar_nombre_unico(db: Session, nombre: str, excluir_id: int | None = None) -> None:
    """
    Dos motivos con el mismo nombre serían la misma razón dos veces: al
    elegir en la lista no habría forma de saber cuál corresponde, y los
    reportes por motivo quedarían partidos en dos.

    La base también lo garantiza con un UNIQUE; esto existe para devolver un
    mensaje entendible en vez de un error de integridad.
    """
    consulta = select(MotivoBaja.id).where(func.lower(MotivoBaja.nombre) == nombre.lower())
    if excluir_id is not None:
        consulta = consulta.where(MotivoBaja.id != excluir_id)
    if db.execute(consulta).scalar_one_or_none():
        raise ReglaDeNegocio(f"Ya existe un motivo de baja '{nombre}'")


def crear_motivo(
    db: Session, autor: Usuario, nombre: str, ip_origen: str | None = None
) -> MotivoBaja:
    limpio = normalizar_texto(nombre)
    if not limpio:
        raise ReglaDeNegocio("El nombre del motivo es obligatorio")
    _validar_nombre_unico(db, limpio)

    motivo = MotivoBaja(nombre=limpio, activo=True)
    db.add(motivo)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="motivo_baja.crear",
        entidad="motivos_baja",
        entidad_id=motivo.id,
        estado_nuevo=motivo,
        ip_origen=ip_origen,
    )
    return motivo


def editar_motivo(
    db: Session,
    autor: Usuario,
    motivo_id: int,
    nombre: str | None = None,
    activo: bool | None = None,
    ip_origen: str | None = None,
) -> MotivoBaja:
    """
    Cambia el nombre o lo desactiva.

    Desactivar y no borrar: los movimientos ya registrados apuntan al motivo,
    y borrarlo dejaría sin explicación bajas que ya pasaron. Un motivo
    inactivo no se ofrece para nuevas bajas y sigue explicando las viejas.
    """
    motivo = obtener_motivo(db, motivo_id)
    antes = snapshot(motivo)

    if nombre is not None:
        limpio = normalizar_texto(nombre)
        if not limpio:
            raise ReglaDeNegocio("El nombre del motivo es obligatorio")
        _validar_nombre_unico(db, limpio, excluir_id=motivo.id)
        motivo.nombre = limpio

    if activo is not None:
        motivo.activo = activo

    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="motivo_baja.editar",
        entidad="motivos_baja",
        entidad_id=motivo.id,
        estado_anterior=antes,
        estado_nuevo=motivo,
        ip_origen=ip_origen,
    )
    return motivo


def registrar_baja(
    db: Session,
    autor: Usuario,
    scope: DeviceScope,
    *,
    variante_id: int,
    punto_de_venta_id: int,
    cantidad: int,
    motivo_baja_id: int,
    notas: str | None = None,
    ip_origen: str | None = None,
) -> MovimientoStock:
    """
    Da de baja unidades de una ubicación.

    El aislamiento por dispositivo se exige acá y no solo en el endpoint: es
    la última barrera antes de tocar el stock, y así cualquier camino nuevo
    que llame a esta función lo respeta sin tener que acordarse.
    """
    scope.exigir(punto_de_venta_id)

    motivo = obtener_motivo(db, motivo_baja_id)
    if not motivo.activo:
        raise ReglaDeNegocio(
            f"El motivo '{motivo.nombre}' está inactivo: no se puede usar en una baja nueva"
        )

    return servicio_stock.aplicar_movimiento(
        db,
        autor,
        tipo=TipoMovimiento.BAJA,
        variante_id=variante_id,
        cantidad=cantidad,
        punto_venta_origen_id=punto_de_venta_id,
        motivo_baja_id=motivo_baja_id,
        notas=notas,
        ip_origen=ip_origen,
    )
