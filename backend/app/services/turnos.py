"""
Servicio de turnos de caja.

Reglas de negocio críticas:
  - Solo puede haber un turno abierto por punto de venta en el día.
  - Si hay un turno del día anterior sin cerrar → bloqueo duro en toda
    operación del local hasta que se cierre (verificar_bloqueo_turno).
  - Cualquier vendedora puede abrir, cerrar o sumarse — no solo la que abrió.
  - Los retiros de efectivo solo los autoriza quien tiene rol dueño; esto
    se verifica en el endpoint (requiere_permiso CAJA_RETIRO).
"""

from datetime import datetime, date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.utils import ahora_db
from app.models.turno import EstadoTurno, RetiroEfectivo, Turno, TurnoVendedora
from app.services.roles import NoEncontrado, ReglaDeNegocio


def _turno_abierto_hoy(punto_de_venta_id: int, hoy: date, db: Session) -> Turno | None:
    """Retorna el turno abierto de hoy para el local, o None."""
    stmt = (
        select(Turno)
        .where(
            Turno.punto_de_venta_id == punto_de_venta_id,
            Turno.estado == EstadoTurno.ABIERTO,
            func.date(Turno.fecha_apertura) == hoy,
        )
        .options(
            joinedload(Turno.vendedoras).joinedload(TurnoVendedora.usuario),
            joinedload(Turno.usuario_apertura),
            joinedload(Turno.punto_de_venta),
        )
    )
    return db.execute(stmt).unique().scalar_one_or_none()


def _turno_abierto_ayer(punto_de_venta_id: int, hoy: date, db: Session) -> Turno | None:
    """Retorna un turno abierto de un día anterior para el local, o None."""
    stmt = select(Turno).where(
        Turno.punto_de_venta_id == punto_de_venta_id,
        Turno.estado == EstadoTurno.ABIERTO,
        func.date(Turno.fecha_apertura) < hoy,
    )
    return db.execute(stmt).scalar_one_or_none()


def verificar_bloqueo_turno(punto_de_venta_id: int, db: Session) -> None:
    """
    Bloqueo duro: si hay un turno abierto del día anterior, lanza
    ReglaDeNegocio. Debe llamarse al inicio de cualquier operación del
    local (ventas, stock, etc.) para garantizar el bloqueo.
    """
    hoy = ahora_db().date()
    turno_viejo = _turno_abierto_ayer(punto_de_venta_id, hoy, db)
    if turno_viejo:
        raise ReglaDeNegocio(
            f"Hay un turno del {turno_viejo.fecha_apertura.strftime('%d/%m/%Y')} "
            "sin cerrar. Cerrá el turno anterior antes de continuar."
        )


def obtener_turno_activo(punto_de_venta_id: int, db: Session) -> Turno | None:
    """Retorna el turno abierto del local (hoy o días anteriores), o None."""
    stmt = (
        select(Turno)
        .where(
            Turno.punto_de_venta_id == punto_de_venta_id,
            Turno.estado == EstadoTurno.ABIERTO,
        )
        .options(
            joinedload(Turno.vendedoras).joinedload(TurnoVendedora.usuario),
            joinedload(Turno.usuario_apertura),
            joinedload(Turno.punto_de_venta),
        )
        .order_by(Turno.fecha_apertura.desc())
    )
    return db.execute(stmt).unique().scalar_one_or_none()


