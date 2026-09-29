"""
Endpoints de "Ajustes" (`/api/v1/ajustes`): los parámetros globales del
negocio. Exclusivos de la Cuenta Maestra, para leer y para editar: son
reglas que cambian precios, descuentos, puntos y plazos de todo el sistema.

La doble confirmación es de la pantalla; la API es el contrato y cualquier
cliente que la llame queda igual validado y auditado por el service.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permisos import requiere_cuenta_maestra
from app.core.utils import ip_de_request
from app.schemas.configuracion import AjustesEditar, AjustesResponse
from app.services import configuracion as servicio
from app.services.roles import NoEncontrado, ReglaDeNegocio

router = APIRouter(prefix="/ajustes", tags=["ajustes"])


def _respuesta(db: Session) -> AjustesResponse:
    return AjustesResponse(
        **servicio.ajustes(db), porcentajes_descuento=servicio.porcentajes_descuento(db)
    )


@router.get("", response_model=AjustesResponse, summary="Parámetros globales")
def obtener(
    db: Session = Depends(get_db),
    _=Depends(requiere_cuenta_maestra),
):
    return _respuesta(db)


@router.patch("", response_model=AjustesResponse, summary="Editar parámetros globales")
def editar(
    datos: AjustesEditar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_cuenta_maestra),
):
    """
    Aplica solo los campos enviados que cambiaron, en una sola auditoría
    (`configuracion.ajustes`) con el antes y el después. Rige para lo que
    se opere desde ahora: lo ya registrado guardó su valor en su momento.
    """
    try:
        servicio.actualizar_ajustes(
            db, autor.id, datos.model_dump(exclude_unset=True),
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReglaDeNegocio as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.commit()
    return _respuesta(db)
