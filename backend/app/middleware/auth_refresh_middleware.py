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

        # `caida` es True cuando la sesión existía pero ya no sirve: se venció
        # por inactividad o la revocaron. Se distingue de "no había nada que
        # renovar" para poder limpiar las cookies, que si no siguen viajando
        # muertas en cada request.
        token_nuevo, caida = _revisar_sesion(request)
        if token_nuevo is not None:
            request.state.access_renovado = token_nuevo

        response = await call_next(request)

        # Si el handler ya se ocupó de la cookie, no se le pisa: el caso que
        # importa es `logout`, que la BORRA. Como esto corre después, escribir
        # acá le devolvería al usuario un access token válido por 30 minutos
        # más justo cuando acaba de cerrar sesión.
        if token_nuevo is not None and not _response_toca_la_cookie(response):
            _setear_cookie(response, token_nuevo)

        if caida:
            _borrar_cookies(response)

        return response


def _revisar_sesion(request: Request) -> tuple[str | None, bool]:
    """
    Mira la sesión del request y devuelve `(access_nuevo, caida)`.

    Hace dos cosas que van juntas:

    1. REGISTRA LA ACTIVIDAD. Corre la ventana de inactividad en cada request,
       no solo cuando toca renovar: si solo se contara al renovar, alguien
       trabajando sin parar durante media hora vería vencer su sesión igual,
       porque su access token todavía vigente nunca habría pasado por acá.
    2. RENUEVA el access token si venció y la sesión sigue viva.

    Nunca levanta: un fallo acá dejaría sin servicio a toda la aplicación por
    algo que, en el peor caso, se resuelve volviendo a entrar.
    """
    from app.services import auth as servicio_auth

    if _excluida(request.url.path):
        return None, False

    # Una credencial explícita manda sobre la cookie, igual que en
    # `get_current_user`: si alguien manda un Bearer, esa es la que quiere
    # usar, y taparla con una sesión del navegador sería una sorpresa.
    if request.headers.get("authorization", "").lower().startswith("bearer "):
        return None, False

    refresh = request.cookies.get(settings.JWT_REFRESH_COOKIE_NAME)
    if not refresh:
        return None, False

    hay_que_renovar = not _access_vigente(request.cookies.get(settings.JWT_COOKIE_NAME))

    db = SessionLocal()
    try:
        if hay_que_renovar:
            # La misma función que usa el endpoint `/auth/refresh`: valida la
            # firma, que la sesión no esté revocada, que no se haya vencido
            # por inactividad y que el usuario siga activo. Si algo de eso
            # falla levanta TokenInvalido y no se renueva nada —es lo que hace
            # que cerrar sesión signifique algo—.
            token = servicio_auth.refrescar_access_token(db, refresh)
            db.commit()
            return token, False

        # El access sigue vigente: no hay nada que renovar, pero esto ES
        # actividad y la ventana tiene que correrse igual.
        sesion = servicio_auth.sesion_vigente(db, refresh)
        servicio_auth.registrar_actividad(db, sesion)
        db.commit()
        return None, False
    except servicio_auth.TokenInvalido:
        # La sesión existía y ya no sirve. El commit deja escrita la
        # revocación que hizo `sesion_vigente` al encontrarla vencida.
        db.commit()
        return None, True
    except Exception:  # noqa: BLE001 - renovar nunca debe romper la request
        logger.exception("Fallo revisando la sesión")
        db.rollback()
        return None, False
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


def _borrar_cookies(response) -> None:
    """
    Saca las dos cookies de sesión cuando la sesión ya no sirve.

    Sin esto el navegador sigue mandando un refresh muerto en cada request y
    el servidor sigue contestando 401, sin que nada explique por qué: la
    pantalla queda pidiendo login con las credenciales viejas todavía puestas.

    La del dispositivo no se toca: el equipo sigue siendo el mismo después de
    que se le venza la sesión a quien lo estaba usando.
    """
    response.delete_cookie(settings.JWT_COOKIE_NAME, path="/")
    response.delete_cookie(settings.JWT_REFRESH_COOKIE_NAME, path="/")


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
