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
from app.models.turno import Arqueo, ArqueoItem, EstadoTurno, Turno, TurnoVendedora
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


def efectivo_cierre_anterior(punto_de_venta_id: int, db: Session) -> dict | None:
    """
    El efectivo que quedó en la caja al cerrar el último turno del local:
    lo CONTADO (declarado) en la línea de efectivo de su arqueo, que es lo que
    físicamente quedó. Precarga el "Efectivo inicial" del turno siguiente.

    None si el local nunca cerró un turno o si ese arqueo no tiene línea de
    efectivo.
    """
    from app.services.arqueo import medio_efectivo

    efectivo = medio_efectivo(db)
    if efectivo is None:
        return None

    fila = db.execute(
        select(Turno.id, Turno.fecha_cierre, ArqueoItem.monto_declarado)
        .join(Arqueo, Arqueo.turno_id == Turno.id)
        .join(ArqueoItem, ArqueoItem.arqueo_id == Arqueo.id)
        .where(
            Turno.punto_de_venta_id == punto_de_venta_id,
            Turno.estado == EstadoTurno.CERRADO,
            ArqueoItem.medio_de_pago_id == efectivo.id,
        )
        .order_by(Turno.fecha_cierre.desc(), Turno.id.desc())
        .limit(1)
    ).first()
    if fila is None:
        return None
    return {"turno_id": fila[0], "fecha_cierre": fila[1], "efectivo": fila[2]}


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

    anterior = efectivo_cierre_anterior(punto_de_venta_id, db)

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
        # Con lo que dejó el cierre anterior: si la vendedora corrigió el
        # valor precargado, la diferencia queda a la vista.
        estado_nuevo=snapshot({
            **snapshot(turno),
            "efectivo_cierre_anterior": (anterior or {}).get("efectivo"),
        }),
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


def turno_para_operar(punto_de_venta_id: int, db: Session) -> Turno:
    """
    El turno sobre el que se registra una operación de caja del local.

    Exige un turno abierto HOY: un turno de un día anterior sin cerrar es el
    bloqueo duro de siempre, y sin turno no hay caja donde registrar nada.
    Única puerta para retiros, novedades, retiros de mercadería y cobros de
    joyero (Principio 2).
    """
    verificar_bloqueo_turno(punto_de_venta_id, db)
    turno = obtener_turno_activo(punto_de_venta_id, db)
    if turno is None:
        raise ReglaDeNegocio("No hay un turno abierto en este local: iniciá el turno primero.")
    return turno


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
