"""
Endpoints de compras a proveedores.

El flujo es: iniciar borrador → agregar ítems → cerrar. El stock y los
precios se actualizan recién al cerrar, en una sola transacción.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permisos import Modulo, requiere_permiso
from app.core.utils import ip_de_request
from app.schemas.comunes import RespuestaPaginada
from app.schemas.compras import (
    CompraIniciar,
    CompraItemAgregar,
    CompraItemModificar,
    CompraItemResponse,
    CompraResponse,
    CompraResumen,
    ConfirmacionPrecio,
)
from app.services import compras as servicio
from app.services.roles import NoEncontrado, ReglaDeNegocio

router = APIRouter(prefix="/compras", tags=["compras"])


def _404(exc):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _409(exc):
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ---------------------------------------------------------------------------
# Listado y consultas
# ---------------------------------------------------------------------------

@router.get("", response_model=RespuestaPaginada[CompraResumen], summary="Historial")
def listar(
    proveedor_id: int | None = Query(default=None),
    desde: datetime | None = Query(default=None),
    hasta: datetime | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.COMPRAS, "ver")),
):
    filas, total = servicio.listar_compras(
        db,
        proveedor_id=proveedor_id,
        desde=desde,
        hasta=hasta,
        pagina=pagina,
        tamano=tamano,
    )
    # Computar total_items para el resumen.
    resultados = []
    for c in filas:
        resumen = CompraResumen.model_validate(c)
        resumen.total_items = len(c.items)
        resultados.append(resumen)
    return RespuestaPaginada[CompraResumen](
        total=total, pagina=pagina, tamano=tamano, resultados=resultados,
    )


@router.get(
    "/borrador",
    response_model=CompraResponse | None,
    summary="Borrador activo del usuario",
)
def borrador_activo(
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.COMPRAS, "ver")),
):
    """Devuelve la compra en borrador del usuario actual, o null."""
    compra = servicio.obtener_borrador_activo(db, autor.id)
    if compra is None:
        return None
    resp = CompraResponse.model_validate(compra)
    resp.total_items = len(compra.items)
    return resp


@router.get(
    "/{compra_id}",
    response_model=CompraResponse,
    summary="Detalle con ítems",
)
def detalle(
    compra_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.COMPRAS, "ver")),
):
    try:
        compra = servicio.obtener_compra_completa(db, compra_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc
    resp = CompraResponse.model_validate(compra)
    resp.total_items = len(compra.items)
    return resp


# ---------------------------------------------------------------------------
# Operaciones
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=CompraResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Iniciar compra o retomar borrador",
)
def iniciar(
    datos: CompraIniciar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.COMPRAS, "crear")),
):
    try:
        compra = servicio.iniciar_compra(
            db, autor,
            proveedor_id=datos.proveedor_id,
            punto_de_venta_id=datos.punto_de_venta_id,
            fecha_compra=datos.fecha_compra,
            notas=datos.notas,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return servicio.obtener_compra_completa(db, compra.id)


@router.post(
    "/{compra_id}/items",
    response_model=CompraItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar ítem",
)
def agregar_item(
    compra_id: int,
    datos: CompraItemAgregar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.COMPRAS, "crear")),
):
    try:
        item, requiere_conf = servicio.agregar_item(
            db, autor,
            compra_id=compra_id,
            variante_id=datos.variante_id,
            cantidad=datos.cantidad,
            precio_usd=datos.precio_usd,
            es_producto_nuevo=datos.es_producto_nuevo,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    db.refresh(item)
    resp = CompraItemResponse.model_validate(item)
    resp.requiere_confirmacion_precio = requiere_conf
    return resp


@router.put(
    "/{compra_id}/items/{item_id}",
    response_model=CompraItemResponse,
    summary="Modificar cantidad o precio",
)
def modificar_item(
    compra_id: int,
    item_id: int,
    datos: CompraItemModificar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.COMPRAS, "editar")),
):
    try:
        item, requiere_conf = servicio.modificar_item(
            db, autor,
            compra_id=compra_id,
            item_id=item_id,
            cantidad=datos.cantidad,
            precio_usd=datos.precio_usd,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    db.refresh(item)
    resp = CompraItemResponse.model_validate(item)
    resp.requiere_confirmacion_precio = requiere_conf
    return resp


@router.delete(
    "/{compra_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Quitar ítem",
)
def quitar_item(
    compra_id: int,
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.COMPRAS, "editar")),
):
    try:
        servicio.quitar_item(
            db, autor,
            compra_id=compra_id,
            item_id=item_id,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()


@router.post(
    "/{compra_id}/items/{item_id}/confirmar-precio",
    response_model=CompraItemResponse,
    summary="Confirmar o rechazar cambio de precio >30%",
)
def confirmar_precio(
    compra_id: int,
    item_id: int,
    datos: ConfirmacionPrecio,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.COMPRAS, "editar")),
):
    try:
        item = servicio.confirmar_cambio_precio(
            db, autor,
            compra_item_id=item_id,
            confirmar=datos.confirmar,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    db.refresh(item)
    return CompraItemResponse.model_validate(item)


@router.post(
    "/{compra_id}/cerrar",
    response_model=CompraResponse,
    summary="Cerrar compra — actualiza stock y precios",
)
def cerrar(
    compra_id: int,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.COMPRAS, "crear")),
):
    try:
        compra = servicio.cerrar_compra(
            db, autor,
            compra_id=compra_id,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    compra = servicio.obtener_compra_completa(db, compra.id)
    resp = CompraResponse.model_validate(compra)
    resp.total_items = len(compra.items)
    return resp


@router.delete(
    "/{compra_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar borrador",
)
def eliminar(
    compra_id: int,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.COMPRAS, "eliminar")),
):
    try:
        servicio.eliminar_borrador(
            db, autor,
            compra_id=compra_id,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
