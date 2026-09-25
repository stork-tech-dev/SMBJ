"""
Endpoints de Reportes de Caja (`/api/v1/reportes/caja/...`).

Todos son reportes globales (sin aislamiento por dispositivo), piden
REPORTES ver y filtran por `fecha` (un día; NULL = hoy) y, salvo Señas, por
`punto_de_venta_id`. Cada uno tiene su `/exportar` a Excel con los mismos
filtros.

Seis de los siete comparten firma: se registran desde la tabla `_REPORTES`
en lugar de escribir doce funciones casi iguales (Principio 2). Señas va
aparte porque no tiene local y sí filtro de estado.
"""

from collections.abc import Callable
from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permisos import Modulo, requiere_permiso
from app.core.utils import ahora_db
from app.reports import reportes_caja_excel as excel
from app.schemas import reportes_caja as esquemas
from app.schemas.operaciones_caja import RetiroMercaderiaResponse
from app.services import reportes_caja as servicio
from app.services import stock as servicio_stock

router = APIRouter(prefix="/reportes/caja", tags=["reportes-caja"])

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _excel(contenido: bytes, archivo: str) -> Response:
    return Response(
        content=contenido,
        media_type=_XLSX,
        headers={"Content-Disposition": f'attachment; filename="{archivo}.xlsx"'},
    )


def _mercaderia_para_api(datos: dict) -> dict:
    """Los retiros salen del service como modelos: se pasan al schema de siempre."""
    for grupo in datos["empleadas"]:
        grupo["retiros"] = [RetiroMercaderiaResponse.de(r) for r in grupo["retiros"]]
    return datos


# slug, service, schema de respuesta, Excel, resumen para OpenAPI, ajuste de la respuesta
_REPORTES: list[tuple[str, Callable, type, Callable, str, Callable | None]] = [
    ("novedades", servicio.novedades, esquemas.ReporteNovedades,
     excel.xls_novedades, "Novedades de caja por turno", None),
    ("arqueos", servicio.arqueos, esquemas.ReporteArqueos,
     excel.xls_arqueos, "Arqueos: sistema vs contado", None),
    ("movimientos", servicio.movimientos, esquemas.ReporteMovimientos,
     excel.xls_movimientos, "Movimientos de caja por turno", None),
    ("retiros-efectivo", servicio.retiros_efectivo, esquemas.ReporteRetirosEfectivo,
     excel.xls_retiros_efectivo, "Retiros de efectivo", None),
    ("cobros-joyero", servicio.cobros_joyero, esquemas.ReporteCobrosJoyero,
     excel.xls_cobros_joyero, "Cobros de joyero", None),
    ("retiros-mercaderia", servicio.retiros_mercaderia, esquemas.ReporteRetirosMercaderiaCaja,
     excel.xls_retiros_mercaderia, "Retiros de mercadería por empleada", _mercaderia_para_api),
]


def _registrar(slug, funcion, esquema, a_excel, resumen, ajuste) -> None:
    """Da de alta `GET /{slug}` y `GET /{slug}/exportar` para un reporte."""

    def reporte(
        fecha: date | None = Query(default=None, description="Día; vacío = hoy"),
        punto_de_venta_id: int | None = Query(default=None),
        db: Session = Depends(get_db),
        _=Depends(requiere_permiso(Modulo.REPORTES, "ver")),
    ):
        datos = funcion(db, fecha or ahora_db().date(), punto_de_venta_id)
        if ajuste is not None:
            datos = ajuste(datos)
        return {**datos, "opciones_locales": servicio_stock.opciones_locales(db)}

    def exportar(
        fecha: date | None = Query(default=None),
        punto_de_venta_id: int | None = Query(default=None),
        db: Session = Depends(get_db),
        _=Depends(requiere_permiso(Modulo.REPORTES, "ver")),
    ):
        datos = funcion(db, fecha or ahora_db().date(), punto_de_venta_id)
        return _excel(a_excel(datos), slug)

    nombre = slug.replace("-", "_")
    router.add_api_route(
        f"/{slug}", reporte, methods=["GET"], response_model=esquema,
        summary=f"Reporte: {resumen}", name=f"reporte_caja_{nombre}",
    )
    router.add_api_route(
        f"/{slug}/exportar", exportar, methods=["GET"], response_class=Response,
        summary=f"Exportar a Excel: {resumen}", name=f"reporte_caja_{nombre}_exportar",
    )


for _reporte in _REPORTES:
    _registrar(*_reporte)


# --- Señas: sin local, con filtro de estado ---

_ESTADOS = "^(" + "|".join(servicio.ESTADOS_SENA) + ")$"


@router.get("/senas", response_model=esquemas.ReporteSenas, summary="Reporte: señas")
def reporte_senas(
    fecha: date | None = Query(default=None, description="Día de alta; vacío = hoy"),
    estado: str | None = Query(default=None, pattern=_ESTADOS),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.REPORTES, "ver")),
):
    """Señas dadas de alta ese día, con saldo, vencimiento y estado."""
    return servicio.senas(db, fecha or ahora_db().date(), estado)


@router.get("/senas/exportar", response_class=Response, summary="Exportar a Excel: señas")
def reporte_senas_exportar(
    fecha: date | None = Query(default=None),
    estado: str | None = Query(default=None, pattern=_ESTADOS),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.REPORTES, "ver")),
):
    return _excel(excel.xls_senas(servicio.senas(db, fecha or ahora_db().date(), estado)), "senas")
