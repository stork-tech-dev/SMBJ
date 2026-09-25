"""
Reportes de Caja: siete vistas globales (sin aislamiento por dispositivo) de
lo que pasó en las cajas de UN día, opcionalmente de un solo local.

El día se aplica por **turno** en todo lo que pertenece a uno (novedades,
arqueos, movimientos, retiros, cobros de joyero, retiros de mercadería): entra
todo lo de los turnos cuya `fecha_apertura` cae en esa fecha — el mismo
criterio que el Resumen diario consolidado (`ventas.resumen_diario_consolidado`).
Así un turno que cruza la medianoche no queda partido entre dos reportes.

Las señas no son de un turno ni de un local: se filtran por su fecha de alta.

Todo devuelve datos crudos (Decimal, datetime); el formato lo pone el frontend
o el Excel.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session, joinedload

from app.core.utils import ahora_db
from app.models.cliente import Cliente
from app.models.medio_pago import MedioDePago
from app.models.operaciones_caja import CobroJoyero, NovedadCaja, TipoNovedad
from app.models.punto_de_venta import PuntoDeVenta
from app.models.sena import Sena
from app.models.turno import Arqueo, ArqueoItem, RetiroEfectivo, Turno
from app.models.venta import EstadoVenta, Venta, VentaPago
from app.services import arqueo as servicio_arqueo
from app.services import configuracion as servicio_configuracion
from app.services import retiros_mercaderia as servicio_mercaderia

CERO = Decimal("0")


# ---------------------------------------------------------------------------
# Turnos del día (base de casi todos los reportes)
# ---------------------------------------------------------------------------


def turnos_del_dia(db: Session, fecha: date, punto_de_venta_id: int | None) -> list[Turno]:
    """Turnos abiertos en *fecha* (de un local o de todos), por local y hora."""
    consulta = (
        select(Turno)
        .join(PuntoDeVenta, PuntoDeVenta.id == Turno.punto_de_venta_id)
        .options(joinedload(Turno.punto_de_venta))
        .where(func.date(Turno.fecha_apertura) == fecha)
        .order_by(func.lower(PuntoDeVenta.nombre), Turno.fecha_apertura, Turno.id)
    )
    if punto_de_venta_id is not None:
        consulta = consulta.where(Turno.punto_de_venta_id == punto_de_venta_id)
    return list(db.execute(consulta).unique().scalars())


def _datos_turno(turno: Turno) -> dict:
    """Cabecera común de los reportes agrupados por turno."""
    return {
        "turno_id": turno.id,
        "punto_de_venta_id": turno.punto_de_venta_id,
        "punto_de_venta_nombre": turno.punto_de_venta.nombre,
        "fecha_apertura": turno.fecha_apertura,
        "fecha_cierre": turno.fecha_cierre,
    }


def _de_los_turnos(columna, turnos: list[Turno]):
    """Condición `columna IN (ids de los turnos)`; falsa si no hay turnos."""
    return columna.in_([t.id for t in turnos])


# ---------------------------------------------------------------------------
# 1. Novedades de caja
# ---------------------------------------------------------------------------


def novedades(db: Session, fecha: date, punto_de_venta_id: int | None = None) -> dict:
    """
    Novedades agrupadas por turno, con subtotal de entradas, salidas y neto
    por turno y del día. Solo aparecen los turnos que tuvieron novedades.
    """
    turnos = turnos_del_dia(db, fecha, punto_de_venta_id)
    filas = (
        db.execute(
            select(NovedadCaja)
            .options(
                joinedload(NovedadCaja.concepto),
                joinedload(NovedadCaja.autorizador),
                joinedload(NovedadCaja.registrado_por),
            )
            .where(_de_los_turnos(NovedadCaja.turno_id, turnos))
            .order_by(NovedadCaja.timestamp, NovedadCaja.id)
        )
        .unique()
        .scalars()
        .all()
    )

    por_turno: dict[int, list[NovedadCaja]] = {}
    for n in filas:
        por_turno.setdefault(n.turno_id, []).append(n)

    grupos = []
    total_entradas = total_salidas = CERO
    for turno in turnos:
        lista = por_turno.get(turno.id)
        if not lista:
            continue
        entradas = sum((n.monto for n in lista if n.tipo == TipoNovedad.ENTRADA), CERO)
        salidas = sum((n.monto for n in lista if n.tipo == TipoNovedad.SALIDA), CERO)
        total_entradas += entradas
        total_salidas += salidas
        grupos.append({
            **_datos_turno(turno),
            "novedades": [
                {
                    "id": n.id,
                    "timestamp": n.timestamp,
                    "concepto": n.concepto.nombre,
                    "tipo": n.tipo.value,
                    "monto": n.monto,
                    "autorizador_nombre": n.autorizador.nombre,
                    "registrado_por_nombre": n.registrado_por.nombre,
                    "notas": n.notas,
                }
                for n in lista
            ],
            "total_entradas": entradas,
            "total_salidas": salidas,
            "neto": entradas - salidas,
        })

    return {
        "turnos": grupos,
        "total_entradas": total_entradas,
        "total_salidas": total_salidas,
        "neto": total_entradas - total_salidas,
    }


# ---------------------------------------------------------------------------
# 2. Arqueos de caja
# ---------------------------------------------------------------------------


def _nombre_item(item: ArqueoItem) -> str:
    """Columna del item: el grupo de terminal si agrupa, si no el medio."""
    if item.grupo_terminal:
        return item.grupo_terminal
    return item.medio_de_pago.nombre if item.medio_de_pago else "Sin medio"


def arqueos(db: Session, fecha: date, punto_de_venta_id: int | None = None) -> dict:
    """
    Un arqueo por fila: por cada medio (o grupo de terminal) lo que decía el
    sistema, lo contado y la diferencia. Las columnas son las que aparecen en
    los arqueos del día, en el orden en que se declararon — si Débito y
    Crédito se arquean juntos en la terminal, son una sola columna.
    """
    turnos = turnos_del_dia(db, fecha, punto_de_venta_id)
    por_turno = {t.id: t for t in turnos}
    registros = (
        db.execute(
            select(Arqueo)
            .options(
                joinedload(Arqueo.items).joinedload(ArqueoItem.medio_de_pago),
                joinedload(Arqueo.usuario),
            )
            .where(_de_los_turnos(Arqueo.turno_id, turnos))
        )
        .unique()
        .scalars()
        .all()
    )
    orden = {t.id: i for i, t in enumerate(turnos)}
    registros = sorted(registros, key=lambda a: orden[a.turno_id])

    columnas: list[str] = []
    filas = []
    for arqueo in registros:
        items = []
        for item in sorted(arqueo.items, key=lambda i: i.id):
            nombre = _nombre_item(item)
            if nombre not in columnas:
                columnas.append(nombre)
            items.append({
                "columna": nombre,
                "monto_esperado": item.monto_esperado,
                "monto_declarado": item.monto_declarado,
                "diferencia": item.diferencia,
                "es_informativo": item.es_informativo,
            })
        filas.append({
            **_datos_turno(por_turno[arqueo.turno_id]),
            "arqueo_id": arqueo.id,
            "usuario_nombre": arqueo.usuario.nombre,
            "items": items,
            "total_esperado": arqueo.total_esperado,
            "total_declarado": arqueo.total_declarado,
            "diferencia": arqueo.diferencia,
        })

    return {"columnas": columnas, "filas": filas}


# ---------------------------------------------------------------------------
# 3. Movimientos de caja por turno
# ---------------------------------------------------------------------------


def _movimiento(timestamp: datetime, tipo: str, detalle: str, medio: str | None,
                ingreso: Decimal = CERO, egreso: Decimal = CERO) -> dict:
    return {
        "timestamp": timestamp,
        "tipo": tipo,
        "detalle": detalle,
        "medio_de_pago": medio,
        "ingreso": ingreso,
        "egreso": egreso,
    }


def _ventas_del_turno(db: Session, turno: Turno) -> list[dict]:
    """
    Un movimiento por pago de venta confirmada del turno. Mismo criterio que
    el arqueo (`arqueo._pagos_del_turno`): ventas del local entre la apertura
    y el cierre (o hasta ahora si sigue abierto).
    """
    condicion = and_(
        Venta.punto_de_venta_id == turno.punto_de_venta_id,
        Venta.estado == EstadoVenta.CONFIRMADA,
        Venta.created_at >= turno.fecha_apertura,
    )
    if turno.fecha_cierre is not None:
        condicion = and_(condicion, Venta.created_at <= turno.fecha_cierre)
    filas = db.execute(
        select(Venta.created_at, Venta.numero, MedioDePago.nombre, VentaPago.monto_total)
        .join(VentaPago, VentaPago.venta_id == Venta.id)
        .join(MedioDePago, MedioDePago.id == VentaPago.medio_de_pago_id)
        .where(condicion)
        .order_by(Venta.created_at, VentaPago.id)
    ).all()
    return [
        _movimiento(creada, "venta", f"Venta {numero}", medio, ingreso=monto)
        for creada, numero, medio, monto in filas
    ]


def movimientos(db: Session, fecha: date, punto_de_venta_id: int | None = None) -> dict:
    """
    Todos los ingresos y egresos de cada turno, en orden cronológico:
    apertura, pagos de ventas, cobros de joyero, novedades y retiros de
    efectivo. Los retiros de mercadería no mueven la caja y no aparecen.

    Cada turno trae además `efectivo_esperado` —la misma cuenta que el
    arqueo—, para controlar el recorrido contra lo que había que contar.
    """
    turnos = turnos_del_dia(db, fecha, punto_de_venta_id)
    efectivo = servicio_arqueo.medio_efectivo(db)
    nombre_efectivo = efectivo.nombre if efectivo else "Efectivo"

    grupos = []
    for turno in turnos:
        lista = [
            _movimiento(
                turno.fecha_apertura, "apertura", "Apertura de caja",
                nombre_efectivo, ingreso=Decimal(turno.efectivo_apertura),
            )
        ]
        lista += _ventas_del_turno(db, turno)

        for c in db.execute(
            select(CobroJoyero).options(joinedload(CobroJoyero.medio_de_pago))
            .where(CobroJoyero.turno_id == turno.id)
        ).unique().scalars():
            detalle = "Cobro de joyero" + (f" — reclamo {c.numero_reclamo}" if c.numero_reclamo else "")
            lista.append(_movimiento(c.timestamp, "cobro_joyero", detalle,
                                     c.medio_de_pago.nombre, ingreso=c.monto_cobrado))

        for n in db.execute(
            select(NovedadCaja).options(joinedload(NovedadCaja.concepto))
            .where(NovedadCaja.turno_id == turno.id)
        ).unique().scalars():
            es_entrada = n.tipo == TipoNovedad.ENTRADA
            lista.append(_movimiento(
                n.timestamp, "novedad", f"Novedad: {n.concepto.nombre}", nombre_efectivo,
                ingreso=n.monto if es_entrada else CERO,
                egreso=CERO if es_entrada else n.monto,
            ))

        for r in db.execute(
            select(RetiroEfectivo).options(joinedload(RetiroEfectivo.usuario))
            .where(RetiroEfectivo.turno_id == turno.id)
        ).unique().scalars():
            lista.append(_movimiento(r.timestamp, "retiro_efectivo",
                                     f"Retiro de efectivo — {r.usuario.nombre}",
                                     nombre_efectivo, egreso=r.monto))

        # Orden estable: a igual hora, la apertura primero.
        orden = {"apertura": 0}
        lista.sort(key=lambda m: (m["timestamp"], orden.get(m["tipo"], 1)))

        grupos.append({
            **_datos_turno(turno),
            "movimientos": lista,
            "total_ingresos": sum((m["ingreso"] for m in lista), CERO),
            "total_egresos": sum((m["egreso"] for m in lista), CERO),
            "efectivo_esperado": servicio_arqueo.efectivo_esperado(turno.id, db),
        })

    return {"turnos": grupos}


# ---------------------------------------------------------------------------
# 4. Retiros de efectivo
# ---------------------------------------------------------------------------


def retiros_efectivo(db: Session, fecha: date, punto_de_venta_id: int | None = None) -> dict:
    """Retiros de los turnos del día, en orden cronológico, con el total."""
    turnos = turnos_del_dia(db, fecha, punto_de_venta_id)
    filas = (
        db.execute(
            select(RetiroEfectivo)
            .options(
                joinedload(RetiroEfectivo.usuario),
                joinedload(RetiroEfectivo.registrado_por),
                joinedload(RetiroEfectivo.punto_de_venta),
            )
            .where(_de_los_turnos(RetiroEfectivo.turno_id, turnos))
            .order_by(RetiroEfectivo.timestamp, RetiroEfectivo.id)
        )
        .unique()
        .scalars()
        .all()
    )
    return {
        "filas": [
            {
                "id": r.id,
                "turno_id": r.turno_id,
                "timestamp": r.timestamp,
                "punto_de_venta_nombre": r.punto_de_venta.nombre,
                "usuario_nombre": r.usuario.nombre,
                "registrado_por_nombre": r.registrado_por.nombre,
                "monto": r.monto,
            }
            for r in filas
        ],
        "total": sum((r.monto for r in filas), CERO),
    }


# ---------------------------------------------------------------------------
# 5. Cobros de joyero
# ---------------------------------------------------------------------------


def cobros_joyero(db: Session, fecha: date, punto_de_venta_id: int | None = None) -> dict:
    """Cobros de los turnos del día, con total por medio de pago y general."""
    turnos = turnos_del_dia(db, fecha, punto_de_venta_id)
    filas = (
        db.execute(
            select(CobroJoyero)
            .options(
                joinedload(CobroJoyero.medio_de_pago),
                joinedload(CobroJoyero.registrado_por),
                joinedload(CobroJoyero.punto_de_venta),
            )
            .where(_de_los_turnos(CobroJoyero.turno_id, turnos))
            .order_by(CobroJoyero.timestamp, CobroJoyero.id)
        )
        .unique()
        .scalars()
        .all()
    )
    por_medio: dict[str, Decimal] = {}
    for c in filas:
        por_medio[c.medio_de_pago.nombre] = por_medio.get(c.medio_de_pago.nombre, CERO) + c.monto_cobrado

    return {
        "filas": [
            {
                "id": c.id,
                "turno_id": c.turno_id,
                "timestamp": c.timestamp,
                "punto_de_venta_nombre": c.punto_de_venta.nombre,
                "vendedora_nombre": c.registrado_por.nombre,
                "numero_reclamo": c.numero_reclamo,
                "medio_de_pago": c.medio_de_pago.nombre,
                "monto": c.monto_cobrado,
                "notas": c.notas,
            }
            for c in filas
        ],
        "totales_por_medio": [
            {"medio_de_pago": medio, "monto": monto} for medio, monto in sorted(por_medio.items())
        ],
        "total": sum((c.monto_cobrado for c in filas), CERO),
    }


# ---------------------------------------------------------------------------
# 6. Señas
# ---------------------------------------------------------------------------

ESTADOS_SENA = ("activa", "usada", "vencida")


def senas(db: Session, fecha: date, estado: str | None = None) -> dict:
    """
    Señas dadas de alta en *fecha*, con su saldo, vencimiento y estado:
    - usada: ya no le queda saldo;
    - vencida: le queda saldo y pasó la vigencia (`dias_vigencia_sena`);
    - activa: el resto.

    El vencimiento se calcula (alta + vigencia), no se guarda (Principio 4).
    """
    dias = servicio_configuracion.dias_vigencia_sena(db)
    hoy = ahora_db().date()
    vencimiento = func.date(Sena.created_at) + dias
    estado_sql = case(
        (Sena.saldo == 0, "usada"),
        (vencimiento < hoy, "vencida"),
        else_="activa",
    )

    consulta = (
        select(Sena, Cliente.nombre, vencimiento.label("vencimiento"), estado_sql.label("estado"))
        .join(Cliente, Cliente.id == Sena.cliente_id)
        .where(func.date(Sena.created_at) == fecha)
        .order_by(Sena.created_at, Sena.id)
    )
    if estado is not None:
        consulta = consulta.where(estado_sql == estado)

    filas = db.execute(consulta).all()
    return {
        "dias_vigencia": dias,
        "filas": [
            {
                "id": s.id,
                "created_at": s.created_at,
                "cliente_nombre": cliente,
                "monto": s.monto,
                "saldo": s.saldo,
                "fecha_vencimiento": venc,
                "estado": est,
                "descripcion": s.descripcion,
            }
            for s, cliente, venc, est in filas
        ],
        "total_monto": sum((f[0].monto for f in filas), CERO),
        "total_saldo": sum((f[0].saldo for f in filas), CERO),
    }


# ---------------------------------------------------------------------------
# 7. Retiros de mercadería
# ---------------------------------------------------------------------------


def retiros_mercaderia(db: Session, fecha: date, punto_de_venta_id: int | None = None) -> dict:
    """
    Retiros de los turnos del día agrupados por empleada, con el subtotal a
    descontar del sueldo de cada una. Primero las de esta empresa, después
    las de la otra (el orden de `retiros_mercaderia.reporte`).
    """
    turnos = turnos_del_dia(db, fecha, punto_de_venta_id)
    retiros, _total = servicio_mercaderia.reporte(
        db, punto_de_venta_id=punto_de_venta_id, tamano=None,
        turno_ids=[t.id for t in turnos],
    )

    grupos: list[dict] = []
    for r in retiros:
        clave = (r.es_empresa_propia, r.empleada_usuario_id, r.nombre_empleada)
        if not grupos or grupos[-1]["_clave"] != clave:
            grupos.append({
                "_clave": clave,
                "empleada_nombre": r.nombre_empleada,
                "empleada_dni": r.empleada_dni,
                "es_empresa_propia": r.es_empresa_propia,
                "retiros": [],
                "subtotal_lista": CERO,
                "subtotal": CERO,
            })
        grupo = grupos[-1]
        grupo["retiros"].append(r)
        grupo["subtotal_lista"] += r.precio_lista
        grupo["subtotal"] += r.precio_con_descuento

    for grupo in grupos:
        del grupo["_clave"]

    return {
        "empleadas": grupos,
        "total_lista": sum((g["subtotal_lista"] for g in grupos), CERO),
        "total": sum((g["subtotal"] for g in grupos), CERO),
    }

