"""
Endpoints de la auditoría de inventario.

Iniciar, contar y cerrar van con el recurso `stock.auditoria`. Al cerrar
se aplican automáticamente los ajustes de stock.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.device_scope import DeviceScope, get_device_scope
from app.core.permisos import Modulo, Recurso, requiere_permiso
from app.core.utils import ip_de_request
from app.schemas.auditoria_inventario import (
    AuditoriaIniciar,
    AuditoriaResponse,
    AuditoriaResumen,
    ItemEditar,
    ItemsCargar,
)
from app.schemas.comunes import RespuestaPaginada
from app.services import auditoria_inventario as servicio
from app.services.roles import NoEncontrado, ReglaDeNegocio

router = APIRouter(prefix="/auditorias-inventario", tags=["auditoría de inventario"])


def _404(exc):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _409(exc):
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("", response_model=RespuestaPaginada[AuditoriaResumen], summary="Listado")
def listar(
    estado: str | None = Query(
        default=None, pattern="^(en_curso|cerrada)$"
    ),
    punto_de_venta_id: int | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.STOCK, "ver")),
):
    filas, total = servicio.listar(
        db,
        scope,
        estado=estado,
        punto_de_venta_id=punto_de_venta_id,
        pagina=pagina,
        tamano=tamano,
    )
    return RespuestaPaginada[AuditoriaResumen](
        total=total, pagina=pagina, tamano=tamano, resultados=filas
    )


@router.post(
    "",
    response_model=AuditoriaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Iniciar un conteo",
)
def iniciar(
    datos: AuditoriaIniciar,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.STOCK, "crear", Recurso.STOCK_AUDITORIA)),
):
    """Abre el conteo. Todavía no hay nada contado ni nada ajustado."""
    try:
        auditoria = servicio.iniciar(
            db,
            autor,
            scope,
            punto_de_venta_id=datos.punto_de_venta_id,
            filtro_categoria_id=datos.filtro_categoria_id,
            notas=datos.notas,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return servicio.obtener(db, auditoria.id)


@router.get(
    "/{auditoria_id}", response_model=AuditoriaResponse, summary="Detalle con diferencias"
)
def detalle(
    auditoria_id: int,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.STOCK, "ver")),
):
    try:
        auditoria = servicio.obtener(db, auditoria_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc

    # Un vendedor no puede leer el conteo de otro local cambiando el id de
    # la URL: el listado ya filtra, pero el detalle se pide por número.
    scope.exigir(auditoria.punto_de_venta_id)
    return auditoria


@router.get(
    "/{auditoria_id}/pdf",
    response_class=Response,
    summary="Descargar la planilla en PDF",
)
def pdf(
    auditoria_id: int,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.STOCK, "ver")),
):
    """
    La planilla de lo contado, para archivar o firmar en papel.

    Mismo permiso y mismo aislamiento que el detalle: quien puede ver la
    auditoría en pantalla puede imprimirla, y nadie puede bajarse la de otro
    local cambiando el id de la URL.

    Se arma en el momento y no se guarda: lo que muestra ya está congelado en
    `auditoria_items` (ver `reports/auditoria_pdf.py`).
    """
    from app.reports.auditoria_pdf import generar_pdf_auditoria

    try:
        auditoria = servicio.obtener(db, auditoria_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc

    scope.exigir(auditoria.punto_de_venta_id)

    return Response(
        content=generar_pdf_auditoria(db, auditoria),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="auditoria-{auditoria.id}.pdf"'
        },
    )


@router.get(
    "/{auditoria_id}/xls",
    response_class=Response,
    summary="Descargar la planilla en Excel",
)
def xls(
    auditoria_id: int,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.STOCK, "ver")),
):
    """Mismo criterio que el PDF: quien puede ver, puede exportar."""
    from app.reports.auditoria_pdf import generar_xls_auditoria

    try:
        auditoria = servicio.obtener(db, auditoria_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc

    scope.exigir(auditoria.punto_de_venta_id)

    return Response(
        content=generar_xls_auditoria(auditoria),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="auditoria-{auditoria.id}.xlsx"'
        },
    )


@router.post(
    "/{auditoria_id}/items",
    response_model=AuditoriaResponse,
    summary="Registrar lo contado",
)
def cargar_items(
    auditoria_id: int,
    datos: ItemsCargar,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.STOCK, "crear", Recurso.STOCK_AUDITORIA)),
):
    """
    Carga o corrige cantidades contadas. Repetir un código sobreescribe:
    contar dos veces un estante es normal y vale el último conteo.
    """
    try:
        auditoria = servicio.registrar_items(
            db,
            autor,
            scope,
            auditoria_id,
            [i.model_dump() for i in datos.items],
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return auditoria


@router.patch(
    "/{auditoria_id}/items/{item_id}",
    response_model=AuditoriaResponse,
    summary="Corregir la cantidad contada de un ítem",
)
def editar_item(
    auditoria_id: int,
    item_id: int,
    datos: ItemEditar,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.STOCK, "crear", Recurso.STOCK_AUDITORIA)),
):
    """Corrige un ítem ya cargado sin tener que eliminarlo y recargarlo."""
    try:
        auditoria = servicio.editar_item(
            db, autor, scope, auditoria_id, item_id,
            cantidad_contada=datos.cantidad_contada,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return auditoria


@router.delete(
    "/{auditoria_id}/items/{item_id}",
    response_model=AuditoriaResponse,
    summary="Eliminar un ítem del conteo",
)
def eliminar_item(
    auditoria_id: int,
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.STOCK, "crear", Recurso.STOCK_AUDITORIA)),
):
    """Quita un ítem cargado por error. Solo mientras el conteo está en curso."""
    try:
        auditoria = servicio.eliminar_item(
            db, autor, scope, auditoria_id, item_id,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return auditoria


@router.patch(
    "/{auditoria_id}/finalizar",
    response_model=AuditoriaResponse,
    summary="Cerrar el conteo y ajustar el stock",
)
def finalizar(
    auditoria_id: int,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.STOCK, "crear", Recurso.STOCK_AUDITORIA)),
):
    """Cierra el conteo y genera los ajustes de stock por cada diferencia."""
    try:
        auditoria = servicio.finalizar(
            db, autor, scope, auditoria_id, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return auditoria
