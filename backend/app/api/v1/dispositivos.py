"""
Endpoint público de identificación de dispositivos.

No requiere autenticación de usuario: identifica el celular por su cookie
o fingerprint y crea uno nuevo (inactivo) si hace falta.
"""

from fastapi import APIRouter, Depends

from app.core.device_deps import get_current_device
from app.models.dispositivo import Dispositivo
from app.schemas.dispositivo import DispositivoMeResponse

router = APIRouter(prefix="/dispositivos", tags=["dispositivos"])


@router.get("/me", response_model=DispositivoMeResponse, summary="Dispositivo actual")
def me(dispositivo: Dispositivo = Depends(get_current_device)):
    """
    Devuelve el dispositivo asociado a esta request (según la cookie), o
    crea uno nuevo inactivo si no existe. Lee el header X-Device-Fingerprint
    para recuperar la identidad cuando no hay cookie.
    """
    return dispositivo
