"""
Autenticación: hashing de contraseñas, emisión y validación de JWT,
login/logout y recuperación de contraseña.

Toda la lógica vive acá y no en el router: vale igual para la API, para
el HTML y para cualquier cliente futuro (Principio 1).
"""

import secrets
from datetime import timedelta

import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria
from app.core.utils import ahora, ahora_db
from app.models.sesion import Sesion
from app.models.usuario import HistorialAcceso, ResultadoAcceso, Usuario
from config import settings

# bcrypt: estándar del proyecto para contraseñas y claves especiales.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


class TokenInvalido(Exception):
    """El JWT no es válido: expirado, mal firmado o del tipo equivocado."""


class CredencialesInvalidas(Exception):
    """Usuario o contraseña incorrectos, o usuario/rol inactivo."""


# ============================================================================
# CONTRASEÑAS
# ============================================================================


def hash_password(password: str) -> str:
    """Hash bcrypt de una contraseña en texto plano."""
    return pwd_context.hash(password)


def verificar_password(password: str, hash_guardado: str) -> bool:
    """Compara una contraseña con su hash. Nunca lanza: devuelve False."""
    try:
        return pwd_context.verify(password, hash_guardado)
    except Exception:  # noqa: BLE001 - hash corrupto o formato desconocido
        return False


# ============================================================================
# TOKENS
# ============================================================================