def abrir_turno(
    punto_de_venta_id: int,
    usuario_id: int,
    efectivo_apertura: float,
    notas: str | None,
    db: Session,
    ip: str | None = None,
) -> Turno:
    """
    Abre un nuevo turno para el local. Pasos:
    1. Verifica que no haya turno del día anterior sin cerrar (bloqueo duro).
    2. Verifica que no haya ya un turno abierto hoy (error: debe unirse).
    3. Crea el turno y registra al usuario en turno_vendedoras.
    4. Auditoria: 'turno.abierto'
    """
    hoy = ahora_db().date()
    # Paso 1: bloqueo duro
    turno_viejo = _turno_abierto_ayer(punto_de_venta_id, hoy, db)
    if turno_viejo:
        raise ReglaDeNegocio(
            f"Hay un turno del {turno_viejo.fecha_apertura.strftime('%d/%m/%Y')} "
            "sin cerrar. Cerrá el turno anterior antes de continuar."
        )
    # Paso 2: turno abierto hoy
    turno_hoy = _turno_abierto_hoy(punto_de_venta_id, hoy, db)
    if turno_hoy:
        raise ReglaDeNegocio(
            "Ya hay un turno abierto hoy. Usá 'Unirme al turno' para sumarte."
        )

    ahora = ahora_db()
    turno = Turno(
        punto_de_venta_id=punto_de_venta_id,
        estado=EstadoTurno.ABIERTO,
        efectivo_apertura=efectivo_apertura,
        usuario_apertura_id=usuario_id,
        fecha_apertura=ahora,
        notas=notas,
        created_at=ahora,
        updated_at=ahora,
    )
    db.add(turno)
    db.flush()  # Necesitamos el id para turno_vendedoras

    vendedora = TurnoVendedora(
        turno_id=turno.id,
        usuario_id=usuario_id,
        ingreso=ahora,
    )
    db.add(vendedora)
    db.flush()

    registrar_auditoria(
        db=db,
        usuario_id=usuario_id,
        accion="turno.abierto",
        entidad="turnos",
        entidad_id=turno.id,
        estado_nuevo=snapshot(turno),
        ip_origen=ip,
    )
    return turno


def unirse_a_turno(
    punto_de_venta_id: int,
    usuario_id: int,
    db: Session,
    ip: str | None = None,
) -> Turno:
    """
    Suma al usuario al turno abierto del local.
    Si ya estaba registrado, devuelve el turno sin duplicar.
    """
    turno = obtener_turno_activo(punto_de_venta_id, db)
    if not turno:
        raise ReglaDeNegocio("No hay turno abierto en este local.")

    ya_registrada = any(tv.usuario_id == usuario_id for tv in turno.vendedoras)
    if not ya_registrada:
        db.add(TurnoVendedora(
            turno_id=turno.id,
            usuario_id=usuario_id,
            ingreso=ahora_db(),
        ))
        db.flush()

    return turno


def registrar_retiro(
    turno_id: int,
    monto: float,
    motivo: str,
    autorizado_por_id: int,
    realizado_por_id: int,
    db: Session,
    ip: str | None = None,
) -> RetiroEfectivo:
    """
    Registra un retiro de efectivo en el turno activo.
    La autorización del Dueño se verifica en el endpoint (requiere_permiso CAJA_RETIRO).
    """
    turno = db.get(Turno, turno_id)
    if not turno:
        raise NoEncontrado("Turno no encontrado")
    if turno.estado != EstadoTurno.ABIERTO:
        raise ReglaDeNegocio("Solo se pueden registrar retiros en turnos abiertos.")
    if monto <= 0:
        raise ReglaDeNegocio("El monto del retiro debe ser mayor a cero.")

    ahora = ahora_db()
    retiro = RetiroEfectivo(
        turno_id=turno_id,
        monto=monto,
        motivo=motivo,
        autorizado_por=autorizado_por_id,
        realizado_por=realizado_por_id,
        timestamp=ahora,
    )
    db.add(retiro)
    db.flush()

    registrar_auditoria(
        db=db,
        usuario_id=realizado_por_id,
        accion="caja.retiro_efectivo",
        entidad="retiros_efectivo",
        entidad_id=retiro.id,
        estado_nuevo=snapshot(retiro),
        ip_origen=ip,
    )
    return retiro


def listar_turnos(
    db: Session,
    punto_de_venta_id: int | None = None,
    estado: str | None = None,
    pagina: int = 1,
    tamano: int = 20,
) -> tuple[list[Turno], int]:
    stmt = (
        select(Turno)
        .options(
            joinedload(Turno.usuario_apertura),
            joinedload(Turno.punto_de_venta),
        )
        .order_by(Turno.fecha_apertura.desc())
    )
    if punto_de_venta_id:
        stmt = stmt.where(Turno.punto_de_venta_id == punto_de_venta_id)
    if estado:
        stmt = stmt.where(Turno.estado == estado)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    filas = db.execute(stmt.offset((pagina - 1) * tamano).limit(tamano)).unique().scalars().all()
    return list(filas), total
