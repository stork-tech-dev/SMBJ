"""
Endpoints del árbol de categorías.

Se gestionan bajo el módulo PRODUCTOS: la categoría no es una entidad
independiente, es la clasificación de los productos.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permisos import Modulo, requiere_permiso
from app.core.utils import ip_de_request
from app.schemas.categorias import (
    CategoriaCrear,
    CategoriaEditar,
    CategoriaMover,
    CategoriaNodo,
    CategoriaResponse,
)
from app.services import categorias as servicio
from app.services.roles import NoEncontrado, ReglaDeNegocio

router = APIRouter(prefix="/categorias", tags=["categorias"])


def _404(exc):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _409(exc):
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("", response_model=list[CategoriaResponse], summary="Listado plano")
def listar(
    nombre: str | None = Query(default=None),
    nivel: int | None = Query(default=None, ge=1, le=5),
    parent_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.PRODUCTOS, "ver")),
):
    """Filtros del Principio 5, resueltos en el backend."""
    return servicio.listar_categorias(db, nombre=nombre, nivel=nivel, parent_id=parent_id)


@router.get("/arbol", response_model=list[CategoriaNodo], summary="Árbol completo")
def arbol(
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.PRODUCTOS, "ver")),
):
    """
    El árbol entero en una sola llamada.

    Va antes de `/{categoria_id}` a propósito: si se declarara después,
    FastAPI intentaría interpretar "arbol" como un id.
    """
    return servicio.arbol(db)


@router.get("/{categoria_id}", response_model=CategoriaResponse, summary="Detalle")
def detalle(
    categoria_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.PRODUCTOS, "ver")),
):
    try:
        return servicio.obtener_categoria(db, categoria_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc


@router.post(
    "", response_model=CategoriaResponse, status_code=status.HTTP_201_CREATED, summary="Alta"
)
def crear(
    datos: CategoriaCrear,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PRODUCTOS, "crear")),
):
    try:
        categoria = servicio.crear_categoria(
            db,
            autor,
            nombre=datos.nombre,
            parent_id=datos.parent_id,
            orden=datos.orden,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return categoria


@router.put("/{categoria_id}", response_model=CategoriaResponse, summary="Editar")
def editar(
    categoria_id: int,
    datos: CategoriaEditar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PRODUCTOS, "editar")),
):
    try:
        categoria = servicio.editar_categoria(
            db,
            autor,
            categoria_id,
            nombre=datos.nombre,
            orden=datos.orden,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return categoria


@router.patch("/{categoria_id}/mover", response_model=CategoriaResponse, summary="Mover de padre")
def mover(
    categoria_id: int,
    datos: CategoriaMover,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PRODUCTOS, "editar")),
):
    """
    Endpoint propio y no parte de PUT: mover cambia el nivel de toda la
    descendencia y tiene sus propias validaciones (ciclos, profundidad).
    """
    try:
        categoria = servicio.mover_categoria(
            db,
            autor,
            categoria_id,
            nuevo_parent_id=datos.parent_id,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return categoria


@router.delete(
    "/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Eliminar"
)
def eliminar(
    categoria_id: int,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PRODUCTOS, "eliminar")),
):
    try:
        servicio.eliminar_categoria(db, autor, categoria_id, ip_origen=ip_de_request(request))
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
