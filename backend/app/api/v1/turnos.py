"""
Endpoints de turnos de caja, retiros de efectivo y arqueo.

El device scope limita qué local puede operar el usuario:
un Vendedor solo puede abrir/cerrar el turno de su local asignado.
Un Supervisor puede ver el arqueo de cualquier local.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.device_scope import DeviceScope, get_device_scope
from app.core.permisos import Modulo, Recurso, requiere_permiso
from app.core.utils import ip_de_request
from app.models.turno import Arqueo, RetiroEfectivo, Turno, TurnoVendedora
from app.schemas.comunes import RespuestaPaginada
from app.schemas.turnos import (
    ArqueoEsperadoResponse,
    ArqueoItemEsperado,
    ArqueoItemResponse,
    ArqueoRegistrarRequest,
    ArqueoResponse,
    RetiroRequest,
    RetiroResponse,
    TurnoAbrirRequest,
    TurnoResponse,
    TurnoResumen,
    VendedoraEnTurno,
)
from app.services import arqueo as srv_arqueo
from app.services import turnos as srv_turnos
from app.services.roles import NoEncontrado, ReglaDeNegocio

router = APIRouter(prefix="/turnos", tags=["turnos"])


def _404(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _409(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _punto_id(scope: DeviceScope) -> int:
    """El local del dispositivo actual. Lanza 400 si el scope no tiene local."""
    if not scope.punto_de_venta_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este dispositivo no tiene un local asignado.",
        )
    return scope.punto_de_venta_id


def _turno_to_response(turno) -> TurnoResponse:
    return TurnoResponse(
        id=turno.id,
        punto_de_venta_id=turno.punto_de_venta_id,
        punto_de_venta_nombre=turno.punto_de_venta.nombre,
        estado=turno.estado.value if hasattr(turno.estado, "value") else turno.estado,
        efectivo_apertura=turno.efectivo_apertura,
        fecha_apertura=turno.fecha_apertura,
        fecha_cierre=turno.fecha_cierre,
        notas=turno.notas,
        usuario_apertura_nombre=turno.usuario_apertura.nombre,
        usuario_cierre_nombre=turno.usuario_cierre.nombre if turno.usuario_cierre else None,
        vendedoras=[
            VendedoraEnTurno(id=tv.usuario_id, nombre=tv.usuario.nombre, ingreso=tv.ingreso)
            for tv in turno.vendedoras
        ],
    )


def _turno_to_resumen(turno) -> TurnoResumen:
    return TurnoResumen(
        id=turno.id,
        punto_de_venta_id=turno.punto_de_venta_id,
        punto_de_venta_nombre=turno.punto_de_venta.nombre if turno.punto_de_venta else "",
        estado=turno.estado.value if hasattr(turno.estado, "value") else turno.estado,
        fecha_apertura=turno.fecha_apertura,
        fecha_cierre=turno.fecha_cierre,
        usuario_apertura_nombre=turno.usuario_apertura.nombre if turno.usuario_apertura else "",
    )


def _arqueo_to_response(arqueo) -> ArqueoResponse:
    return ArqueoResponse(
        id=arqueo.id,
        turno_id=arqueo.turno_id,
        total_esperado=arqueo.total_esperado,
        total_declarado=arqueo.total_declarado,
        diferencia=arqueo.diferencia,
        notificacion_enviada=arqueo.notificacion_enviada,
        created_at=arqueo.created_at,
        items=[
            ArqueoItemResponse(
                id=i.id,
                medio_de_pago_id=i.medio_de_pago_id,
                grupo_terminal=i.grupo_terminal,
                monto_esperado=i.monto_esperado,
                monto_declarado=i.monto_declarado,
                diferencia=i.diferencia,
                es_informativo=i.es_informativo,
            )
            for i in arqueo.items
        ],
    )


# ── Turno activo ────────────────────────────────────────────────────────────


@router.get("/activo", response_model=TurnoResponse | None)
def turno_activo(
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.CAJA, "ver")),
    db: Session = Depends(get_db),
):
    """Retorna el turno abierto del local actual, o null si no hay."""
    punto_id = _punto_id(scope)
    turno = srv_turnos.obtener_turno_activo(punto_id, db)
    if not turno:
        return None
    return _turno_to_response(turno)


@router.post("/abrir", response_model=TurnoResponse, status_code=status.HTTP_201_CREATED)
def abrir_turno(
    body: TurnoAbrirRequest,
    request: Request,
    scope: DeviceScope = Depends(get_device_scope),
    usuario=Depends(requiere_permiso(Modulo.CAJA, "ver")),
    db: Session = Depends(get_db),
):
    """Abre un nuevo turno en el local del dispositivo actual."""
    punto_id = _punto_id(scope)
    try:
        turno = srv_turnos.abrir_turno(
            punto_de_venta_id=punto_id,
            usuario_id=usuario.id,
            efectivo_apertura=float(body.efectivo_apertura),
            notas=body.notas,
            db=db,
            ip=ip_de_request(request),
        )
    except ReglaDeNegocio as e:
        raise _409(e)
    db.commit()
    db.refresh(turno)
    return _turno_to_response(turno)


@router.post("/unirse", response_model=TurnoResponse)
def unirse_a_turno(
    request: Request,
    scope: DeviceScope = Depends(get_device_scope),
    usuario=Depends(requiere_permiso(Modulo.CAJA, "ver")),
    db: Session = Depends(get_db),
):
    """Une al usuario autenticado al turno activo del local."""
    punto_id = _punto_id(scope)
    try:
        turno = srv_turnos.unirse_a_turno(punto_id, usuario.id, db, ip=ip_de_request(request))
    except ReglaDeNegocio as e:
        raise _409(e)
    db.commit()
    db.refresh(turno)
    return _turno_to_response(turno)


@router.get("", response_model=RespuestaPaginada[TurnoResumen])
def listar_turnos(
    pagina: int = Query(1, ge=1),
    tamano: int = Query(20, ge=1, le=100),
    punto_de_venta_id: int | None = Query(None),
    estado: str | None = Query(None),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.CAJA, "ver")),
    db: Session = Depends(get_db),
):
    """Lista turnos con paginación. Vendedores solo ven su local."""
    # Vendedor solo ve su local
    filtro_punto = punto_de_venta_id
    if scope.restringido:
        filtro_punto = scope.punto_de_venta_id

    filas, total = srv_turnos.listar_turnos(
        db=db,
        punto_de_venta_id=filtro_punto,
        estado=estado,
        pagina=pagina,
        tamano=tamano,
    )
    return RespuestaPaginada[TurnoResumen](  # type: ignore[arg-type]
        resultados=[_turno_to_resumen(t) for t in filas],
        total=total,
        pagina=pagina,
        tamano=tamano,
    )


@router.get("/{turno_id}", response_model=TurnoResponse)
def ver_turno(
    turno_id: int,
    _=Depends(requiere_permiso(Modulo.CAJA, "ver")),
    db: Session = Depends(get_db),
):
    """Devuelve el detalle completo de un turno, con vendedoras y datos de usuario."""
    turno = db.execute(
        select(Turno)
        .where(Turno.id == turno_id)
        .options(
            joinedload(Turno.vendedoras).joinedload(TurnoVendedora.usuario),
            joinedload(Turno.usuario_apertura),
            joinedload(Turno.usuario_cierre),
            joinedload(Turno.punto_de_venta),
        )
    ).unique().scalar_one_or_none()
    if not turno:
        raise _404(NoEncontrado("Turno no encontrado"))
    return _turno_to_response(turno)


# ── Retiros ────────────────────────────────────────────────────────────────


@router.post(
    "/{turno_id}/retiros",
    response_model=RetiroResponse,
    status_code=status.HTTP_201_CREATED,
)
def registrar_retiro(
    turno_id: int,
    body: RetiroRequest,
    request: Request,
    usuario=Depends(requiere_permiso(Modulo.CAJA, "crear", recurso=Recurso.CAJA_RETIRO)),
    db: Session = Depends(get_db),
):
    """Registra un retiro de efectivo del turno. Requiere permiso CAJA_RETIRO."""
    try:
        retiro = srv_turnos.registrar_retiro(
            turno_id=turno_id,
            monto=float(body.monto),
            motivo=body.motivo,
            autorizado_por_id=body.autorizado_por_id,
            realizado_por_id=usuario.id,
            db=db,
            ip=ip_de_request(request),
        )
    except (NoEncontrado, ReglaDeNegocio) as e:
        code = status.HTTP_404_NOT_FOUND if isinstance(e, NoEncontrado) else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=str(e))
    db.commit()
    db.refresh(retiro)
    return RetiroResponse(
        id=retiro.id,
        turno_id=retiro.turno_id,
        monto=retiro.monto,
        motivo=retiro.motivo,
        autorizado_por_id=retiro.autorizado_por,
        realizado_por_id=retiro.realizado_por,
        timestamp=retiro.timestamp,
    )


@router.get("/{turno_id}/retiros", response_model=list[RetiroResponse])
def listar_retiros(
    turno_id: int,
    _=Depends(requiere_permiso(Modulo.CAJA, "ver")),
    db: Session = Depends(get_db),
):
    """Lista todos los retiros de efectivo de un turno."""
    retiros = db.execute(
        select(RetiroEfectivo).where(RetiroEfectivo.turno_id == turno_id)
    ).scalars().all()
    return [
        RetiroResponse(
            id=r.id,
            turno_id=r.turno_id,
            monto=r.monto,
            motivo=r.motivo,
            autorizado_por_id=r.autorizado_por,
            realizado_por_id=r.realizado_por,
            timestamp=r.timestamp,
        )
        for r in retiros
    ]


# ── Arqueo ─────────────────────────────────────────────────────────────────


@router.get("/{turno_id}/arqueo/esperado", response_model=ArqueoEsperadoResponse)
def arqueo_esperado(
    turno_id: int,
    _=Depends(requiere_permiso(Modulo.CAJA, "crear", recurso=Recurso.CAJA_ARQUEO)),
    db: Session = Depends(get_db),
):
    """Calcula el arqueo esperado del turno según los pagos registrados."""
    try:
        resultado = srv_arqueo.calcular_esperado(turno_id, db)
    except NoEncontrado as e:
        raise _404(e)
    return ArqueoEsperadoResponse(
        turno_id=resultado["turno_id"],
        items=[ArqueoItemEsperado(**i) for i in resultado["items"]],
        total_esperado=resultado["total_esperado"],
    )


@router.post(
    "/{turno_id}/arqueo",
    response_model=ArqueoResponse,
    status_code=status.HTTP_201_CREATED,
)
def registrar_arqueo(
    turno_id: int,
    body: ArqueoRegistrarRequest,
    request: Request,
    usuario=Depends(requiere_permiso(Modulo.CAJA, "crear", recurso=Recurso.CAJA_ARQUEO)),
    db: Session = Depends(get_db),
):
    """Registra el arqueo declarado por el usuario al cerrar el turno."""
    try:
        arqueo = srv_arqueo.registrar_arqueo(
            turno_id=turno_id,
            items_declarados=[i.model_dump() for i in body.items],
            total_declarado=body.total_declarado,
            usuario_id=usuario.id,
            db=db,
            ip=ip_de_request(request),
        )
    except NoEncontrado as e:
        raise _404(e)
    except ReglaDeNegocio as e:
        raise _409(e)
    db.commit()
    db.refresh(arqueo)
    return _arqueo_to_response(arqueo)


@router.get("/{turno_id}/arqueo", response_model=ArqueoResponse)
def ver_arqueo(
    turno_id: int,
    _=Depends(requiere_permiso(Modulo.CAJA, "crear", recurso=Recurso.CAJA_ARQUEO)),
    db: Session = Depends(get_db),
):
    """Devuelve el arqueo registrado para el turno, con todos sus ítems."""
    arqueo = db.execute(
        select(Arqueo)
        .where(Arqueo.turno_id == turno_id)
        .options(joinedload(Arqueo.items))
    ).unique().scalar_one_or_none()
    if not arqueo:
        raise _404(NoEncontrado("Arqueo no encontrado para este turno"))
    return _arqueo_to_response(arqueo)
