"""
Reglas de negocio de roles.

Las restricciones de los roles del sistema se aplican acá y no en el
router: valen para cualquier consumidor de la API.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.utils import ahora_db, normalizar_texto
from app.models.rol import Rol
from app.models.usuario import Usuario
from app.services.permisos import crear_permisos_vacios


class ReglaDeNegocio(Exception):
    """Violación de una regla de negocio. El router la traduce a 409/403."""


class NoEncontrado(Exception):
    """La entidad pedida no existe. El router la traduce a 404."""


def obtener_rol(db: Session, rol_id: int) -> Rol:
    rol = db.get(Rol, rol_id)
    if rol is None:
        raise NoEncontrado("Rol inexistente")
    return rol


def obtener_rol_por_nombre(db: Session, nombre: str) -> Rol | None:
    return db.execute(select(Rol).where(Rol.nombre == nombre)).scalar_one_or_none()


def listar_roles(
    db: Session,
    nombre: str | None = None,
    activo: bool | None = None,
    es_sistema: bool | None = None,
) -> list[dict]:
    """
    Listado con los filtros por defecto del Principio 5, más la cantidad
    de usuarios por rol (calculada, no persistida — Principio 4).
    """
    cantidad_usuarios = (
        select(Usuario.rol_id, func.count(Usuario.id).label("cantidad"))
        .group_by(Usuario.rol_id)
        .subquery()
    )

    consulta = select(Rol, func.coalesce(cantidad_usuarios.c.cantidad, 0)).outerjoin(
        cantidad_usuarios, Rol.id == cantidad_usuarios.c.rol_id
    )

    # ILIKE: búsqueda de texto insensible a mayúsculas.
    if nombre:
        consulta = consulta.where(Rol.nombre.ilike(f"%{nombre}%"))
    if activo is not None:
        consulta = consulta.where(Rol.activo.is_(activo))
    if es_sistema is not None:
        consulta = consulta.where(Rol.es_sistema.is_(es_sistema))

    consulta = consulta.order_by(Rol.es_sistema.desc(), Rol.nombre)

    return [
        {"rol": rol, "cantidad_usuarios": cantidad}
        for rol, cantidad in db.execute(consulta).all()
    ]


def crear_rol(
    db: Session, nombre: str, descripcion: str | None, autor_id: int, ip_origen: str | None = None
) -> Rol:
    """
    Crea un rol y sus permisos en FALSE para todos los módulos.
    El nombre se normaliza a minúsculas con guiones bajos.
    """
    nombre_limpio = (normalizar_texto(nombre) or "").lower().replace(" ", "_")
    if not nombre_limpio:
        raise ReglaDeNegocio("El nombre del rol es obligatorio")

    if obtener_rol_por_nombre(db, nombre_limpio) is not None:
        raise ReglaDeNegocio(f"Ya existe un rol con el nombre '{nombre_limpio}'")

    rol = Rol(
        nombre=nombre_limpio,
        descripcion=normalizar_texto(descripcion),
        es_sistema=False,  # Solo el seed crea roles de sistema.
        activo=True,
        created_at=ahora_db(),
        updated_at=ahora_db(),
    )
    db.add(rol)
    db.flush()

    crear_permisos_vacios(db, rol)

    registrar_auditoria(
        db,
        usuario_id=autor_id,
        accion="rol.crear",
        entidad="roles",
        entidad_id=rol.id,
        estado_nuevo=rol,
        ip_origen=ip_origen,
    )
    return rol


def editar_rol(
    db: Session,
    rol_id: int,
    nombre: str | None,
    descripcion: str | None,
    autor_id: int,
    ip_origen: str | None = None,
) -> Rol:
    """
    Edita un rol. En los roles de sistema solo se puede tocar la
    descripción: el nombre es la clave con la que el código los identifica.
    """
    rol = obtener_rol(db, rol_id)
    antes = snapshot(rol)

    if nombre is not None:
        nombre_limpio = (normalizar_texto(nombre) or "").lower().replace(" ", "_")
        if nombre_limpio != rol.nombre:
            if rol.es_sistema:
                raise ReglaDeNegocio("No se puede renombrar un rol del sistema")
            if not nombre_limpio:
                raise ReglaDeNegocio("El nombre del rol es obligatorio")
            existente = obtener_rol_por_nombre(db, nombre_limpio)
            if existente is not None and existente.id != rol.id:
                raise ReglaDeNegocio(f"Ya existe un rol con el nombre '{nombre_limpio}'")
            rol.nombre = nombre_limpio

    if descripcion is not None:
        rol.descripcion = normalizar_texto(descripcion)

    rol.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor_id,
        accion="rol.editar",
        entidad="roles",
        entidad_id=rol.id,
        estado_anterior=antes,
        estado_nuevo=rol,
        ip_origen=ip_origen,
    )
    return rol


def cambiar_estado_rol(
    db: Session, rol_id: int, activo: bool, autor_id: int, ip_origen: str | None = None
) -> Rol:
    """
    Activa o desactiva un rol. No se puede desactivar uno que tenga
    usuarios activos: quedarían sin poder operar.
    """
    rol = obtener_rol(db, rol_id)
    antes = snapshot(rol)

    if not activo:
        usuarios_activos = db.execute(
            select(func.count(Usuario.id)).where(
                Usuario.rol_id == rol.id, Usuario.activo.is_(True)
            )
        ).scalar_one()
        if usuarios_activos:
            raise ReglaDeNegocio(
                f"El rol tiene {usuarios_activos} usuario(s) activo(s): "
                "desactivarlos o reasignarlos antes de desactivar el rol"
            )

    rol.activo = activo
    rol.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor_id,
        accion="rol.activar" if activo else "rol.desactivar",
        entidad="roles",
        entidad_id=rol.id,
        estado_anterior=antes,
        estado_nuevo=rol,
        ip_origen=ip_origen,
    )
    return rol


def eliminar_rol(db: Session, rol_id: int, autor_id: int, ip_origen: str | None = None) -> None:
    """Elimina un rol no-sistema y sin usuarios asociados."""
    rol = obtener_rol(db, rol_id)

    if rol.es_sistema:
        raise ReglaDeNegocio("No se puede eliminar un rol del sistema")

    usuarios = db.execute(
        select(func.count(Usuario.id)).where(Usuario.rol_id == rol.id)
    ).scalar_one()
    if usuarios:
        raise ReglaDeNegocio(f"El rol tiene {usuarios} usuario(s) asociado(s)")

    antes = snapshot(rol)
    registrar_auditoria(
        db,
        usuario_id=autor_id,
        accion="rol.eliminar",
        entidad="roles",
        entidad_id=rol.id,
        estado_anterior=antes,
        ip_origen=ip_origen,
    )
    db.delete(rol)
    db.flush()
