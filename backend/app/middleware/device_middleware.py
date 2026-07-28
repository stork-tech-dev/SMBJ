"""
Middleware de identificación de dispositivos.

En cada request de navegación deja disponible `request.state.device` y,
cuando el dispositivo es nuevo o se recuperó por fingerprint, agrega la
cookie `device_uuid` a la response.

Se saltea en las rutas de infraestructura (estáticos, health, docs): no
tiene sentido crear un dispositivo por cada healthcheck de Docker.
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.database import SessionLocal
from app.core.utils import ip_de_request
from app.services.device_service import DeviceService
from config import settings

logger = logging.getLogger(__name__)

# Prefijos que no participan de la identificación en el middleware.
#
# `/api` se excluye a propósito: esos endpoints identifican con la sesión
# del request vía Depends(get_current_device). Si el middleware también los
# procesara, se crearían dos dispositivos en la primera request sin cookie
# (uno el middleware, otro la dependency). El middleware queda para las
# páginas HTML, donde deja request.state.device listo para usar.
PREFIJOS_EXCLUIDOS = (
    "/api",
    "/static",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon",
)


class DeviceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.device = None

        if not settings.DEVICE_MIDDLEWARE_ENABLED or _excluida(request.url.path):
            return await call_next(request)

        uuid_cookie = request.cookies.get(settings.DEVICE_COOKIE_NAME)
        fingerprint = request.headers.get(settings.DEVICE_FINGERPRINT_HEADER)
        ip = ip_de_request(request)

        set_cookie_uuid = None
        db = SessionLocal()
        try:
            servicio = DeviceService(db)
            dispositivo, set_cookie = servicio.identificar_dispositivo(uuid_cookie, fingerprint, ip)
            db.commit()
            # Se guardan datos simples, no el objeto ORM: la sesión se cierra
            # acá y el objeto quedaría desligado.
            request.state.device = _snapshot_device(dispositivo)
            if set_cookie:
                set_cookie_uuid = str(dispositivo.uuid)
        except Exception:  # noqa: BLE001 - la identificación nunca debe romper la request
            db.rollback()
            logger.exception("Fallo identificando el dispositivo")
        finally:
            db.close()

        response = await call_next(request)

        if set_cookie_uuid is not None:
            _setear_cookie(response, set_cookie_uuid)

        return response


def _excluida(path: str) -> bool:
    return any(path.startswith(prefijo) for prefijo in PREFIJOS_EXCLUIDOS)


def _setear_cookie(response, uuid: str) -> None:
    response.set_cookie(
        settings.DEVICE_COOKIE_NAME,
        uuid,
        max_age=settings.DEVICE_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def _snapshot_device(dispositivo) -> dict:
    """Datos del dispositivo que quedan en request.state, ya desligados del ORM."""
    return {
        "id": dispositivo.id,
        "uuid": str(dispositivo.uuid),
        "punto_de_venta_id": dispositivo.punto_de_venta_id,
        "activo": dispositivo.activo,
        "descripcion": dispositivo.descripcion,
    }
