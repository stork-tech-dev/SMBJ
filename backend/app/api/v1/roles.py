"""
Endpoints de roles. Todos exclusivos de la Cuenta Maestra.

El router solo traduce excepciones de los services a códigos HTTP: las
reglas de negocio viven en `/app/services/roles.py`.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permisos import requiere_cuenta_maestra
from app.core.utils import ip_de_request
from app.schemas.comunes import MensajeResponse
from app.schemas.permisos import ActualizarPermisosRequest, ModuloPermiso
from app.schemas.roles import RolCrear, RolEditar, RolEstado, RolListadoResponse, RolResponse
from app.services import permisos as servicio_permisos
from app.services import roles as servicio_roles

router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("", response_model=list[RolListadoResponse], summary="Listado de roles")
def listar(
    nombre: str | None = Query(default=None, description="Búsqueda parcial, sin distinguir mayúsculas"),
    activo: bool | None = Query(default=None),
    es_sistema: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    _=Depends(requiere_cuenta_maestra),
):
    filas = servicio_roles.listar_roles(db, nombre=nombre, activo=activo, es_sistema=es_sistema)
    return [
        RolListadoResponse(
            **RolResponse.model_validate(f["rol"]).model_dump(),
            cantidad_usuarios=f["cantidad_usuarios"],
        )
        for f in filas
    ]


@router.post("", response_model=RolResponse, status_code=status.HTTP_201_CREATED, summary="Crear rol")
def crear(
    datos: RolCrear,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_cuenta_maestra),
):
    """El rol nuevo arranca con todos los permisos en FALSE."""
    try:
        rol = servicio_roles.crear_rol(
            db, datos.nombre, datos.descripcion, autor.id, ip_de_request(request)
        )
    except servicio_roles.ReglaDeNegocio as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.commit()
    return rol


@router.put("/{rol_id}", response_model=RolResponse, summary="Editar rol")
def editar(
    rol_id: int,
    datos: RolEditar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_cuenta_maestra),
):
    """En los roles de sistema solo se puede cambiar la descripción."""
    try:
        rol = servicio_roles.editar_rol(
            db, rol_id, datos.nombre, datos.descripcion, autor.id, ip_de_request(request)
        )
    except servicio_roles.NoEncontrado as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except servicio_roles.ReglaDeNegocio as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.commit()
    return rol


@router.patch("/{rol_id}/estado", response_model=RolResponse, summary="Activar o desactivar rol")
def cambiar_estado(
    rol_id: int,
    datos: RolEstado,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_cuenta_maestra),
):
    try:
        rol = servicio_roles.cambiar_estado_rol(
            db, rol_id, datos.activo, autor.id, ip_de_request(request)
        )
    except servicio_roles.NoEncontrado as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except servicio_roles.ReglaDeNegocio as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.commit()
    return rol


@router.delete("/{rol_id}", response_model=MensajeResponse, summary="Eliminar rol")
def eliminar(
    rol_id: int,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_cuenta_maestra),
):
    """Solo roles no-sistema y sin usuarios asociados."""
    try:
        servicio_roles.eliminar_rol(db, rol_id, autor.id, ip_de_request(request))
    except servicio_roles.NoEncontrado as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except servicio_roles.ReglaDeNegocio as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.commit()
    return MensajeResponse(mensaje="Rol eliminado")


@router.get("/{rol_id}/permisos", response_model=list[ModuloPermiso], summary="Permisos del rol")
def obtener_permisos(
    rol_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_cuenta_maestra),
):
    """Árbol completo: todos los módulos con sus recursos específicos."""
    try:
        servicio_roles.obtener_rol(db, rol_id)
    except servicio_roles.NoEncontrado as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return servicio_permisos.arbol_de_rol(db, rol_id)


@router.put("/{rol_id}/permisos", response_model=list[ModuloPermiso], summary="Actualizar permisos del rol")
def actualizar_permisos(
    rol_id: int,
    datos: ActualizarPermisosRequest,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_cuenta_maestra),
):
    try:
        rol = servicio_roles.obtener_rol(db, rol_id)
        arbol = servicio_permisos.actualizar_permisos_rol(
            db,
            rol,
            [p.model_dump() for p in datos.permisos],
            autor.id,
            ip_de_request(request),
        )
    except servicio_roles.NoEncontrado as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    db.commit()
    return arbol
