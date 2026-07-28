"""
Endpoints de autenticación.

El JWT se devuelve en el cuerpo (para clientes de API) y además se setea
en una cookie HttpOnly, que es lo que usa el frontend con HTMX: así el
token viaja solo en cada request, sin JavaScript de por medio.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria
from app.core.database import get_db
from app.core.email import enviar_reset_password
from app.core.permisos import get_current_user
from app.core.utils import ip_de_request
from app.schemas.auth import (
    AccessTokenResponse,
    CambiarPasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    ResetPasswordRequest,
    TokenResponse,
    UsuarioToken,
)
from app.schemas.comunes import MensajeResponse
from app.services import auth as servicio_auth
from config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


def _setear_cookies(response: Response, access: str, refresh: str) -> None:
    """
    Guarda los tokens en cookies HttpOnly.

    HttpOnly evita que un XSS pueda leer el token desde JavaScript;
    SameSite=lax corta el uso cross-site sin romper la navegación normal.
    """
    response.set_cookie(
        settings.JWT_COOKIE_NAME,
        access,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.JWT_ACCESS_TOKEN_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        settings.JWT_REFRESH_COOKIE_NAME,
        refresh,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.JWT_REFRESH_TOKEN_DAYS * 24 * 3600,
        path="/",
    )


def _borrar_cookies(response: Response) -> None:
    response.delete_cookie(settings.JWT_COOKIE_NAME, path="/")
    response.delete_cookie(settings.JWT_REFRESH_COOKIE_NAME, path="/")


@router.post("/login", response_model=TokenResponse, summary="Iniciar sesión")
def login(
    datos: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    Autentica por username + contraseña.

    Todo intento, exitoso o fallido, queda registrado en
    `historial_accesos` y en `auditoria`.
    """
    ip = ip_de_request(request)

    try:
        usuario = servicio_auth.autenticar_usuario(db, datos.username, datos.password, ip)
    except servicio_auth.CredencialesInvalidas as exc:
        # El registro del intento fallido ya quedó en la sesión: se commitea
        # igual, porque la auditoría no depende de que el login salga bien.
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    access, refresh = servicio_auth.generar_tokens(db, usuario.id, ip)

    # `ultimo_acceso` se sella solo si el usuario ya no debe cambiar la
    # contraseña: mientras esté en NULL, el sistema lo sigue exigiendo.
    debe_cambiar = servicio_auth.debe_cambiar_password(usuario)
    if not debe_cambiar:
        servicio_auth.marcar_acceso(db, usuario)

    db.commit()

    _setear_cookies(response, access, refresh)

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.JWT_ACCESS_TOKEN_MINUTES * 60,
        usuario=UsuarioToken(
            id=usuario.id,
            username=usuario.username,
            nombre=usuario.nombre,
            rol=usuario.rol.nombre,
            debe_cambiar_password=debe_cambiar,
        ),
    )


@router.post("/refresh", response_model=AccessTokenResponse, summary="Renovar access token")
def refresh(
    datos: RefreshRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Emite un access token nuevo a partir del refresh token."""
    token = datos.refresh_token or request.cookies.get(settings.JWT_REFRESH_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Falta el refresh token"
        )

    try:
        access = servicio_auth.refrescar_access_token(db, token)
    except servicio_auth.TokenInvalido as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    db.commit()

    response.set_cookie(
        settings.JWT_COOKIE_NAME,
        access,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.JWT_ACCESS_TOKEN_MINUTES * 60,
        path="/",
    )

    return AccessTokenResponse(
        access_token=access, expires_in=settings.JWT_ACCESS_TOKEN_MINUTES * 60
    )


@router.post("/logout", response_model=MensajeResponse, summary="Cerrar sesión")
def logout(
    datos: RefreshRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    """Revoca el refresh token y borra las cookies."""
    token = datos.refresh_token or request.cookies.get(settings.JWT_REFRESH_COOKIE_NAME)
    if token:
        servicio_auth.revocar_sesion(db, token)

    registrar_auditoria(
        db,
        usuario_id=usuario.id,
        accion="auth.logout",
        entidad="usuarios",
        entidad_id=usuario.id,
        ip_origen=ip_de_request(request),
    )
    db.commit()

    _borrar_cookies(response)
    return MensajeResponse(mensaje="Sesión cerrada")


@router.post(
    "/forgot-password", response_model=MensajeResponse, summary="Pedir reseteo de contraseña"
)
def forgot_password(
    datos: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)
):
    """
    Envía el email de recuperación, solo si el usuario existe y tiene
    email cargado.

    La respuesta es siempre la misma, exista o no el usuario: no hay que
    revelar qué usernames están dados de alta.
    """
    from sqlalchemy import select

    from app.models.usuario import Usuario

    generico = MensajeResponse(
        mensaje="Si el usuario existe y tiene email cargado, se envió un mensaje con las instrucciones"
    )

    usuario = db.execute(
        select(Usuario).where(Usuario.username == datos.username.lower())
    ).scalar_one_or_none()

    if usuario is None or not usuario.activo or not usuario.email:
        return generico

    token = servicio_auth.generar_token_reset(usuario)
    enviar_reset_password(usuario.email, usuario.nombre, token)

    registrar_auditoria(
        db,
        usuario_id=usuario.id,
        accion="auth.reset_solicitar",
        entidad="usuarios",
        entidad_id=usuario.id,
        estado_nuevo={"username": usuario.username},
        ip_origen=ip_de_request(request),
    )
    db.commit()

    return generico


@router.post(
    "/reset-password", response_model=MensajeResponse, summary="Aplicar nueva contraseña"
)
def reset_password(
    datos: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)
):
    """Aplica la contraseña nueva con el token recibido por email."""
    try:
        usuario = servicio_auth.validar_token_reset(db, datos.token)
    except servicio_auth.TokenInvalido as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    servicio_auth.cambiar_password(
        db, usuario, datos.password_nueva, autor_id=usuario.id, ip_origen=ip_de_request(request)
    )
    # Ya definió una contraseña propia: no hace falta forzar otro cambio.
    servicio_auth.marcar_acceso(db, usuario)
    db.commit()

    return MensajeResponse(mensaje="Contraseña actualizada")


@router.post(
    "/cambiar-password", response_model=MensajeResponse, summary="Cambiar la propia contraseña"
)
def cambiar_password(
    datos: CambiarPasswordRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    """
    Cambio de contraseña del usuario logueado. Es el flujo del cambio
    obligatorio en el primer ingreso.
    """
    if not servicio_auth.verificar_password(datos.password_actual, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="La contraseña actual no es correcta"
        )

    servicio_auth.cambiar_password(
        db, usuario, datos.password_nueva, autor_id=usuario.id, ip_origen=ip_de_request(request)
    )
    servicio_auth.marcar_acceso(db, usuario)

    # cambiar_password revoca todas las sesiones: hay que emitir una nueva
    # para no dejar afuera al usuario que acaba de cambiarla.
    access, refresh = servicio_auth.generar_tokens(db, usuario.id, ip_de_request(request))
    db.commit()

    _setear_cookies(response, access, refresh)
    return MensajeResponse(mensaje="Contraseña actualizada")


@router.get("/me", summary="Datos del usuario logueado")
def me(usuario=Depends(get_current_user)) -> UsuarioToken:
    """Devuelve quién está autenticado. Útil para el frontend y para probar el token."""
    return UsuarioToken(
        id=usuario.id,
        username=usuario.username,
        nombre=usuario.nombre,
        rol=usuario.rol.nombre,
        debe_cambiar_password=servicio_auth.debe_cambiar_password(usuario),
    )
