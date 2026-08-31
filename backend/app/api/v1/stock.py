"""
Endpoints de stock: existencias, movimientos, mínimos y bajas.

Todos los de consulta llevan `Depends(get_device_scope)`: es la dependency
que limita a un vendedor al local de su dispositivo. Va acá y no como lógica
dentro de cada handler porque un endpoint que se olvide del filtro no falla
—simplemente deja ver todo—, y eso no se nota hasta que ya pasó.
"""

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.device_scope import DeviceScope, get_device_scope
from app.core.permisos import Modulo, Recurso, requiere_permiso
from app.core.utils import ip_de_request
from app.models.punto_de_venta import PuntoDeVenta
from app.models.stock import TipoMovimiento
from app.schemas.comunes import RespuestaPaginada
from app.schemas.stock import (
    BajaCrear,
    IngresoCrear,
    MotivoBajaCrear,
    MotivoBajaEditar,
    MotivoBajaResponse,
    MovimientoResponse,
    PuntoResumen,
    ResumenStock,
    StockMinimos,
    StockResponse,
)
from app.services import bajas_stock as servicio_bajas
from app.services import stock as servicio
from app.services.roles import NoEncontrado, ReglaDeNegocio

router = APIRouter(prefix="/stock", tags=["stock"])

_TIPOS = "|".join(t.value for t in TipoMovimiento)


def _404(exc):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _409(exc):
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("", response_model=RespuestaPaginada[StockResponse], summary="Stock actual")
def listar(
    punto_de_venta_id: int | None = Query(default=None),
    categoria_id: int | None = Query(default=None),
    proveedor_id: int | None = Query(default=None),
    busqueda: str | None = Query(
        default=None, description="Código de etiqueta, SKU o parte de la descripción"
    ),
    solo_bajo_minimo: bool = Query(default=False),
    incluir_sin_stock: bool = Query(default=True),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.STOCK, "ver")),
):
    """
    Filtros del Principio 5, todos resueltos en el backend.

    Un vendedor sin local asignado recibe la lista vacía, no un 403: tiene
    que poder abrir la pantalla y leer por qué no hay nada.
    """
    filas, total = servicio.listar_stock(
        db,
        scope,
        punto_de_venta_id=punto_de_venta_id,
        categoria_id=categoria_id,
        proveedor_id=proveedor_id,
        busqueda=busqueda,
        solo_bajo_minimo=solo_bajo_minimo,
        incluir_sin_stock=incluir_sin_stock,
        pagina=pagina,
        tamano=tamano,
    )
    return RespuestaPaginada[StockResponse](
        total=total, pagina=pagina, tamano=tamano, resultados=filas  # type: ignore[arg-type]
    )


@router.get("/alertas", response_model=list[StockResponse], summary="Lo que hay que reponer")
def alertas(
    limite: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.STOCK, "ver")),
):
    """
    Filas con la cantidad en su mínimo o por debajo, las más urgentes
    primero. Alimenta el panel del dashboard.

    Va declarado ANTES de cualquier ruta con parámetro de camino, igual que
    en el módulo de productos.
    """
    return servicio.alertas(db, scope, limite=limite)


@router.get(
    "/ubicaciones",
    response_model=list[PuntoResumen],
    summary="Ubicaciones sobre las que se puede operar",
)
def ubicaciones(
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.STOCK, "ver")),
):
    """
    Los puntos de venta que las pantallas de stock pueden ofrecer.

    Existe en vez de reusar `GET /puntos-de-venta` porque ese pide permiso de
    CONFIGURACIÓN, que un vendedor no tiene: sin esto no podría ni iniciar un
    conteo en su propio local. No expone nada nuevo — el nombre y el código
    de la ubicación ya viajan en cada fila de stock.

    Viene ya acotado por el dispositivo: para un vendedor la lista tiene
    exactamente su local, así que la pantalla no puede ofrecerle otro.

    Solo las activas: no se manda ni se cuenta mercadería en una ubicación
    dada de baja.
    """
    consulta = select(PuntoDeVenta).where(PuntoDeVenta.activo.is_(True))

    if scope.restringido:
        if scope.sin_asignacion:
            return []
        consulta = consulta.where(PuntoDeVenta.id == scope.punto_de_venta_id)

    return list(db.execute(consulta.order_by(PuntoDeVenta.codigo)).scalars().all())


@router.get("/resumen", response_model=ResumenStock, summary="Números del encabezado")
def resumen(
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.STOCK, "ver")),
):
    """Cuántas filas, cuántas unidades, cuántas alertas y cuánto vale."""
    filas, total = servicio.listar_stock(db, scope, tamano=200)
    return ResumenStock(
        filas=total,
        unidades=sum(f.cantidad for f in filas),
        alertas=len(servicio.alertas(db, scope, limite=500)),
        valorizado=Decimal(servicio.valorizado(db, scope)),
    )


