"""
Endpoints de las operaciones de caja (sesión 09): retiros de efectivo,
novedades de caja, retiros de mercadería de empleadas y cobros de joyero.

Las cuatro se registran desde el celular del local, sobre el turno abierto de
ESE local: el punto de venta sale del dispositivo (`get_active_device`), nunca
del cuerpo del request, y además pasa por `DeviceScope.exigir` para que un
vendedor no opere sobre otro local.

Un router por operación —cada una tiene su prefijo—, en un solo archivo
porque comparten los mismos helpers.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.device_deps import get_active_device
from app.core.device_scope import DeviceScope, get_device_scope
from app.core.permisos import Modulo, Recurso, requiere_permiso
from app.core.utils import ip_de_request
from app.schemas.comunes import RespuestaPaginada
from app.schemas.operaciones_caja import (
    CobroJoyeroRequest,
    CobroJoyeroResponse,
    ConceptoNovedadResponse,
    CotizacionRetiroResponse,
    EfectivoDisponibleResponse,
    EmpleadaResumen,
    MedioCobroResponse,
    NovedadCajaRequest,
    NovedadCajaResponse,
    ReporteRetirosMercaderiaResponse,
    RetiroEfectivoRequest,
    RetiroEfectivoResponse,
    RetiroMercaderiaRequest,
    RetiroMercaderiaResponse,
)
from app.services import cobros_joyero as servicio_joyero
from app.services import novedades_caja as servicio_novedades
from app.services import retiros as servicio_retiros
from app.services import retiros_mercaderia as servicio_mercaderia
from app.services import stock as servicio_stock
from app.services.roles import NoEncontrado, ReglaDeNegocio

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _404(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _409(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _local(dispositivo, scope: DeviceScope) -> int:
    """El local del celular desde el que se opera, validado contra el scope."""
    scope.exigir(dispositivo.punto_de_venta_id)
    return dispositivo.punto_de_venta_id


def _filtro_local(scope: DeviceScope, pedido: int | None) -> int | None:
    """En los historiales, un vendedor solo ve su local."""
    return scope.punto_de_venta_id if scope.restringido else pedido


# ============================================================================
# RETIROS DE EFECTIVO
# ============================================================================

retiros_router = APIRouter(prefix="/retiros-efectivo", tags=["operaciones-caja"])


@retiros_router.get(
    "/disponible",
    response_model=EfectivoDisponibleResponse,
    summary="Efectivo disponible en la caja del turno abierto",
)
def efectivo_disponible(
    db: Session = Depends(get_db),
    dispositivo=Depends(get_active_device),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.CAJA, "ver")),
):
    """Declarado antes del POST por claridad; no choca con ninguna ruta con id."""
    try:
        turno_id, disponible = servicio_retiros.efectivo_disponible(
            db, _local(dispositivo, scope)
        )
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc
    return EfectivoDisponibleResponse(turno_id=turno_id, disponible=disponible)


@retiros_router.post(
    "",
    response_model=RetiroEfectivoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un retiro de efectivo",
)
def registrar_retiro(
    datos: RetiroEfectivoRequest,
    request: Request,
    db: Session = Depends(get_db),
    dispositivo=Depends(get_active_device),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.CAJA, "crear", Recurso.CAJA_RETIRO)),
):
    """
    Valida el monto contra el efectivo disponible y después el código de
    quien retira. Un código incorrecto devuelve 403 con un mensaje genérico,
    pero el intento queda auditado igual (se commitea antes de responder).
    """
    try:
        retiro = servicio_retiros.registrar_retiro(
            db,
            autor,
            punto_de_venta_id=_local(dispositivo, scope),
            monto=datos.monto,
            codigo=datos.codigo,
            ip_origen=ip_de_request(request),
        )
    except servicio_retiros.CodigoInvalido as exc:
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ReglaDeNegocio as exc:
        db.rollback()
        raise _409(exc) from exc

    db.commit()
    db.refresh(retiro)
    return RetiroEfectivoResponse.de(retiro)


@retiros_router.get(
    "", response_model=RespuestaPaginada[RetiroEfectivoResponse], summary="Historial"
)
def listar_retiros(
    turno_id: int | None = Query(default=None),
    punto_de_venta_id: int | None = Query(default=None),
    usuario_id: int | None = Query(default=None),
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=10, ge=1, le=200),
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.CAJA, "ver")),
):
    filas, total = servicio_retiros.listar_retiros(
        db,
        turno_id=turno_id,
        punto_de_venta_id=_filtro_local(scope, punto_de_venta_id),
        usuario_id=usuario_id,
        desde=desde,
        hasta=hasta,
        pagina=pagina,
        tamano=tamano,
    )
    return RespuestaPaginada[RetiroEfectivoResponse](
        total=total, pagina=pagina, tamano=tamano,
        resultados=[RetiroEfectivoResponse.de(r) for r in filas],
    )


# ============================================================================
# NOVEDADES DE CAJA
# ============================================================================

novedades_router = APIRouter(prefix="/novedades-caja", tags=["operaciones-caja"])


@novedades_router.get(
    "/conceptos",
    response_model=list[ConceptoNovedadResponse],
    summary="Conceptos activos para cargar una novedad",
)
def conceptos_activos(
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.CAJA, "ver")),
):
    """
    Existe aparte del ABM de `/configuracion/conceptos-novedad` porque ese
    pide permiso de Configuración, que la vendedora no tiene.
    """
    return [
        ConceptoNovedadResponse(id=c.id, nombre=c.nombre, tipo=c.tipo.value, activo=c.activo)
        for c in servicio_novedades.listar_conceptos(db, activo=True)
    ]


@novedades_router.post(
    "",
    response_model=NovedadCajaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar una novedad de caja",
)
def registrar_novedad(
    datos: NovedadCajaRequest,
    request: Request,
    db: Session = Depends(get_db),
    dispositivo=Depends(get_active_device),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.CAJA, "crear")),
):
    """El tipo (entrada/salida) lo pone el concepto: no viaja en el request."""
    try:
        novedad = servicio_novedades.registrar_novedad(
            db,
            autor,
            punto_de_venta_id=_local(dispositivo, scope),
            concepto_id=datos.concepto_id,
            monto=datos.monto,
            autorizador_id=datos.autorizador_id,
            notas=datos.notas,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    db.refresh(novedad)
    return NovedadCajaResponse.de(novedad)


@novedades_router.get(
    "", response_model=RespuestaPaginada[NovedadCajaResponse], summary="Historial"
)
def listar_novedades(
    turno_id: int | None = Query(default=None),
    punto_de_venta_id: int | None = Query(default=None),
    concepto_id: int | None = Query(default=None),
    autorizador_id: int | None = Query(default=None),
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=10, ge=1, le=200),
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.CAJA, "ver")),
):
    filas, total = servicio_novedades.listar_novedades(
        db,
        turno_id=turno_id,
        punto_de_venta_id=_filtro_local(scope, punto_de_venta_id),
        concepto_id=concepto_id,
        autorizador_id=autorizador_id,
        desde=desde,
        hasta=hasta,
        pagina=pagina,
        tamano=tamano,
    )
    return RespuestaPaginada[NovedadCajaResponse](
        total=total, pagina=pagina, tamano=tamano,
        resultados=[NovedadCajaResponse.de(n) for n in filas],
    )


# ============================================================================
# RETIROS DE MERCADERÍA DE EMPLEADAS
# ============================================================================

mercaderia_router = APIRouter(prefix="/retiros-mercaderia", tags=["operaciones-caja"])


@mercaderia_router.get(
    "/buscar-empleada",
    response_model=list[EmpleadaResumen],
    summary="Buscar una empleada de esta empresa por usuario o nombre",
)
def buscar_empleada(
    q: str = Query(min_length=1),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.CAJA, "crear")),
):
    return servicio_mercaderia.buscar_empleadas(db, q)


@mercaderia_router.get(
    "/cotizar",
    response_model=CotizacionRetiroResponse,
    summary="Precio de lista y precio con descuento de empleada de un producto",
)
def cotizar(
    codigo: str = Query(min_length=1, description="Código de la etiqueta, con o sin dígito"),
    db: Session = Depends(get_db),
    dispositivo=Depends(get_active_device),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.CAJA, "crear")),
):
    from app.services.ventas import buscar_variante

    local = _local(dispositivo, scope)
    try:
        variante = buscar_variante(db, codigo)
        cotizacion = servicio_mercaderia.cotizar(db, variante)
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    descripcion = variante.producto.descripcion
    if variante.descripcion_sufijo:
        descripcion = f"{descripcion} — {variante.descripcion_sufijo}"
    return CotizacionRetiroResponse(
        variante_id=variante.id,
        codigo=variante.codigo_con_verificador,
        descripcion=descripcion,
        foto=variante.foto_url,
        precio_lista=cotizacion["precio_lista"],
        descuento=cotizacion["descuento"],
        precio_con_descuento=cotizacion["precio_con_descuento"],
        motivo_nombre=cotizacion["motivo"].nombre,
        stock=servicio_stock.cantidad_en(db, variante.id, local),
        stock_infinito=variante.producto.stock_infinito,
    )


@mercaderia_router.get(
    "/reporte",
    response_model=ReporteRetirosMercaderiaResponse,
    summary="Reporte: retiros de mercadería para liquidar sueldos",
)
def reporte(
    punto_de_venta_id: int | None = Query(default=None),
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=10, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.REPORTES, "ver")),
):
    """Reporte global (sin aislamiento por dispositivo), como el resto de Reportes."""
    filas, total = servicio_mercaderia.reporte(
        db, punto_de_venta_id=punto_de_venta_id, desde=desde, hasta=hasta,
        pagina=pagina, tamano=tamano,
    )
    return ReporteRetirosMercaderiaResponse(
        resultados=[RetiroMercaderiaResponse.de(r) for r in filas],
        total=total,
        pagina=pagina,
        tamano=tamano,
        opciones_locales=servicio_stock.opciones_locales(db),  # type: ignore[arg-type]
    )


@mercaderia_router.get(
    "/reporte/exportar",
    response_class=Response,
    summary="Exportar a Excel el reporte de retiros de mercadería",
)
def reporte_exportar(
    punto_de_venta_id: int | None = Query(default=None),
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.REPORTES, "ver")),
):
    from app.reports.retiros_mercaderia_excel import generar_xls_retiros_mercaderia

    filas, _total = servicio_mercaderia.reporte(
        db, punto_de_venta_id=punto_de_venta_id, desde=desde, hasta=hasta, tamano=None
    )
    return Response(
        content=generar_xls_retiros_mercaderia(filas),
        media_type=_XLSX,
        headers={"Content-Disposition": 'attachment; filename="retiros-de-mercaderia.xlsx"'},
    )


@mercaderia_router.post(
    "",
    response_model=RetiroMercaderiaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un retiro de mercadería",
)
def registrar_retiro_mercaderia(
    datos: RetiroMercaderiaRequest,
    request: Request,
    db: Session = Depends(get_db),
    dispositivo=Depends(get_active_device),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.CAJA, "crear")),
):
    try:
        retiro = servicio_mercaderia.registrar_retiro(
            db,
            autor,
            punto_de_venta_id=_local(dispositivo, scope),
            variante_id=datos.variante_id,
            empleada_usuario_id=datos.empleada_usuario_id,
            empleada_nombre=datos.empleada_nombre,
            empleada_dni=datos.empleada_dni,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    db.refresh(retiro)
    return RetiroMercaderiaResponse.de(retiro)


@mercaderia_router.get(
    "", response_model=RespuestaPaginada[RetiroMercaderiaResponse], summary="Historial"
)
def listar_retiros_mercaderia(
    punto_de_venta_id: int | None = Query(default=None),
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    empleada: str | None = Query(default=None),
    es_empresa_propia: bool | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=10, ge=1, le=200),
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.CAJA, "ver")),
):
    filas, total = servicio_mercaderia.listar_retiros(
        db,
        punto_de_venta_id=_filtro_local(scope, punto_de_venta_id),
        desde=desde,
        hasta=hasta,
        empleada=empleada,
        es_empresa_propia=es_empresa_propia,
        pagina=pagina,
        tamano=tamano,
    )
    return RespuestaPaginada[RetiroMercaderiaResponse](
        total=total, pagina=pagina, tamano=tamano,
        resultados=[RetiroMercaderiaResponse.de(r) for r in filas],
    )


# ============================================================================
# COBROS DE JOYERO
# ============================================================================

joyero_router = APIRouter(prefix="/cobros-joyero", tags=["operaciones-caja"])


@joyero_router.get(
    "/medios-de-pago",
    response_model=list[MedioCobroResponse],
    summary="Medios con los que se puede cobrar un arreglo",
)
def medios_de_pago(
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.CAJA, "ver")),
):
    """
    Los medios activos, sin la seña y sin planes de cuotas (un cobro de
    joyero es siempre en un pago). `es_efectivo` marca cuál cobra el precio
    en efectivo.
    """
    from app.services import medios_pago as servicio_medios
    from app.services.arqueo import medio_efectivo

    efectivo = medio_efectivo(db)
    return [
        MedioCobroResponse(
            id=m.id, nombre=m.nombre, es_efectivo=efectivo is not None and m.id == efectivo.id
        )
        for m in servicio_medios.medios_para_cobro_directo(db)
    ]


@joyero_router.post(
    "",
    response_model=CobroJoyeroResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un cobro de joyero",
)
def registrar_cobro(
    datos: CobroJoyeroRequest,
    request: Request,
    db: Session = Depends(get_db),
    dispositivo=Depends(get_active_device),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.CAJA, "crear")),
):
    """No acepta plan de cuotas: el request ni siquiera tiene el campo."""
    try:
        cobro = servicio_joyero.registrar_cobro(
            db,
            autor,
            punto_de_venta_id=_local(dispositivo, scope),
            medio_de_pago_id=datos.medio_de_pago_id,
            monto_efectivo=datos.monto_efectivo,
            monto_otros=datos.monto_otros,
            numero_reclamo=datos.numero_reclamo,
            notas=datos.notas,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    db.refresh(cobro)
    return CobroJoyeroResponse.de(cobro)


@joyero_router.get(
    "", response_model=RespuestaPaginada[CobroJoyeroResponse], summary="Historial"
)
def listar_cobros(
    turno_id: int | None = Query(default=None),
    punto_de_venta_id: int | None = Query(default=None),
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=10, ge=1, le=200),
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.CAJA, "ver")),
):
    filas, total = servicio_joyero.listar_cobros(
        db,
        turno_id=turno_id,
        punto_de_venta_id=_filtro_local(scope, punto_de_venta_id),
        desde=desde,
        hasta=hasta,
        pagina=pagina,
        tamano=tamano,
    )
    return RespuestaPaginada[CobroJoyeroResponse](
        total=total, pagina=pagina, tamano=tamano,
        resultados=[CobroJoyeroResponse.de(c) for c in filas],
    )
