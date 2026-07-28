"""
Dependencies de FastAPI para dispositivos.

Se identifican con la sesión inyectada (respetan overrides de test) y
setean/renuevan la cookie en la response cuando corresponde. Sirven para
que cualquier endpoint futuro (stock, ventas) exija un dispositivo activo.
"""

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.utils import ip_de_request
from app.models.dispositivo import Dispositivo
from app.services.device_service import DeviceService
from config import settings


def get_current_device(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> Dispositivo:
    """
    Dispositivo actual según la cookie, sin importar si está activo.

    Si no hay cookie, lo crea (inactivo) o lo recupera por fingerprint, y
    escribe la cookie en la response — igual que el flujo del middleware,
    pero con la sesión del request para que sea testeable.
    """
    servicio = DeviceService(db)

    # Si el middleware ya identificó el dispositivo en esta request (páginas
    # HTML), se reutiliza cargándolo en la sesión del request, para no crear
    # un segundo dispositivo ni reescribir la cookie.
    snap = getattr(request.state, "device", None)
    if snap:
        existente = servicio.repo.get_by_uuid(snap["uuid"])
        if existente is not None:
            request.state.device = snap
            return existente

    uuid_cookie = request.cookies.get(settings.DEVICE_COOKIE_NAME)
    fingerprint = request.headers.get(settings.DEVICE_FINGERPRINT_HEADER)
    ip = ip_de_request(request)

    dispositivo, set_cookie = servicio.identificar_dispositivo(uuid_cookie, fingerprint, ip)
    db.commit()

    # Deja el dispositivo disponible como request.state.device también para
    # los endpoints de API (donde el middleware no corre).
    request.state.device = {
        "id": dispositivo.id,
        "uuid": str(dispositivo.uuid),
        "punto_de_venta_id": dispositivo.punto_de_venta_id,
        "activo": dispositivo.activo,
        "descripcion": dispositivo.descripcion,
    }

    if set_cookie:
        response.set_cookie(
            settings.DEVICE_COOKIE_NAME,
            str(dispositivo.uuid),
            max_age=settings.DEVICE_COOKIE_MAX_AGE,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite="lax",
            path="/",
        )

    return dispositivo


def get_active_device(dispositivo: Dispositivo = Depends(get_current_device)) -> Dispositivo:
    """
    Como el anterior, pero devuelve 403 si el dispositivo no está activo o
    no tiene un local asignado. Lo usarán los endpoints operativos.
    """
    if not dispositivo.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Dispositivo no activado"
        )
    if dispositivo.punto_de_venta_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Dispositivo sin local asignado"
        )
    return dispositivo
