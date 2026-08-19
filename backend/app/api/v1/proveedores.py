"""
Endpoints de proveedores y valor del dólar.

Acceso (vía resolver_permiso sobre el módulo PROVEEDORES):
  - CRUD y estado          → permiso ver/crear/editar del módulo
  - Cambio de dólar        → permiso editar del módulo
  - Masivo e importación   → recurso DOLAR_CAMBIO_MASIVO
  - Reactivar inhabilitado → regla extra en el service (CM o Dueño)
"""

from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permisos import Modulo, Recurso, requiere_permiso
from app.core.utils import ip_de_request
from app.models.proveedor import EstadoProveedor
from app.schemas.comunes import MensajeResponse
from app.schemas.proveedores import (
    CambioDolarRequest,
    CambioMasivoPreviewItem,
    CambioMasivoRequest,
    CambioMasivoResultItem,
    DolarHistorialResponse,
    ImportarResultado,
    ProveedorCrear,
    ProveedorEditar,
    ProveedorEstado,
    ProveedorResponse,
)
from app.services import proveedores as servicio
from app.services.roles import NoEncontrado, ReglaDeNegocio

router = APIRouter(prefix="/proveedores", tags=["proveedores"])


def _404(exc):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _409(exc):
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _403(exc):
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


# ============================================================================
# Cambio masivo e importación — rutas fijas ANTES que /{id}, para que no las
# capture el parámetro de path.
# ============================================================================


@router.post(
    "/dolar/masivo/preview",
    response_model=list[CambioMasivoPreviewItem],
    summary="Previsualizar cambio masivo",
)
def preview_masivo(
    datos: CambioMasivoRequest,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.PROVEEDORES, "editar", Recurso.DOLAR_CAMBIO_MASIVO)),
):
    """Calcula el resultado sin aplicarlo: alimenta la tabla de preview."""
    try:
        return servicio.preview_masivo(db, datos.proveedor_ids, datos.modalidad, datos.valor)
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc


@router.post(
    "/dolar/masivo",
    response_model=list[CambioMasivoResultItem],
    summary="Aplicar cambio masivo del dólar",
)
def cambio_masivo(
    datos: CambioMasivoRequest,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PROVEEDORES, "editar", Recurso.DOLAR_CAMBIO_MASIVO)),
):
    """Un registro de historial y de auditoría por proveedor afectado."""
    try:
        resultado = servicio.cambio_masivo(
            db, autor, datos.proveedor_ids, datos.modalidad, datos.valor, ip_de_request(request)
        )
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return resultado


@router.get(
    "/dolar/plantilla",
    response_class=Response,
    summary="Descargar la plantilla Excel con el dólar actual de cada proveedor",
)
def descargar_plantilla_dolar(
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.PROVEEDORES, "editar", Recurso.DOLAR_CAMBIO_MASIVO)),
):
    """
    Excel listo para editar y volver a subir por `/dolar/importar`.

    Mismo permiso que la importación: es la puerta de entrada al mismo
    circuito, y quien no puede aplicar el cambio tampoco necesita el archivo
    con los valores de todos los proveedores.

    Va declarado ANTES de `/{proveedor_id}`, igual que el resto de las rutas
    de `/dolar`: si no, FastAPI leería "dolar" como un id.
    """
    from datetime import date

    contenido = servicio.generar_plantilla_dolar(db)
    nombre = f"dolar-proveedores-{date.today().isoformat()}.xlsx"

    return Response(
        content=contenido,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@router.post(
    "/dolar/importar", response_model=ImportarResultado, summary="Importar dólar desde Excel"
)
async def importar_dolar(
    request: Request,
    archivo: UploadFile = File(..., description=".xlsx con columnas proveedor_id y dolar_nuevo"),
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PROVEEDORES, "editar", Recurso.DOLAR_CAMBIO_MASIVO)),
):
    """
    Todo-o-nada: si alguna fila tiene error no se aplica nada y se devuelve
    la lista de errores. El status sigue siendo 200: el "error" es un
    resultado esperado de la validación, no una falla de la request.
    """
    contenido = await archivo.read()
    try:
        resultado = servicio.importar_dolar(db, autor, contenido, ip_de_request(request))
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    if resultado["errores"]:
        db.rollback()
    else:
        db.commit()
    return resultado


