"""
Endpoint público de identificación de dispositivos.

No requiere autenticación de usuario: identifica el celular por su cookie
o fingerprint y crea uno nuevo (inactivo) si hace falta.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.device_deps import get_current_device
from app.models.dispositivo import Dispositivo
from app.schemas.dispositivo import DispositivoMeResponse

router = APIRouter(prefix="/dispositivos", tags=["dispositivos"])


@router.get("/me", response_model=DispositivoMeResponse, summary="Dispositivo actual")
def me(dispositivo: Dispositivo | None = Depends(get_current_device)):
    """
    Devuelve el dispositivo asociado a esta request, según la cookie o el
    header X-Device-Fingerprint.

    Ya NO da de alta: el alta ocurre solo en el login. Un equipo donde
    nadie se autenticó todavía no está registrado, y eso es un 404 — si
    este endpoint creara, cualquiera podría llenar la tabla llamándolo.
    """
    if dispositivo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispositivo no registrado",
        )
    return dispositivo
