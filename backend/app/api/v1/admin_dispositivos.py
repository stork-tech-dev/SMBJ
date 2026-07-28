"""
Administración de dispositivos (Cuenta Maestra y Dueño).

Se gestiona bajo el módulo DISPOSITIVOS: leer requiere `ver`, editar y
cambiar estado requieren `editar`.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permisos import Modulo, requiere_permiso
from app.core.utils import ip_de_request
from app.schemas.dispositivo import DispositivoEditar, DispositivoResponse
from app.services.device_service import DeviceService
from app.services.roles import NoEncontrado, ReglaDeNegocio

router = APIRouter(prefix="/admin/dispositivos", tags=["dispositivos-admin"])


def _404(exc):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _409(exc):
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("", response_model=list[DispositivoResponse], summary="Listado de dispositivos")
def listar(
    descripcion: str | None = Query(default=None),
    punto_de_venta_id: int | None = Query(default=None),
    activo: bool | None = Query(default=None),
    acceso_desde: date | None = Query(default=None),
    acceso_hasta: date | None = Query(default=None),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.DISPOSITIVOS, "ver")),
):
    return DeviceService(db).listar(
        descripcion=descripcion,
        punto_de_venta_id=punto_de_venta_id,
        activo=activo,
        acceso_desde=acceso_desde,
        acceso_hasta=acceso_hasta,
    )


@router.get("/{device_id}", response_model=DispositivoResponse, summary="Detalle")
def detalle(
    device_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.DISPOSITIVOS, "ver")),
):
    try:
        return DeviceService(db).obtener(device_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc


@router.put("/{device_id}", response_model=DispositivoResponse, summary="Editar")
def editar(
    device_id: int,
    datos: DispositivoEditar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.DISPOSITIVOS, "editar")),
):
    """
    Edita descripción, local, observaciones y estado. `uuid` y `fingerprint`
    no son editables: no forman parte del schema.
    """
    # Distingue "no enviaron el local" de "lo pusieron en NULL": solo se
    # toca la asignación si el campo vino en el body.
    asignar_local = "punto_de_venta_id" in datos.model_fields_set
    try:
        dispositivo = DeviceService(db).actualizar(
            device_id,
            usuario_id=autor.id,
            ip=ip_de_request(request),
            descripcion=datos.descripcion,
            punto_de_venta_id=datos.punto_de_venta_id,
            observaciones=datos.observaciones,
            activo=datos.activo,
            asignar_local=asignar_local,
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return dispositivo


@router.patch("/{device_id}/activar", response_model=DispositivoResponse, summary="Activar")
def activar(
    device_id: int,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.DISPOSITIVOS, "editar")),
):
    try:
        dispositivo = DeviceService(db).reactivar(device_id, autor.id, ip_de_request(request))
    except NoEncontrado as exc:
        raise _404(exc) from exc

    db.commit()
    return dispositivo


@router.patch("/{device_id}/desactivar", response_model=DispositivoResponse, summary="Desactivar")
def desactivar(
    device_id: int,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.DISPOSITIVOS, "editar")),
):
    try:
        dispositivo = DeviceService(db).desactivar(device_id, autor.id, ip_de_request(request))
    except NoEncontrado as exc:
        raise _404(exc) from exc

    db.commit()
    return dispositivo