# ============================================================================
# CRUD
# ============================================================================


@router.get("", response_model=list[ProveedorResponse], summary="Listado de proveedores")
def listar(
    nombre: str | None = Query(default=None),
    email: str | None = Query(default=None),
    telefono: str | None = Query(default=None),
    estado: str | None = Query(default=None, pattern="^(activo|desactivado|inhabilitado)$"),
    dolar_desde: Decimal | None = Query(default=None),
    dolar_hasta: Decimal | None = Query(default=None),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.PROVEEDORES, "ver")),
):
    return servicio.listar_proveedores(
        db,
        nombre=nombre,
        email=email,
        telefono=telefono,
        estado=estado,
        dolar_desde=dolar_desde,
        dolar_hasta=dolar_hasta,
    )


@router.get("/{proveedor_id}", response_model=ProveedorResponse, summary="Ficha de proveedor")
def detalle(
    proveedor_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.PROVEEDORES, "ver")),
):
    try:
        return servicio.obtener_proveedor(db, proveedor_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc


@router.post(
    "", response_model=ProveedorResponse, status_code=status.HTTP_201_CREATED, summary="Alta"
)
def crear(
    datos: ProveedorCrear,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PROVEEDORES, "crear")),
):
    try:
        proveedor = servicio.crear_proveedor(
            db,
            autor,
            nombre=datos.nombre,
            pais=datos.pais,
            dolar_actual=datos.dolar_actual,
            provincia=datos.provincia,
            telefono=datos.telefono,
            email=datos.email,
            notas=datos.notas,
            ip_origen=ip_de_request(request),
        )
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return proveedor


@router.put("/{proveedor_id}", response_model=ProveedorResponse, summary="Editar")
def editar(
    proveedor_id: int,
    datos: ProveedorEditar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PROVEEDORES, "editar")),
):
    try:
        proveedor = servicio.editar_proveedor(
            db,
            autor,
            proveedor_id,
            nombre=datos.nombre,
            pais=datos.pais,
            provincia=datos.provincia,
            telefono=datos.telefono,
            email=datos.email,
            notas=datos.notas,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return proveedor


@router.patch(
    "/{proveedor_id}/estado", response_model=ProveedorResponse, summary="Cambiar estado"
)
def cambiar_estado(
    proveedor_id: int,
    datos: ProveedorEstado,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PROVEEDORES, "editar")),
):
    """Baja lógica (desactivar/inhabilitar) o reactivación. Nunca DELETE físico."""
    try:
        proveedor = servicio.cambiar_estado(
            db,
            autor,
            proveedor_id,
            EstadoProveedor(datos.estado),
            confirmar_con_productos=datos.confirmar_con_productos,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except servicio.SinPermiso as exc:
        raise _403(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return proveedor


# ============================================================================
# Valor del dólar (individual + historial)
# ============================================================================


@router.patch(
    "/{proveedor_id}/dolar", response_model=ProveedorResponse, summary="Actualizar dólar"
)
def cambiar_dolar(
    proveedor_id: int,
    datos: CambioDolarRequest,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PROVEEDORES, "editar")),
):
    try:
        proveedor = servicio.cambiar_dolar(
            db, autor, proveedor_id, datos.valor_nuevo, ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return proveedor


@router.get(
    "/{proveedor_id}/dolar/historial",
    response_model=list[DolarHistorialResponse],
    summary="Historial del dólar",
)
def historial_dolar(
    proveedor_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.PROVEEDORES, "ver")),
):
    try:
        return servicio.historial_dolar(db, proveedor_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc
