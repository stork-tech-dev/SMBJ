"""
Reglas de negocio de puntos de venta.

Las restricciones (un solo CD, código de confirmación solo en locales, no
desactivar con dispositivos/stock sin confirmar) se aplican acá: valen para
cualquier consumidor de la API.
"""

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.utils import ahora_db, normalizar_texto
from app.models.dispositivo import Dispositivo
from app.models.punto_de_venta import PuntoDeVenta, TipoPuntoVenta
from app.models.usuario import Usuario
from app.services.roles import NoEncontrado, ReglaDeNegocio


def obtener_punto(db: Session, punto_id: int) -> PuntoDeVenta:
    punto = db.get(PuntoDeVenta, punto_id)
    if punto is None:
        raise NoEncontrado("Punto de venta inexistente")
    return punto


def listar_puntos(
    db: Session,
    nombre: str | None = None,
    tipo: str | None = None,
    activo: bool | None = None,
) -> list[PuntoDeVenta]:
    """Listado con los filtros del Principio 5, resueltos en el backend."""
    consulta = select(PuntoDeVenta)
    if nombre:
        consulta = consulta.where(PuntoDeVenta.nombre.ilike(f"%{nombre}%"))
    if tipo:
        consulta = consulta.where(PuntoDeVenta.tipo == tipo)
    if activo is not None:
        consulta = consulta.where(PuntoDeVenta.activo.is_(activo))
    # CD primero, después el resto por nombre.
    return list(
        db.execute(consulta.order_by(PuntoDeVenta.tipo, PuntoDeVenta.nombre)).scalars().all()
    )


def locales_activos(db: Session) -> list[PuntoDeVenta]:
    """Locales activos: alimentan el selector de asignación de dispositivos."""
    return list(
        db.execute(
            select(PuntoDeVenta)
            .where(PuntoDeVenta.tipo == TipoPuntoVenta.LOCAL, PuntoDeVenta.activo.is_(True))
            .order_by(PuntoDeVenta.nombre)
        )
        .scalars()
        .all()
    )


def _validar_codigo(tipo: TipoPuntoVenta, codigo: str | None) -> str | None:
    """El código de confirmación solo aplica a locales y son 4 caracteres."""
    codigo = normalizar_texto(codigo)
    if codigo is None:
        return None
    if tipo != TipoPuntoVenta.LOCAL:
        raise ReglaDeNegocio("El código de confirmación solo aplica a locales")
    if len(codigo) != 4:
        raise ReglaDeNegocio("El código de confirmación debe tener 4 caracteres")
    return codigo


def _existe_cd(db: Session, excluir_id: int | None = None) -> bool:
    consulta = select(func.count(PuntoDeVenta.id)).where(
        PuntoDeVenta.tipo == TipoPuntoVenta.CD
    )
    if excluir_id is not None:
        consulta = consulta.where(PuntoDeVenta.id != excluir_id)
    return db.execute(consulta).scalar_one() > 0


def crear_punto(
    db: Session,
    autor: Usuario,
    nombre: str,
    tipo: TipoPuntoVenta,
    codigo_confirmacion: str | None = None,
    ip_origen: str | None = None,
) -> PuntoDeVenta:
    """Alta de punto de venta. Solo puede existir un CD por instancia."""
    nombre_limpio = normalizar_texto(nombre)
    if not nombre_limpio:
        raise ReglaDeNegocio("El nombre es obligatorio")

    if tipo == TipoPuntoVenta.CD and _existe_cd(db):
        raise ReglaDeNegocio("Ya existe un Centro de Distribución")

    codigo = _validar_codigo(tipo, codigo_confirmacion)

    punto = PuntoDeVenta(
        nombre=nombre_limpio,
        tipo=tipo,
        codigo_confirmacion=codigo,
        activo=True,
        created_at=ahora_db(),
        updated_at=ahora_db(),
    )
    db.add(punto)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="punto_venta.crear",
        entidad="puntos_de_venta",
        entidad_id=punto.id,
        estado_nuevo=punto,
        ip_origen=ip_origen,
    )
    return punto


def editar_punto(
    db: Session,
    autor: Usuario,
    punto_id: int,
    nombre: str | None = None,
    tipo: TipoPuntoVenta | None = None,
    codigo_confirmacion: str | None = None,
    ip_origen: str | None = None,
) -> PuntoDeVenta:
    """Edita un punto de venta. Cambiar a CD respeta la unicidad."""
    punto = obtener_punto(db, punto_id)
    antes = snapshot(punto)

    if nombre is not None:
        nombre_limpio = normalizar_texto(nombre)
        if not nombre_limpio:
            raise ReglaDeNegocio("El nombre es obligatorio")
        punto.nombre = nombre_limpio

    if tipo is not None and tipo != punto.tipo:
        if tipo == TipoPuntoVenta.CD and _existe_cd(db, excluir_id=punto.id):
            raise ReglaDeNegocio("Ya existe un Centro de Distribución")
        punto.tipo = tipo
        # Al dejar de ser local, el código de confirmación pierde sentido.
        if tipo != TipoPuntoVenta.LOCAL:
            punto.codigo_confirmacion = None

    if codigo_confirmacion is not None:
        punto.codigo_confirmacion = _validar_codigo(punto.tipo, codigo_confirmacion)

    punto.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="punto_venta.editar",
        entidad="puntos_de_venta",
        entidad_id=punto.id,
        estado_anterior=antes,
        estado_nuevo=punto,
        ip_origen=ip_origen,
    )
    return punto


def _tiene_stock(db: Session, punto_id: int) -> bool:
    """
    Si hay stock asociado al punto. La tabla de stock llega en el módulo 05;
    hasta entonces no existe y se asume que no hay.
    """
    existe = db.execute(text("SELECT to_regclass('public.stock')")).scalar()
    if existe is None:
        return False
    return (
        db.execute(
            text("SELECT count(*) FROM stock WHERE punto_de_venta_id = :pid AND cantidad > 0"),
            {"pid": punto_id},
        ).scalar_one()
        > 0
    )


def cambiar_estado(
    db: Session,
    autor: Usuario,
    punto_id: int,
    activo: bool,
    confirmar: bool = False,
    ip_origen: str | None = None,
) -> PuntoDeVenta:
    """
    Activa o desactiva un punto de venta. No se puede desactivar uno con
    dispositivos activos o stock asociado sin confirmación explícita.
    """
    punto = obtener_punto(db, punto_id)
    antes = snapshot(punto)

    if not activo and not confirmar:
        dispositivos_activos = db.execute(
            select(func.count(Dispositivo.id)).where(
                Dispositivo.punto_de_venta_id == punto.id, Dispositivo.activo.is_(True)
            )
        ).scalar_one()
        if dispositivos_activos or _tiene_stock(db, punto.id):
            detalle = []
            if dispositivos_activos:
                detalle.append(f"{dispositivos_activos} dispositivo(s) activo(s)")
            if _tiene_stock(db, punto.id):
                detalle.append("stock asociado")
            raise ReglaDeNegocio(
                "El punto de venta tiene " + " y ".join(detalle) + ". Confirmar la baja."
            )

    punto.activo = activo
    punto.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="punto_venta.activar" if activo else "punto_venta.desactivar",
        entidad="puntos_de_venta",
        entidad_id=punto.id,
        estado_anterior=antes,
        estado_nuevo=punto,
        ip_origen=ip_origen,
    )
    return punto
