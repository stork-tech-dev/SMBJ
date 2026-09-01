"""
Servicio de arqueo de cierre de turno.

El arqueo compara lo que el sistema registró (venta_pagos del turno)
contra lo que la vendedora declara al cerrar.

Reglas:
  - Los retiros de efectivo se descuentan del esperado de efectivo.
  - Los medios agrupados (agrupa_en_terminal=TRUE) se suman por grupo.
  - Los medios informativos (es_informativo=TRUE) se muestran pero no
    suman al total (ej: gift cards virtuales).
  - Las señas usadas en ventas SÍ suman (entró plata física).
  - Las gift cards físicas no aparecen (son ventas normales de producto).
  - La diferencia != 0 genera notificaciones para todos los usuarios Dueño.
  - Todo se escribe en la misma transacción que el cierre del turno.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.utils import ahora_db
from app.models.medio_pago import MedioDePago
from app.models.rol import Rol
from app.models.turno import (
    Arqueo,
    ArqueoItem,
    EstadoTurno,
    MedioPagoArqueoConfig,
    Notificacion,
    TipoNotificacion,
    Turno,
    TurnoVendedora,
)
from app.models.usuario import Usuario
from app.models.venta import EstadoVenta, Venta, VentaPago
from app.services.roles import NoEncontrado, ReglaDeNegocio


def _pagos_del_turno(turno: Turno, db: Session) -> dict[int, Decimal]:
    """
    Suma los pagos de ventas confirmadas del turno por medio_de_pago_id.
    Retorna {medio_de_pago_id: monto_total}.
    """
    stmt = (
        select(VentaPago.medio_de_pago_id, func.sum(VentaPago.monto_total))
        .join(Venta, Venta.id == VentaPago.venta_id)
        .where(
            Venta.punto_de_venta_id == turno.punto_de_venta_id,
            Venta.estado == EstadoVenta.CONFIRMADA,
            Venta.created_at >= turno.fecha_apertura,
        )
        .group_by(VentaPago.medio_de_pago_id)
    )
    if turno.fecha_cierre:
        stmt = stmt.where(Venta.created_at <= turno.fecha_cierre)

    rows = db.execute(stmt).all()
    return {row[0]: row[1] or Decimal("0") for row in rows}


def _retiros_efectivo_del_turno(turno_id: int, db: Session) -> Decimal:
    """Suma los retiros de efectivo del turno."""
    from app.models.turno import RetiroEfectivo
    stmt = select(func.sum(RetiroEfectivo.monto)).where(
        RetiroEfectivo.turno_id == turno_id
    )
    return db.execute(stmt).scalar_one_or_none() or Decimal("0")


def calcular_esperado(turno_id: int, db: Session) -> dict:
    """
    Calcula el arqueo esperado para el turno según:
    - Configuración de agrupamiento (medios_pago_arqueo_config)
    - Retiros de efectivo (se descuentan del efectivo esperado)

    Retorna dict con 'items' (lista de dicts) y 'total_esperado'.
    """
    turno = db.get(Turno, turno_id)
    if not turno:
        raise NoEncontrado("Turno no encontrado")

    # Obtener configuraciones de arqueo
    configs = db.execute(
        select(MedioPagoArqueoConfig, MedioDePago)
        .join(MedioDePago, MedioDePago.id == MedioPagoArqueoConfig.medio_de_pago_id)
    ).all()

    # Mapa medio_id → (config, medio)
    config_por_medio: dict[int, tuple] = {
        cfg.medio_de_pago_id: (cfg, medio) for cfg, medio in configs
    }

    # Pagos del turno por medio
    pagos = _pagos_del_turno(turno, db)

    # Identificar el medio "efectivo" para descontar retiros.
    # Asumimos que el medio con nombre ilike 'efectivo' es el de efectivo.
    efectivo_medio = db.execute(
        select(MedioDePago).where(func.lower(MedioDePago.nombre) == "efectivo")
    ).scalar_one_or_none()

    retiros = Decimal("0")
    if efectivo_medio:
        retiros = _retiros_efectivo_del_turno(turno_id, db)

    # Construir items agrupados
    grupos: dict[str, dict] = {}  # key → item acumulado

    for medio_id, monto in pagos.items():
        cfg_tuple = config_por_medio.get(medio_id)
        if not cfg_tuple:
            # Sin configuración → arquear individual con defaults
            medio = db.get(MedioDePago, medio_id)
            key = f"medio:{medio_id}"
            grupos[key] = {
                "medio_de_pago_id": medio_id,
                "medio_nombre": medio.nombre if medio else f"Medio #{medio_id}",
                "grupo_terminal": None,
                "monto_esperado": monto,
                "es_informativo": False,
            }
            continue

        cfg, medio = cfg_tuple
        if cfg.agrupa_en_terminal and cfg.grupo_terminal:
            key = f"grupo:{cfg.grupo_terminal}"
            if key not in grupos:
                grupos[key] = {
                    "medio_de_pago_id": None,
                    "medio_nombre": cfg.grupo_terminal,
                    "grupo_terminal": cfg.grupo_terminal,
                    "monto_esperado": Decimal("0"),
                    "es_informativo": cfg.es_informativo,
                }
            grupos[key]["monto_esperado"] += monto
        else:
            key = f"medio:{medio_id}"
            grupos[key] = {
                "medio_de_pago_id": medio_id,
                "medio_nombre": medio.nombre,
                "grupo_terminal": None,
                "monto_esperado": monto,
                "es_informativo": cfg.es_informativo,
            }

    # Aplicar descuento de retiros al efectivo
    if efectivo_medio:
        key = f"medio:{efectivo_medio.id}"
        if key in grupos:
            grupos[key]["monto_esperado"] = max(
                Decimal("0"), grupos[key]["monto_esperado"] - retiros
            )

    items = list(grupos.values())
    total_esperado = sum(
        i["monto_esperado"] for i in items if not i["es_informativo"]
    )

    return {"turno_id": turno_id, "items": items, "total_esperado": total_esperado}


def _notificar_duenos(
    turno: Turno,
    arqueo: Arqueo,
    items: list[ArqueoItem],
    db: Session,
) -> None:
    """
    Genera una notificación para cada usuario con rol Dueño.
    Se llama solo si diferencia != 0.
    """
    # Buscar usuarios activos con rol que incluya 'due' en el nombre (Dueño)
    duenos = db.execute(
        select(Usuario)
        .join(Rol, Rol.id == Usuario.rol_id)
        .where(func.lower(Rol.nombre).contains("due"))
        .where(Usuario.activo.is_(True))
    ).scalars().all()

    if not duenos:
        return

    vendedoras_nombres = [
        tv.usuario.nombre for tv in turno.vendedoras if tv.usuario
    ]

    fecha_str = turno.fecha_apertura.strftime("%d/%m/%Y")
    diferencia = arqueo.diferencia
    signo = "+" if diferencia > 0 else ""

    detalle_lines = []
    for item in items:
        if not item.es_informativo:
            detalle_lines.append(
                f"  {item.grupo_terminal or 'Medio #' + str(item.medio_de_pago_id)}: "
                f"esperado ${item.monto_esperado:,.2f} — "
                f"declarado ${item.monto_declarado:,.2f} — "
                f"diferencia ${item.diferencia:+,.2f}"
            )

    cuerpo = (
        f"Local: {turno.punto_de_venta.nombre}\n"
        f"Fecha: {fecha_str}\n"
        f"Diferencia total: ${diferencia:,.2f} ({signo}{diferencia:,.2f})\n"
        f"Vendedoras en el turno: {', '.join(vendedoras_nombres) or '—'}\n"
        f"Detalle:\n" + "\n".join(detalle_lines)
    )

    metadata_data = {
        "turno_id": turno.id,
        "diferencia": str(diferencia),
        "punto_de_venta": turno.punto_de_venta.nombre,
        "vendedoras": vendedoras_nombres,
    }

    ahora = ahora_db()
    for dueno in duenos:
        db.add(Notificacion(
            usuario_id=dueno.id,
            tipo=TipoNotificacion.DIFERENCIA_ARQUEO,
            titulo=f"Diferencia en arqueo — {turno.punto_de_venta.nombre} — {fecha_str}",
            cuerpo=cuerpo,
            leida=False,
            metadata_=metadata_data,
            created_at=ahora,
        ))


def registrar_arqueo(
    turno_id: int,
    items_declarados: list[dict],
    total_declarado: Decimal,
    usuario_id: int,
    db: Session,
    ip: str | None = None,
) -> Arqueo:
    """
    Registra el arqueo y cierra el turno.
    Si diferencia != 0, genera notificaciones para los Dueños.
    Todo en la misma transacción.
    """
    turno = db.execute(
        select(Turno)
        .where(Turno.id == turno_id)
        .options(
            joinedload(Turno.vendedoras).joinedload(TurnoVendedora.usuario),
            joinedload(Turno.punto_de_venta),
        )
    ).unique().scalar_one_or_none()

    if not turno:
        raise NoEncontrado("Turno no encontrado")
    if turno.estado != EstadoTurno.ABIERTO:
        raise ReglaDeNegocio("El turno ya está cerrado.")
    if turno.arqueo:
        raise ReglaDeNegocio("El turno ya tiene un arqueo registrado.")

    esperado = calcular_esperado(turno_id, db)
    total_esperado = esperado["total_esperado"]

    ahora = ahora_db()

    # diferencia es GENERATED ALWAYS AS en la DB; no se incluye en el INSERT
    arqueo = Arqueo(
        turno_id=turno_id,
        usuario_id=usuario_id,
        total_esperado=total_esperado,
        total_declarado=total_declarado,
        notificacion_enviada=False,
        created_at=ahora,
    )
    db.add(arqueo)
    db.flush()

    # Construir mapa esperado por key para los items
    esperado_map = {
        (i.get("medio_de_pago_id"), i.get("grupo_terminal")): i
        for i in esperado["items"]
    }

    arqueo_items: list[ArqueoItem] = []
    for decl in items_declarados:
        medio_id = decl.get("medio_de_pago_id")
        grupo = decl.get("grupo_terminal")
        esp = esperado_map.get((medio_id, grupo), {})
        monto_esperado = esp.get("monto_esperado", Decimal("0"))
        monto_declarado = Decimal(str(decl.get("monto_declarado", 0)))

        # diferencia es GENERATED ALWAYS AS en la DB; no se incluye en el INSERT
        item = ArqueoItem(
            arqueo_id=arqueo.id,
            medio_de_pago_id=medio_id,
            grupo_terminal=grupo,
            monto_esperado=monto_esperado,
            monto_declarado=monto_declarado,
            es_informativo=decl.get("es_informativo", False),
        )
        db.add(item)
        arqueo_items.append(item)

    db.flush()

    # Refrescar para leer la diferencia calculada por PostgreSQL (GENERATED ALWAYS AS)
    db.refresh(arqueo)
    for item in arqueo_items:
        db.refresh(item)

    # Cerrar el turno
    turno.estado = EstadoTurno.CERRADO
    turno.fecha_cierre = ahora
    turno.usuario_cierre_id = usuario_id
    turno.updated_at = ahora
    db.flush()

    # Notificar si hay diferencia
    if arqueo.diferencia != Decimal("0"):
        _notificar_duenos(turno, arqueo, arqueo_items, db)
        arqueo.notificacion_enviada = True
        db.flush()

    registrar_auditoria(
        db=db,
        usuario_id=usuario_id,
        accion="caja.arqueo_cerrado",
        entidad="arqueos",
        entidad_id=arqueo.id,
        estado_nuevo=snapshot(arqueo),
        ip_origen=ip,
    )
    return arqueo
