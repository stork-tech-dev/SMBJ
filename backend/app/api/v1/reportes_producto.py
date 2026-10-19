"""
Endpoints del reporte "Historial del Producto"
(`/api/v1/reportes/historial-producto/...`).

Reporte global (sin aislamiento por dispositivo) con permiso de REPORTES
ver. Trae su propia búsqueda de productos porque un perfil con solo
Reportes no puede pedirle nada a `/api/v1/productos` (mismo criterio que
`opciones_locales` en los otros reportes).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permisos import Modulo, requiere_permiso
from app.schemas import reportes_producto as esquemas
from app.services import reportes_producto as servicio
from app.services.roles import NoEncontrado

router = APIRouter(prefix="/reportes/historial-producto", tags=["reportes-producto"])


def _historial(db: Session, producto_id: int) -> dict:
    try:
        return servicio.historial_producto(db, producto_id)
    except NoEncontrado as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/buscar", response_model=list[esquemas.ProductoEncontrado],
    summary="Buscar un producto para el historial",
)
def buscar(
    busqueda: str = Query(default="", description="SKU, descripción o código de etiqueta"),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.REPORTES, "ver")),
):
    return servicio.buscar_productos(db, busqueda)


@router.get(
    "/{producto_id}", response_model=esquemas.HistorialProducto,
    summary="Historial del producto: carga, movimientos, ventas, fallas y precios",
)
def historial(
    producto_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.REPORTES, "ver")),
):
    return _historial(db, producto_id)


@router.get(
    "/{producto_id}/pdf",
    summary="Historial del producto en PDF",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def historial_pdf(
    producto_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.REPORTES, "ver")),
):
    """
    Varias tablas distintas en un mismo documento: por eso PDF y no Excel,
    que serviría para una sola.
    """
    from app.reports.historial_producto_pdf import generar_pdf_historial

    datos = _historial(db, producto_id)
    return Response(
        content=generar_pdf_historial(db, datos),
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'attachment; filename="historial-{datos["ficha"]["sku"]}.pdf"'
        },
    )
