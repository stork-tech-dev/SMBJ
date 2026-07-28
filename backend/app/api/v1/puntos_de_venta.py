"""
Endpoints de puntos de venta.

Se gestionan bajo el módulo CONFIGURACION, que en el seed solo tienen la
Cuenta Maestra y el Dueño — exactamente los roles que pide el spec.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permisos import Modulo, requiere_permiso
from app.core.utils import ip_de_request
from app.models.punto_de_venta import TipoPuntoVenta
from app.schemas.puntos_de_venta import (
    PuntoCrear,
    PuntoEditar,
    PuntoEstado,
    PuntoResponse,
)
from app.services import puntos_de_venta as servicio
from app.services.roles import NoEncontrado, ReglaDeNegocio

router = APIRouter(prefix="/puntos-de-venta", tags=["puntos-de-venta"])


def _404(exc):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _409(exc):
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("", response_model=list[PuntoResponse], summary="Listado de puntos de venta")
def listar(
    nombre: str | None = Query(default=None),
    tipo: str | None = Query(default=None, pattern="^(cd|local|online)$"),
    activo: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.CONFIGURACION, "ver")),
):
    return servicio.listar_puntos(db, nombre=nombre, tipo=tipo, activo=activo)


@router.post(
    "", response_model=PuntoResponse, status_code=status.HTTP_201_CREATED, summary="Alta"
)
def crear(
    datos: PuntoCrear,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CONFIGURACION, "crear")),
):
    try:
        punto = servicio.crear_punto(
            db,
            autor,
            nombre=datos.nombre,
            tipo=TipoPuntoVenta(datos.tipo),
            codigo_confirmacion=datos.codigo_confirmacion,
            ip_origen=ip_de_request(request),
        )
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return punto


@router.put("/{punto_id}", response_model=PuntoResponse, summary="Editar")
def editar(
    punto_id: int,
    datos: PuntoEditar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CONFIGURACION, "editar")),
):
    try:
        punto = servicio.editar_punto(
            db,
            autor,
            punto_id,
            nombre=datos.nombre,
            tipo=TipoPuntoVenta(datos.tipo) if datos.tipo else None,
            codigo_confirmacion=datos.codigo_confirmacion,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return punto


@router.patch("/{punto_id}/estado", response_model=PuntoResponse, summary="Activar o desactivar")
def cambiar_estado(
    punto_id: int,
    datos: PuntoEstado,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CONFIGURACION, "editar")),
):
    try:
        punto = servicio.cambiar_estado(
            db, autor, punto_id, datos.activo, confirmar=datos.confirmar, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return punto