@router.get(
    "/movimientos",
    response_model=RespuestaPaginada[MovimientoResponse],
    summary="Historial de movimientos",
)
def movimientos(
    variante_id: int | None = Query(default=None),
    punto_de_venta_id: int | None = Query(default=None),
    tipo: str | None = Query(default=None, pattern=f"^({_TIPOS})$"),
    desde: datetime | None = Query(default=None),
    hasta: datetime | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.STOCK, "ver")),
):
    """
    Por qué el stock es el que es. Un vendedor ve los movimientos que tocan
    su local por cualquiera de las dos puntas: lo que le llegó y lo que salió.
    """
    filas, total = servicio.listar_movimientos(
        db,
        scope,
        variante_id=variante_id,
        punto_de_venta_id=punto_de_venta_id,
        tipo=tipo,
        desde=desde,
        hasta=hasta,
        pagina=pagina,
        tamano=tamano,
    )
    return RespuestaPaginada[MovimientoResponse](
        total=total, pagina=pagina, tamano=tamano, resultados=filas  # type: ignore[arg-type]
    )


# ============================================================================
# MOTIVOS DE BAJA
# ============================================================================
#
# Van antes de los endpoints de escritura de stock porque comparten prefijo:
# `/stock/motivos-baja` tiene que resolverse como ruta propia.


@router.get(
    "/motivos-baja", response_model=list[MotivoBajaResponse], summary="Motivos de baja"
)
def listar_motivos(
    activo: bool | None = Query(default=None),
    nombre: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.STOCK, "ver")),
):
    return servicio_bajas.listar_motivos(db, activo=activo, nombre=nombre)


@router.post(
    "/motivos-baja",
    response_model=MotivoBajaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Alta de motivo de baja",
)
def crear_motivo(
    datos: MotivoBajaCrear,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(
        requiere_permiso(Modulo.STOCK, "editar", Recurso.STOCK_MOTIVOS_BAJA)
    ),
):
    """El catálogo lo mantienen la Cuenta Maestra y el Dueño."""
    try:
        motivo = servicio_bajas.crear_motivo(
            db, autor, datos.nombre, ip_origen=ip_de_request(request)
        )
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return motivo


@router.put(
    "/motivos-baja/{motivo_id}",
    response_model=MotivoBajaResponse,
    summary="Editar un motivo de baja",
)
def editar_motivo(
    motivo_id: int,
    datos: MotivoBajaEditar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(
        requiere_permiso(Modulo.STOCK, "editar", Recurso.STOCK_MOTIVOS_BAJA)
    ),
):
    """
    Se desactiva, no se borra: los movimientos ya registrados apuntan al
    motivo, y borrarlo dejaría sin explicación bajas que ya pasaron.
    """
    try:
        motivo = servicio_bajas.editar_motivo(
            db,
            autor,
            motivo_id,
            nombre=datos.nombre,
            activo=datos.activo,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return motivo


# ============================================================================
# MOVIMIENTOS QUE SE REGISTRAN A MANO
# ============================================================================


@router.post(
    "/ingresos",
    response_model=MovimientoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingreso de mercadería del proveedor",
)
def crear_ingreso(
    datos: IngresoCrear,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.STOCK, "crear")),
):
    """
    La puerta de entrada de la mercadería al sistema.

    No está en la lista de endpoints del prompt del módulo, pero sin esto no
    hay forma de que el stock exista: los remitos mueven lo que ya está y las
    bajas lo sacan. Cuando el módulo de compras lo genere desde una orden,
    este endpoint sigue sirviendo para lo que entra sin orden previa.
    """
    scope.exigir(datos.punto_de_venta_id)
    try:
        movimiento = servicio.aplicar_movimiento(
            db,
            autor,
            tipo=TipoMovimiento.INGRESO_PROVEEDOR,
            variante_id=datos.variante_id,
            cantidad=datos.cantidad,
            punto_venta_destino_id=datos.punto_de_venta_id,
            notas=datos.notas,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return movimiento


@router.post(
    "/bajas",
    response_model=MovimientoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar una baja",
)
def crear_baja(
    datos: BajaCrear,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.STOCK, "crear", Recurso.STOCK_BAJA)),
):
    """
    Rotura, robo, muestra o merma. Un vendedor solo puede dar de baja
    mercadería de su propio local.
    """
    try:
        movimiento = servicio_bajas.registrar_baja(
            db,
            autor,
            scope,
            variante_id=datos.variante_id,
            punto_de_venta_id=datos.punto_de_venta_id,
            cantidad=datos.cantidad,
            motivo_baja_id=datos.motivo_baja_id,
            notas=datos.notas,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return movimiento


@router.put(
    "/minimos/{variante_id}/{punto_de_venta_id}",
    response_model=StockResponse,
    summary="Definir los mínimos de reposición",
)
def definir_minimos(
    variante_id: int,
    punto_de_venta_id: int,
    datos: StockMinimos,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.STOCK, "editar")),
):
    """
    Lo único que se edita a mano en la tabla de stock.

    Los ids van en la URL y no en el cuerpo porque identifican la fila —que
    puede no existir todavía: se crea en cero al definirle un mínimo.
    """
    scope.exigir(punto_de_venta_id)
    try:
        fila = servicio.definir_minimos(
            db,
            autor,
            variante_id,
            punto_de_venta_id,
            stock_minimo_cd=datos.stock_minimo_cd,
            stock_minimo_local=datos.stock_minimo_local,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return fila
