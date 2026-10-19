"""
Endpoints de Reportes de Productividad (`/api/v1/reportes/productividad/...`).

Reportes globales (sin aislamiento por dispositivo) con permiso de REPORTES
ver, por rango de fechas (`fecha_desde`/`fecha_hasta`, por defecto del
inicio del mes a hoy: `rango_de_fechas`). Cada uno con su `/exportar` a
Excel con los mismos filtros.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.filtros import rango_de_fechas
from app.core.permisos import Modulo, requiere_permiso
from app.reports import reportes_productividad_excel as excel
from app.reports.tabla_excel import respuesta_xlsx
from app.schemas import reportes_productividad as esquemas
from app.services import reportes_productividad as servicio
from app.services import stock as servicio_stock

router = APIRouter(prefix="/reportes/productividad", tags=["reportes-productividad"])

@router.get(
    "/centro-distribucion", response_model=esquemas.ReporteProductividadCD,
    summary="Reporte: productividad del Centro de Distribución",
)
def centro_distribucion(
    rango: tuple[date, date] = Depends(rango_de_fechas),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.REPORTES, "ver")),
):
    """Por usuario: variantes vendibles dadas de alta y remitos enviados desde el CD."""
    return servicio.centro_distribucion(db, *rango)


@router.get(
    "/centro-distribucion/exportar", response_class=Response,
    summary="Exportar a Excel: productividad del Centro de Distribución",
)
def centro_distribucion_exportar(
    rango: tuple[date, date] = Depends(rango_de_fechas),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.REPORTES, "ver")),
):
    return respuesta_xlsx(
        excel.xls_centro_distribucion(servicio.centro_distribucion(db, *rango)),
        "productividad-centro-distribucion",
    )


@router.get(
    "/vendedores", response_model=esquemas.ReporteProductividadVendedores,
    summary="Reporte: productividad de vendedores",
)
def vendedores(
    rango: tuple[date, date] = Depends(rango_de_fechas),
    punto_de_venta_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.REPORTES, "ver")),
):
    """Por usuario: ventas confirmadas, señas y cambios confirmados."""
    datos = servicio.vendedores(db, *rango, punto_de_venta_id)
    return {**datos, "opciones_locales": servicio_stock.opciones_locales(db)}


@router.get(
    "/vendedores/exportar", response_class=Response,
    summary="Exportar a Excel: productividad de vendedores",
)
def vendedores_exportar(
    rango: tuple[date, date] = Depends(rango_de_fechas),
    punto_de_venta_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.REPORTES, "ver")),
):
    return respuesta_xlsx(
        excel.xls_vendedores(servicio.vendedores(db, *rango, punto_de_venta_id)),
        "productividad-vendedores",
    )
