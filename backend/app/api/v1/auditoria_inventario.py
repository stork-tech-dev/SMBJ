"""
Endpoints de la auditoría de inventario.

Contar y aprobar tienen permisos distintos, y ahí está el control: el que
cuenta no valida su propio conteo. Iniciar y cargar ítems va con el recurso
`stock.auditoria`; aprobar o rechazar, con `stock.auditoria_aprobar`, que
tiene el Dueño.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.device_scope import DeviceScope, get_device_scope
from app.core.permisos import Modulo, Recurso, requiere_permiso
from app.core.utils import ip_de_request
from app.schemas.auditoria_inventario import (
    AuditoriaIniciar,
    AuditoriaRechazar,
    AuditoriaResponse,
    AuditoriaResumen,
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
        default=None, pattern="^(en_curso|pendiente_aprobacion|aprobada|rechazada)$"
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
    "/{auditoria_id}/finalizar",
    response_model=AuditoriaResponse,
    summary="Cerrar el conteo y mandarlo a aprobación",
)
def finalizar(
    auditoria_id: int,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.STOCK, "crear", Recurso.STOCK_AUDITORIA)),
):
    """No mueve stock: solo cierra el conteo."""
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


@router.patch(
    "/{auditoria_id}/aprobar",
    response_model=AuditoriaResponse,
    summary="Aprobar: ajusta el stock",
)
def aprobar(
    auditoria_id: int,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(
        requiere_permiso(Modulo.STOCK, "editar", Recurso.STOCK_AUDITORIA_APROBAR)
    ),
):
    """
    Genera un movimiento `ajuste_auditoria` por cada código con diferencia
    distinta de cero y deja el stock igual a lo contado.

    Sin `get_device_scope`: aprueba el Dueño, que no está limitado por
    dispositivo. Es el control que separa a quien cuenta de quien corrige.
    """
    try:
        auditoria = servicio.aprobar(
            db, autor, auditoria_id, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return auditoria


@router.patch(
    "/{auditoria_id}/rechazar",
    response_model=AuditoriaResponse,
    summary="Rechazar: el stock queda como estaba",
)
def rechazar(
    auditoria_id: int,
    datos: AuditoriaRechazar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(
        requiere_permiso(Modulo.STOCK, "editar", Recurso.STOCK_AUDITORIA_APROBAR)
    ),
):
    """El conteo no se borra: queda con sus diferencias y el motivo."""
    try:
        auditoria = servicio.rechazar(
            db, autor, auditoria_id, notas=datos.notas, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return auditoria
