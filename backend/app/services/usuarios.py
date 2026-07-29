"""
Reglas de negocio de usuarios.

Quién puede gestionar a quién se decide acá. `resolver_permiso()` dice si
alguien puede entrar al módulo; estas reglas dicen sobre qué usuarios
concretos puede operar.
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.permisos import ROL_CUENTA_MAESTRA, ROL_SUPERVISOR, ROL_VENDEDOR
from app.core.utils import ahora_db, normalizar_texto
from app.models.punto_de_venta import PuntoDeVenta, TipoPuntoVenta
from app.models.rol import Rol
from app.models.usuario import HistorialAcceso, Usuario
from app.services.auth import hash_password, revocar_sesiones_de_usuario
from app.services.roles import NoEncontrado, ReglaDeNegocio, obtener_rol

# Campos que jamás salen en una respuesta. La exclusión real la garantizan
# los schemas Pydantic; esta constante la usa la auditoría.
CAMPOS_NUNCA_EXPUESTOS = ("password_hash", "clave_especial_hash")


class SinPermiso(Exception):
    """El autor no puede operar sobre este usuario. El router devuelve 403."""


def obtener_usuario(db: Session, usuario_id: int) -> Usuario:
    usuario = db.get(Usuario, usuario_id)
    if usuario is None:
        raise NoEncontrado("Usuario inexistente")
    return usuario


# ============================================================================
# REGLAS DE QUIÉN GESTIONA A QUIÉN
# ============================================================================


def validar_puede_gestionar(autor: Usuario, objetivo_rol: Rol) -> None:
    """
    El Supervisor solo gestiona usuarios con rol 'vendedor'. La Cuenta
    Maestra gestiona a todos. El resto queda sujeto a `resolver_permiso`.

    Los roles se identifican por nombre, nunca por id.
    """
    if autor.rol is None:
        raise SinPermiso("El usuario no tiene rol asignado")

    if autor.rol.nombre == ROL_CUENTA_MAESTRA:
        return

    if autor.rol.nombre == ROL_SUPERVISOR and objetivo_rol.nombre != ROL_VENDEDOR:
        raise SinPermiso("Un supervisor solo puede gestionar usuarios con rol vendedor")


def _validar_local_asignado(db: Session, local_id: int | None) -> int | None:
    """
    El local asignado debe ser un punto de venta de tipo 'local' y activo.

    La regla vive acá y no en el schema porque necesita la base: vale
    igual desde la API, desde un script o desde cualquier otro cliente.
    """
    if local_id is None:
        return None

    local = db.get(PuntoDeVenta, local_id)
    if local is None:
        raise ReglaDeNegocio("El local asignado no existe")
    if local.tipo != TipoPuntoVenta.LOCAL:
        raise ReglaDeNegocio("Solo se puede asignar un punto de venta de tipo local")
    if not local.activo:
        raise ReglaDeNegocio("No se puede asignar un local inactivo")
    return local.id


def locales_asignables(db: Session) -> list[PuntoDeVenta]:
    """
    Locales que se pueden asignar a un usuario. Alimenta el selector
    "Local Asignado" del formulario.

    Delega en el service de puntos de venta en lugar de repetir la query
    (Principio 2): es la misma lista que usa la asignación de dispositivos.
    """
    from app.services.puntos_de_venta import locales_activos

    return locales_activos(db)


def roles_asignables(db: Session, autor: Usuario) -> list[Rol]:
    """
    Roles que el usuario logueado puede asignar. Alimenta el selector del
    formulario de alta/edición.
    """
    consulta = select(Rol).where(Rol.activo.is_(True)).order_by(Rol.nombre)
    roles = list(db.execute(consulta).scalars().all())

    if autor.rol and autor.rol.nombre == ROL_CUENTA_MAESTRA:
        # Nadie puede asignar cuenta_maestra: solo existe la del seed.
        return [r for r in roles if r.nombre != ROL_CUENTA_MAESTRA]

    if autor.rol and autor.rol.nombre == ROL_SUPERVISOR:
        return [r for r in roles if r.nombre == ROL_VENDEDOR]

    return [r for r in roles if r.nombre != ROL_CUENTA_MAESTRA]


# ============================================================================
# LISTADO Y ABM
# ============================================================================


def listar_usuarios(
    db: Session,
    nombre: str | None = None,
    username: str | None = None,
    email: str | None = None,
    rol_id: int | None = None,
    local_asignado_id: int | None = None,
    activo: bool | None = None,
    pagina: int = 1,
    tamano: int = 50,
) -> tuple[list[Usuario], int]:
    """
    Listado con los filtros del Principio 5, resueltos siempre en el
    backend. Devuelve (resultados de la página, total de coincidencias).
    """
    consulta = select(Usuario)

    if nombre:
        consulta = consulta.where(Usuario.nombre.ilike(f"%{nombre}%"))
    if username:
        consulta = consulta.where(Usuario.username.ilike(f"%{username}%"))
    if email:
        consulta = consulta.where(Usuario.email.ilike(f"%{email}%"))
    if rol_id is not None:
        consulta = consulta.where(Usuario.rol_id == rol_id)
    if local_asignado_id is not None:
        consulta = consulta.where(Usuario.local_asignado_id == local_asignado_id)
    if activo is not None:
        consulta = consulta.where(Usuario.activo.is_(activo))

    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()

    resultados = (
        db.execute(
            consulta.order_by(Usuario.nombre).limit(tamano).offset((pagina - 1) * tamano)
        )
        .unique()
        .scalars()
        .all()
    )
    return list(resultados), total


def crear_usuario(
    db: Session,
    autor: Usuario,
    username: str,
    nombre: str,
    password: str,
    rol_id: int,
    email: str | None = None,
    fecha_nacimiento: date | None = None,
    celular: str | None = None,
    local_asignado_id: int | None = None,
    ip_origen: str | None = None,
) -> Usuario:
    """Alta de usuario, con todas las reglas de negocio aplicadas."""
    rol = obtener_rol(db, rol_id)
    validar_puede_gestionar(autor, rol)

    if not rol.activo:
        raise ReglaDeNegocio("No se puede asignar un rol inactivo")

    # Solo puede existir una Cuenta Maestra en todo el sistema.
    if rol.nombre == ROL_CUENTA_MAESTRA:
        ya_existe = db.execute(
            select(func.count(Usuario.id)).where(Usuario.rol_id == rol.id)
        ).scalar_one()
        if ya_existe:
            raise ReglaDeNegocio("Ya existe un usuario con rol cuenta_maestra")

    username_limpio = (normalizar_texto(username) or "").lower()
    if not username_limpio:
        raise ReglaDeNegocio("El username es obligatorio")

    if db.execute(
        select(Usuario.id).where(Usuario.username == username_limpio)
    ).scalar_one_or_none():
        raise ReglaDeNegocio(f"Ya existe un usuario con el username '{username_limpio}'")

    email_limpio = normalizar_texto(email)
    if email_limpio and db.execute(
        select(Usuario.id).where(Usuario.email == email_limpio)
    ).scalar_one_or_none():
        raise ReglaDeNegocio(f"Ya existe un usuario con el email '{email_limpio}'")

    local_id = _validar_local_asignado(db, local_asignado_id)

    usuario = Usuario(
        username=username_limpio,
        email=email_limpio,
        password_hash=hash_password(password),
        nombre=normalizar_texto(nombre) or username_limpio,
        rol_id=rol.id,
        activo=True,
        fecha_nacimiento=fecha_nacimiento,
        celular=celular,
        local_asignado_id=local_id,
        created_at=ahora_db(),
        updated_at=ahora_db(),
        ultimo_acceso=None,  # obliga a cambiar la contraseña en el primer login
    )
    db.add(usuario)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="usuario.crear",
        entidad="usuarios",
        entidad_id=usuario.id,
        estado_nuevo=usuario,  # snapshot() filtra los hashes
        ip_origen=ip_origen,
    )
    return usuario


def editar_usuario(
    db: Session,
    autor: Usuario,
    usuario_id: int,
    nombre: str | None = None,
    email: str | None = None,
    rol_id: int | None = None,
    password: str | None = None,
    fecha_nacimiento: date | None = None,
    celular: str | None = None,
    local_asignado_id: int | None = None,
    editar_fecha_nacimiento: bool = False,
    editar_celular: bool = False,
    editar_local: bool = False,
    ip_origen: str | None = None,
) -> Usuario:
    """
    Edición de usuario. Cambiar la contraseña revoca sus sesiones.

    Los tres campos personales son opcionales y deben poder vaciarse, así
    que su flag `editar_*` distingue "no lo mandaron" de "lo mandaron en
    NULL" — la misma convención que `asignar_local` en dispositivos.
    """
    usuario = obtener_usuario(db, usuario_id)
    validar_puede_gestionar(autor, usuario.rol)
    antes = snapshot(usuario)

    if rol_id is not None and rol_id != usuario.rol_id:
        rol_nuevo = obtener_rol(db, rol_id)
        validar_puede_gestionar(autor, rol_nuevo)

        if not rol_nuevo.activo:
            raise ReglaDeNegocio("No se puede asignar un rol inactivo")
        if rol_nuevo.nombre == ROL_CUENTA_MAESTRA:
            raise ReglaDeNegocio("No se puede asignar el rol cuenta_maestra")
        if usuario.rol.nombre == ROL_CUENTA_MAESTRA:
            raise ReglaDeNegocio("No se puede cambiar el rol de la Cuenta Maestra")

        usuario.rol_id = rol_nuevo.id

    if nombre is not None:
        usuario.nombre = normalizar_texto(nombre) or usuario.nombre

    if email is not None:
        email_limpio = normalizar_texto(email)
        if email_limpio:
            duplicado = db.execute(
                select(Usuario.id).where(Usuario.email == email_limpio, Usuario.id != usuario.id)
            ).scalar_one_or_none()
            if duplicado:
                raise ReglaDeNegocio(f"Ya existe un usuario con el email '{email_limpio}'")
        usuario.email = email_limpio

    if editar_fecha_nacimiento:
        usuario.fecha_nacimiento = fecha_nacimiento

    if editar_celular:
        usuario.celular = celular

    if editar_local:
        usuario.local_asignado_id = _validar_local_asignado(db, local_asignado_id)

    if password:
        usuario.password_hash = hash_password(password)
        usuario.ultimo_acceso = None  # vuelve a exigir cambio en el próximo login
        revocar_sesiones_de_usuario(db, usuario.id)

    usuario.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="usuario.editar",
        entidad="usuarios",
        entidad_id=usuario.id,
        estado_anterior=antes,
        estado_nuevo=usuario,
        ip_origen=ip_origen,
    )
    return usuario


def cambiar_estado_usuario(
    db: Session,
    autor: Usuario,
    usuario_id: int,
    activo: bool,
    ip_origen: str | None = None,
) -> Usuario:
    """
    Activa o desactiva un usuario. Nadie puede desactivarse a sí mismo, y
    la Cuenta Maestra no se puede desactivar: dejaría al sistema sin
    administrador.
    """
    usuario = obtener_usuario(db, usuario_id)
    validar_puede_gestionar(autor, usuario.rol)

    if usuario.id == autor.id and not activo:
        raise ReglaDeNegocio("Un usuario no puede desactivarse a sí mismo")

    if usuario.rol.nombre == ROL_CUENTA_MAESTRA and not activo:
        raise ReglaDeNegocio("No se puede desactivar la Cuenta Maestra")

    antes = snapshot(usuario)
    usuario.activo = activo
    usuario.updated_at = ahora_db()

    # Al desactivar, cortar las sesiones abiertas: si no, el JWT vigente
    # seguiría funcionando hasta expirar.
    if not activo:
        revocar_sesiones_de_usuario(db, usuario.id)

    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="usuario.activar" if activo else "usuario.desactivar",
        entidad="usuarios",
        entidad_id=usuario.id,
        estado_anterior=antes,
        estado_nuevo=usuario,
        ip_origen=ip_origen,
    )
    return usuario


# ============================================================================
# HISTORIAL DE ACCESOS
# ============================================================================


def historial_de_usuario(
    db: Session,
    usuario_id: int,
    desde: date | None = None,
    hasta: date | None = None,
    resultado: str | None = None,
    pagina: int = 1,
    tamano: int = 50,
) -> tuple[list[HistorialAcceso], int]:
    """Historial de accesos de un usuario, con filtro de rango de fechas."""
    obtener_usuario(db, usuario_id)  # 404 si no existe

    consulta = select(HistorialAcceso).where(HistorialAcceso.usuario_id == usuario_id)

    if desde:
        consulta = consulta.where(HistorialAcceso.timestamp >= desde)
    if hasta:
        # El rango es inclusivo: sumar un día cubre todo el día "hasta".
        consulta = consulta.where(func.date(HistorialAcceso.timestamp) <= hasta)
    if resultado:
        consulta = consulta.where(HistorialAcceso.resultado == resultado)

    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()

    filas = (
        db.execute(
            consulta.order_by(HistorialAcceso.timestamp.desc())
            .limit(tamano)
            .offset((pagina - 1) * tamano)
        )
        .scalars()
        .all()
    )
    return list(filas), total


# ============================================================================
# CLAVE ESPECIAL (solo Cuenta Maestra)
# ============================================================================


def _exigir_cuenta_maestra(usuario: Usuario) -> None:
    """
    Los endpoints de clave especial devuelven 404 —no 403— para usuarios
    que no son Cuenta Maestra: no hay razón para revelar que existen.
    """
    if usuario.rol is None or usuario.rol.nombre != ROL_CUENTA_MAESTRA:
        raise NoEncontrado("Recurso inexistente")


def validar_clave_especial(db: Session, usuario_id: int, clave: str) -> bool:
    """Verifica la clave especial de la Cuenta Maestra."""
    from app.services.auth import verificar_password

    usuario = obtener_usuario(db, usuario_id)
    _exigir_cuenta_maestra(usuario)

    if not usuario.clave_especial_hash:
        return False

    return verificar_password(clave, usuario.clave_especial_hash)


def resetear_clave_especial(
    db: Session, autor: Usuario, usuario_id: int, clave_nueva: str, ip_origen: str | None = None
) -> None:
    """
    Define o cambia la clave especial. La clave nunca se audita: solo
    queda constancia de que se cambió.
    """
    usuario = obtener_usuario(db, usuario_id)
    _exigir_cuenta_maestra(usuario)

    usuario.clave_especial_hash = hash_password(clave_nueva)
    usuario.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="usuario.clave_especial_resetear",
        entidad="usuarios",
        entidad_id=usuario.id,
        estado_nuevo={"username": usuario.username, "clave_especial": "actualizada"},
        ip_origen=ip_origen,
    )
