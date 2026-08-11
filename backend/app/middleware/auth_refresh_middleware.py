"""
Middleware de renovación de la sesión.

Cuando la cookie de acceso venció pero el refresh token sigue vivo, emite un
access token nuevo y lo deja en `request.state.access_renovado` (lo lee
`get_current_user`) y en una cookie de la response.

Sin esto la sesión duraba 30 minutos contados desde el login —no desde la
última actividad— y el refresh de 7 días no lo usaba nadie: el endpoint
`/api/v1/auth/refresh` existe, pero no hay una sola llamada en el frontend.

Va como middleware y no como reintento en el JavaScript porque así cubre los
tres caminos de una vez: las páginas HTML, los `fetch` de Alpine y los
requests de HTMX, que usan XMLHttpRequest y no pasarían por un interceptor
de `fetch`.
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.database import SessionLocal
from config import settings

logger = logging.getLogger(__name__)

# Solo los dos endpoints que emiten tokens ellos mismos. NO se excluye
# `/api/v1/auth` entero: ahí viven endpoints normales como `/me`, y sobre
# todo `/logout`, que necesita al usuario autenticado para poder revocar el
# refresh token. Sin renovar, un logout con el access vencido daría 401 y
# dejaría la sesión viva 7 días más — justo lo contrario de lo que se pidió.
PREFIJOS_EXCLUIDOS = (
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/static",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon",
)


class AuthRefreshMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.access_renovado = None

        token_nuevo = _renovar_si_hace_falta(request)
        if token_nuevo is not None:
            request.state.access_renovado = token_nuevo

        response = await call_next(request)

        # Si el handler ya se ocupó de la cookie, no se le pisa: el caso que
        # importa es `logout`, que la BORRA. Como esto corre después, escribir
        # acá le devolvería al usuario un access token válido por 30 minutos
        # más justo cuando acaba de cerrar sesión.
        if token_nuevo is not None and not _response_toca_la_cookie(response):
            _setear_cookie(response, token_nuevo)

        return response


def _renovar_si_hace_falta(request: Request) -> str | None:
    """
    Devuelve un access token nuevo, o None si no corresponde renovar.

    Nunca levanta: un fallo acá dejaría sin servicio a toda la aplicación por
    algo que, en el peor caso, se resuelve volviendo a entrar.
    """
    from app.services import auth as servicio_auth

    if _excluida(request.url.path):
        return None

    # Una credencial explícita manda sobre la cookie, igual que en
    # `get_current_user`: si alguien manda un Bearer, esa es la que quiere
    # usar, y taparla con una sesión del navegador sería una sorpresa.
    if request.headers.get("authorization", "").lower().startswith("bearer "):
        return None

    if _access_vigente(request.cookies.get(settings.JWT_COOKIE_NAME)):
        return None

    refresh = request.cookies.get(settings.JWT_REFRESH_COOKIE_NAME)
    if not refresh:
        return None

    db = SessionLocal()
    try:
        # La misma función que usa el endpoint `/auth/refresh`: valida la
        # firma, que la sesión no esté revocada y que el usuario siga activo.
        # Si algo de eso falla levanta TokenInvalido y no se renueva nada —es
        # lo que hace que cerrar sesión signifique algo.
        return servicio_auth.refrescar_access_token(db, refresh)
    except servicio_auth.TokenInvalido:
        return None
    except Exception:  # noqa: BLE001 - renovar nunca debe romper la request
        logger.exception("Fallo renovando el access token")
        return None
    finally:
        db.close()


def _access_vigente(token: str | None) -> bool:
    from app.services.auth import TokenInvalido, verificar_token

    if not token:
        return False
    try:
        verificar_token(token, tipo="access")
        return True
    except TokenInvalido:
        return False


def _excluida(path: str) -> bool:
    return any(path.startswith(prefijo) for prefijo in PREFIJOS_EXCLUIDOS)


def _response_toca_la_cookie(response) -> bool:
    """¿El handler ya emitió un Set-Cookie para la cookie de acceso?"""
    prefijo = f"{settings.JWT_COOKIE_NAME}=".encode()
    return any(
        nombre.lower() == b"set-cookie" and valor.startswith(prefijo)
        for nombre, valor in response.raw_headers
    )


def _setear_cookie(response, token: str) -> None:
    """Mismos atributos que la cookie que emite el login (`api/v1/auth.py`)."""
    response.set_cookie(
        settings.JWT_COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.JWT_ACCESS_TOKEN_MINUTES * 60,
        path="/",
    )