def _crear_token(payload: dict, expira_en: timedelta, tipo: str) -> str:
    """Firma un JWT con los claims estándar del sistema."""
    emitido = ahora()
    cuerpo = {
        **payload,
        "tipo": tipo,
        "iat": emitido,
        "exp": emitido + expira_en,
    }
    return jwt.encode(cuerpo, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def verificar_token(token: str, tipo: str = "access") -> dict:
    """
    Valida firma y expiración, y comprueba que el token sea del tipo
    esperado (un refresh token no sirve como access token).

    Raises:
        TokenInvalido: si algo no cierra.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenInvalido("Token expirado") from exc
    except jwt.PyJWTError as exc:
        raise TokenInvalido("Token inválido") from exc

    if payload.get("tipo") != tipo:
        raise TokenInvalido(f"Se esperaba un token de tipo '{tipo}'")

    return payload


def generar_tokens(
    db: Session, usuario_id: int, ip_origen: str | None = None
) -> tuple[str, str]:
    """
    Emite el par (access_token, refresh_token) y registra la sesión.

    El access token es de corta duración; el refresh, largo y revocable:
    su `jti` queda en la tabla `sesiones` para que logout lo invalide.
    """
    access = _crear_token(
        {"sub": str(usuario_id)},
        timedelta(minutes=settings.JWT_ACCESS_TOKEN_MINUTES),
        tipo="access",
    )

    jti = secrets.token_urlsafe(32)

    # `expira_en` es la VENTANA DE INACTIVIDAD, no el vencimiento del refresh
    # token: arranca en media hora y cada actividad la corre
    # (`registrar_actividad`). El límite de 7 días sigue existiendo por dos
    # lados —el `exp` del propio JWT y el tope sobre `creada_en`—, así que una
    # sesión con movimiento continuo tampoco vive para siempre.
    #
    # Ponerla en 7 días acá, como estaba, hacía que la ventana naciera abierta
    # de par en par y nunca se cerrara.
    expira = ahora_db() + timedelta(minutes=settings.SESION_INACTIVIDAD_MINUTOS)
    refresh = _crear_token(
        {"sub": str(usuario_id), "jti": jti},
        timedelta(days=settings.JWT_REFRESH_TOKEN_DAYS),
        tipo="refresh",
    )

    db.add(
        Sesion(usuario_id=usuario_id, jti=jti, expira_en=expira, ip_origen=ip_origen)
    )
    db.flush()

    return access, refresh


# Cada cuánto, como mucho, se escribe la ventana en la base.
#
# Correrla en cada request sería un UPDATE por request, y el punto de venta
# hace muchos seguidos. Con este freno, la ventana se mueve a lo sumo una vez
# por minuto: lo que se pierde son segundos de precisión sobre una ventana de
# media hora.
_FRENO_ESCRITURA = timedelta(seconds=60)


def registrar_actividad(db: Session, sesion: Sesion) -> None:
    """
    Corre la ventana de inactividad de la sesión.

    `expira_en` es la ventana deslizante: cada actividad la empuja a
    `ahora + SESION_INACTIVIDAD_MINUTOS`, con tope en el vencimiento absoluto
    del refresh token —`creada_en + JWT_REFRESH_TOKEN_DAYS`—, que ninguna
    actividad puede pasar. Sin ese tope, una sesión con movimiento cada 20
    minutos viviría para siempre.

    NO valida nada: se llama después de haber comprobado que la sesión sigue
    viva. Al revés —correr primero y verificar después— el request que llega
    tarde resetearía la ventana antes de que nadie la mire, y la sesión no
    vencería nunca. Es justo el error que este cambio viene a arreglar.
    """
    nuevo = ahora_db() + timedelta(minutes=settings.SESION_INACTIVIDAD_MINUTOS)
    tope = sesion.creada_en + timedelta(days=settings.JWT_REFRESH_TOKEN_DAYS)
    nuevo = min(nuevo, tope)

    if nuevo - sesion.expira_en >= _FRENO_ESCRITURA:
        sesion.expira_en = nuevo
        db.flush()


def sesion_vigente(db: Session, refresh_token: str) -> Sesion:
    """
    La sesión del refresh token, si sigue viva.

    Es el único lugar donde se decide que una sesión está viva, y lo usan los
    dos caminos que renuevan: el middleware y el endpoint `/auth/refresh`
    —que está excluido del middleware, así que si la regla viviera allá este
    endpoint sería un desvío para saltearla—.

    Raises:
        TokenInvalido: token inválido, sesión revocada o vencida por
            inactividad.
    """
    payload = verificar_token(refresh_token, tipo="refresh")

    sesion = db.execute(
        select(Sesion).where(Sesion.jti == payload.get("jti"))
    ).scalar_one_or_none()
    if sesion is None or sesion.revocada:
        raise TokenInvalido("Sesión revocada")

    if sesion.expira_en < ahora_db():
        # Se revoca y no solo se rechaza: así el refresh token queda muerto de
        # verdad y un navegador que se lo haya guardado tampoco puede volver
        # a entrar con él.
        sesion.revocada = True
        db.flush()
        raise TokenInvalido("Sesión vencida por inactividad")

    return sesion


def refrescar_access_token(db: Session, refresh_token: str) -> str:
    """
    Devuelve un access token nuevo a partir de un refresh token válido, no
    revocado y con actividad reciente.

    Raises:
        TokenInvalido: token vencido, revocado, vencido por inactividad o de
            usuario inactivo.
    """
    sesion = sesion_vigente(db, refresh_token)

    usuario = db.get(Usuario, sesion.usuario_id)
    if usuario is None or not usuario.activo:
        raise TokenInvalido("Usuario inactivo o inexistente")

    # Renovar el access ES actividad: corre la ventana.
    registrar_actividad(db, sesion)

    return _crear_token(
        {"sub": str(usuario.id)},
        timedelta(minutes=settings.JWT_ACCESS_TOKEN_MINUTES),
        tipo="access",
    )


def revocar_sesion(db: Session, refresh_token: str) -> bool:
    """
    Marca como revocada la sesión del refresh token. Idempotente: si el
    token ya no es válido devuelve False sin lanzar.
    """
    try:
        payload = verificar_token(refresh_token, tipo="refresh")
    except TokenInvalido:
        return False

    sesion = db.execute(select(Sesion).where(Sesion.jti == payload.get("jti"))).scalar_one_or_none()
    if sesion is None or sesion.revocada:
        return False

    sesion.revocada = True
    db.flush()
    return True


def revocar_sesiones_de_usuario(db: Session, usuario_id: int) -> int:
    """
    Revoca todas las sesiones abiertas de un usuario. Se usa al
    desactivarlo o al cambiarle la contraseña.
    """
    sesiones = db.execute(
        select(Sesion).where(Sesion.usuario_id == usuario_id, Sesion.revocada.is_(False))
    ).scalars().all()
    for sesion in sesiones:
        sesion.revocada = True
    db.flush()
    return len(sesiones)


# ============================================================================
# LOGIN
# ============================================================================


def _registrar_intento(
    db: Session,
    usuario: Usuario | None,
    resultado: ResultadoAcceso,
    ip_origen: str | None,
    detalle: str | None = None,
    username_intentado: str | None = None,
) -> None:
    """
    Deja constancia del intento de login en las dos tablas que corresponde.

    `historial_accesos` requiere un usuario existente (FK NOT NULL), así
    que los intentos contra un usuario inexistente quedan solo en
    `auditoria`, que sí acepta usuario_id NULL.
    """
    if usuario is not None:
        db.add(
            HistorialAcceso(
                usuario_id=usuario.id,
                timestamp=ahora_db(),
                ip_origen=ip_origen,
                resultado=resultado,
                detalle=detalle,
            )
        )

    registrar_auditoria(
        db,
        usuario_id=usuario.id if usuario else None,
        accion="auth.login" if resultado == ResultadoAcceso.EXITOSO else "auth.login_fallido",
        entidad="usuarios",
        entidad_id=usuario.id if usuario else None,
        estado_nuevo={
            "resultado": resultado.value,
            "detalle": detalle,
            "username": usuario.username if usuario else username_intentado,
        },
        ip_origen=ip_origen,
    )


def autenticar_usuario(
    db: Session, username: str, password: str, ip_origen: str | None = None
) -> Usuario:
    """
    Verifica credenciales y registra el intento (exitoso o fallido) en
    `historial_accesos` y en `auditoria`.

    No hace commit: lo hace el router, junto con el resto de la operación.

    Raises:
        CredencialesInvalidas: siempre con el mismo mensaje genérico, para
            no revelar si el usuario existe.
    """
    usuario = db.execute(
        select(Usuario).where(Usuario.username == username)
    ).scalar_one_or_none()

    if usuario is None:
        _registrar_intento(
            db, None, ResultadoAcceso.FALLIDO, ip_origen,
            detalle="Usuario inexistente", username_intentado=username,
        )
        raise CredencialesInvalidas("Usuario o contraseña incorrectos")

    if not verificar_password(password, usuario.password_hash):
        _registrar_intento(
            db, usuario, ResultadoAcceso.FALLIDO, ip_origen, detalle="Contraseña incorrecta"
        )
        raise CredencialesInvalidas("Usuario o contraseña incorrectos")

    if not usuario.activo:
        _registrar_intento(
            db, usuario, ResultadoAcceso.FALLIDO, ip_origen, detalle="Usuario inactivo"
        )
        raise CredencialesInvalidas("Usuario o contraseña incorrectos")

    if usuario.rol is None or not usuario.rol.activo:
        _registrar_intento(
            db, usuario, ResultadoAcceso.FALLIDO, ip_origen, detalle="Rol inactivo"
        )
        raise CredencialesInvalidas("Usuario o contraseña incorrectos")

    _registrar_intento(db, usuario, ResultadoAcceso.EXITOSO, ip_origen)
    return usuario


def marcar_acceso(db: Session, usuario: Usuario) -> None:
    """
    Sella `ultimo_acceso`. Se llama recién cuando el usuario completó el
    cambio de contraseña obligatorio: mientras siga en NULL, el sistema
    lo sigue mandando a esa pantalla.
    """
    usuario.ultimo_acceso = ahora_db()
    db.flush()


def debe_cambiar_password(usuario: Usuario) -> bool:
    """True si el usuario nunca ingresó y tiene que cambiar la contraseña."""
    return usuario.ultimo_acceso is None


# ============================================================================
# RECUPERACIÓN DE CONTRASEÑA
# ============================================================================


def generar_token_reset(usuario: Usuario) -> str:
    """
    Token de reseteo de contraseña, de un solo uso y vida corta.

    El single-use no necesita tabla: el claim `pwd` lleva un fragmento del
    hash actual, así que al cambiar la contraseña el token deja de validar.
    """
    return _crear_token(
        {"sub": str(usuario.id), "pwd": usuario.password_hash[-16:]},
        timedelta(minutes=30),
        tipo="reset",
    )


def validar_token_reset(db: Session, token: str) -> Usuario:
    """
    Valida un token de reseteo y devuelve el usuario.

    Raises:
        TokenInvalido: token vencido, adulterado o ya usado.
    """
    payload = verificar_token(token, tipo="reset")

    usuario = db.get(Usuario, int(payload["sub"]))
    if usuario is None or not usuario.activo:
        raise TokenInvalido("Usuario inactivo o inexistente")

    if payload.get("pwd") != usuario.password_hash[-16:]:
        raise TokenInvalido("El token ya fue utilizado")

    return usuario


def cambiar_password(
    db: Session,
    usuario: Usuario,
    password_nueva: str,
    autor_id: int | None = None,
    ip_origen: str | None = None,
) -> None:
    """
    Cambia la contraseña, revoca todas las sesiones abiertas y audita.
    Nunca registra la contraseña ni su hash en la auditoría.
    """
    usuario.password_hash = hash_password(password_nueva)
    usuario.updated_at = ahora_db()
    db.flush()

    revocar_sesiones_de_usuario(db, usuario.id)

    registrar_auditoria(
        db,
        usuario_id=autor_id if autor_id is not None else usuario.id,
        accion="usuario.cambiar_password",
        entidad="usuarios",
        entidad_id=usuario.id,
        estado_nuevo={"username": usuario.username},
        ip_origen=ip_origen,
    )
