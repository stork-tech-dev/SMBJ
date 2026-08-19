"""
Endpoints de remitos.

Los tres pasos del flujo tienen permisos distintos y no es casual: arma y
despacha el que tiene la mercadería (Distribución), confirma el que la
recibe (el local). Que sean el mismo permiso permitiría cerrar el circuito
sin que nadie del otro lado cuente nada.
"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.device_scope import DeviceScope, get_device_scope
from app.core.permisos import Modulo, Recurso, requiere_permiso
from app.core.utils import ip_de_request
from app.schemas.comunes import RespuestaPaginada
from app.schemas.remitos import (
    RemitoConfirmar,
    RemitoCrear,
    RemitoResponse,
    RemitoResumen,
)
from app.services import remitos as servicio
from app.services.roles import NoEncontrado, ReglaDeNegocio

router = APIRouter(prefix="/remitos", tags=["remitos"])


def _404(exc):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _409(exc):
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _403(exc):
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


def _exigir_visible(remito, scope: DeviceScope) -> None:
    """
    Un remito es visible desde sus dos puntas.

    Se controla acá y no en el service porque es una regla de LECTURA: el
    listado ya filtra, pero el detalle se pide por id y sin esto un vendedor
    podría leer el remito de otro local cambiando el número en la URL.
    """
    if scope.permite(remito.punto_venta_origen_id):
        return
    if scope.permite(remito.punto_venta_destino_id):
        return
    scope.exigir(remito.punto_venta_destino_id)


@router.get("", response_model=RespuestaPaginada[RemitoResumen], summary="Listado")
def listar(
    estado: str | None = Query(
        default=None, pattern="^(pendiente|en_camino|confirmado|con_diferencia)$"
    ),
    punto_venta_origen_id: int | None = Query(default=None),
    punto_venta_destino_id: int | None = Query(default=None),
    desde: datetime | None = Query(default=None),
    hasta: datetime | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.STOCK, "ver")),
):
    """Filtros del Principio 5, todos resueltos en el backend."""
    filas, total = servicio.listar_remitos(
        db,
        scope,
        estado=estado,
        punto_venta_origen_id=punto_venta_origen_id,
        punto_venta_destino_id=punto_venta_destino_id,
        desde=desde,
        hasta=hasta,
        pagina=pagina,
        tamano=tamano,
    )
    return RespuestaPaginada[RemitoResumen](
        total=total, pagina=pagina, tamano=tamano, resultados=filas
    )


@router.post(
    "",
    response_model=RemitoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Armar un envío",
)
def crear(
    datos: RemitoCrear,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.STOCK, "crear")),
):
    """
    Crea el remito en `pendiente` y descuenta el stock del origen en el acto.
    """
    try:
        remito = servicio.crear_remito(
            db,
            autor,
            scope,
            punto_venta_origen_id=datos.punto_venta_origen_id,
            punto_venta_destino_id=datos.punto_venta_destino_id,
            items=[i.model_dump() for i in datos.items],
            notas=datos.notas,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return servicio.obtener_remito(db, remito.id)


@router.get("/{remito_id}", response_model=RemitoResponse, summary="Detalle con ítems")
def detalle(
    remito_id: int,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.STOCK, "ver")),
):
    try:
        remito = servicio.obtener_remito(db, remito_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc

    _exigir_visible(remito, scope)
    return remito


@router.patch(
    "/{remito_id}/despachar",
    response_model=RemitoResponse,
    summary="Confirmar el despacho y generar el PDF",
)
def despachar(
    remito_id: int,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.STOCK, "crear")),
):
    """
    No mueve stock: ya se descontó al armar el envío. Lo que agrega es el PDF
    que viaja con la mercadería.
    """
    try:
        servicio.despachar(db, autor, scope, remito_id, ip_origen=ip_de_request(request))
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return servicio.obtener_remito(db, remito_id)


@router.patch(
    "/{remito_id}/confirmar",
    response_model=RemitoResponse,
    summary="Confirmar la recepción",
)
def confirmar(
    remito_id: int,
    datos: RemitoConfirmar,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(
        requiere_permiso(Modulo.STOCK, "editar", Recurso.STOCK_REMITO_RECEPCION)
    ),
):
    """
    El local cuenta lo que llegó y el stock entra a destino.

    Pide el número del remito —el impreso en el papel que viaja con la
    carga—: si no coincide, 403. Es la prueba de que la mercadería está ahí.
    """
    try:
        servicio.confirmar_recepcion(
            db,
            autor,
            scope,
            remito_id,
            numero_confirmacion=datos.numero_confirmacion,
            recibidos={i.variante_id: i.cantidad_recibida for i in datos.items},
            notas=datos.notas,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except servicio.CodigoIncorrecto as exc:
        raise _403(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return servicio.obtener_remito(db, remito_id)


@router.get(
    "/{remito_id}/pdf",
    response_class=FileResponse,
    summary="Descargar o reimprimir el PDF",
)
def pdf(
    remito_id: int,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.STOCK, "ver")),
):
    """
    Devuelve el PDF que se generó al despachar, sin rearmarlo: el papel que
    acompañó la carga tiene que poder reimprimirse igual meses después.

    Va por endpoint y no como link directo al `/static` para que respete el
    permiso y el aislamiento por dispositivo: el archivo servido en crudo
    sería legible por cualquiera que adivine el número.
    """
    try:
        remito = servicio.obtener_remito(db, remito_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc

    _exigir_visible(remito, scope)

    if not remito.pdf_url:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El remito {remito.numero} todavía no se despachó: no tiene PDF",
        )

    # La URL guardada es relativa a /static; el archivo vive en app/static.
    archivo = Path(__file__).resolve().parents[2] / "static" / Path(remito.pdf_url).relative_to(
        "/static"
    )
    if not archivo.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El archivo del remito no está en el disco del servidor",
        )

    return FileResponse(
        archivo, media_type="application/pdf", filename=f"{remito.numero}.pdf"
    )
