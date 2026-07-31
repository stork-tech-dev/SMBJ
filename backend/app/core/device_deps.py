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
) -> Dispositivo | None:
    """
    Dispositivo actual según la cookie, sin importar si está activo, o
    None si este equipo todavía no está registrado.

    NO da de alta: el alta ocurre solo en el login. Si esta dependency
    creara, seguiría siendo posible generar filas llamando directamente
    a /api/v1/dispositivos/me, que es público — el mismo agujero que se
    cerró en el middleware, por otra puerta.
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
    user_agent = request.headers.get("user-agent")

    dispositivo, set_cookie = servicio.identificar_dispositivo(
        uuid_cookie, fingerprint, ip, user_agent
    )
    db.commit()

    if dispositivo is None:
        return None

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


def get_active_device(
    dispositivo: Dispositivo | None = Depends(get_current_device),
) -> Dispositivo:
    """
    Como el anterior, pero devuelve 403 si el dispositivo no está activo,
    no tiene un local asignado o directamente no está registrado. Lo usarán
    los endpoints operativos.
    """
    if dispositivo is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dispositivo no registrado: hay que iniciar sesión en él",
        )
    if not dispositivo.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Dispositivo no activado"
        )
    if dispositivo.punto_de_venta_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Dispositivo sin local asignado"
        )
    return dispositivo
