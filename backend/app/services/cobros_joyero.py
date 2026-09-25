"""
Cobros de joyero (sesión 09).

El joyero hace arreglos; el cliente los paga en el local y esa plata después
se le entrega al joyero (pasamanos). Entra plata a la caja, así que afecta el
arqueo en el medio de pago elegido, pero NO es venta: no genera código de
cambio, no descuenta stock y no aparece en los reportes de ventas.

La vendedora ve dos precios —en efectivo y con otros medios— y cobra el que
corresponde al medio con que paga el cliente. Nunca en cuotas.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.auditoria import registrar_auditoria
from app.core.utils import ahora_db, normalizar_texto, redondear
from app.models.operaciones_caja import CobroJoyero
from app.models.usuario import Usuario
from app.services import medios_pago as servicio_medios
from app.services.arqueo import medio_efectivo
from app.services.roles import ReglaDeNegocio
from app.services.turnos import turno_para_operar


def registrar_cobro(
    db: Session,
    autor: Usuario,
    *,
    punto_de_venta_id: int,
    medio_de_pago_id: int,
    monto_efectivo: Decimal,
    monto_otros: Decimal,
    numero_reclamo: str | None = None,
    notas: str | None = None,
    ip_origen: str | None = None,
) -> CobroJoyero:
    turno = turno_para_operar(punto_de_venta_id, db)

    medio = servicio_medios.obtener_medio(db, medio_de_pago_id)
    if not medio.activo:
        raise ReglaDeNegocio(f"El medio de pago '{medio.nombre}' está inactivo")
    # Una seña es saldo del cliente para compras, no plata para el joyero.
    if medio.es_sena:
        raise ReglaDeNegocio("Un cobro de joyero no se puede pagar con una seña")

    efectivo = redondear(Decimal(monto_efectivo or 0))
    otros = redondear(Decimal(monto_otros or 0))
    if efectivo < 0 or otros < 0:
        raise ReglaDeNegocio("Los precios no pueden ser negativos")

    medio_de_efectivo = medio_efectivo(db)
    paga_en_efectivo = medio_de_efectivo is not None and medio.id == medio_de_efectivo.id
    cobrado = efectivo if paga_en_efectivo else otros
    if cobrado <= 0:
        precio = "en efectivo" if paga_en_efectivo else "con otros medios"
        raise ReglaDeNegocio(f"Falta el precio {precio}: es el que se cobra con ese medio")

    cobro = CobroJoyero(
        turno_id=turno.id,
        punto_de_venta_id=punto_de_venta_id,
        monto_efectivo=efectivo,
        monto_otros=otros,
        medio_de_pago_id=medio.id,
        monto_cobrado=cobrado,
        numero_reclamo=normalizar_texto(numero_reclamo),
        registrado_por_id=autor.id,
        timestamp=ahora_db(),
        notas=normalizar_texto(notas),
    )
    db.add(cobro)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="caja.cobro_joyero",
        entidad="cobros_joyero",
        entidad_id=cobro.id,
        estado_nuevo={
            "turno_id": turno.id,
            "medio": medio.nombre,
            "monto_cobrado": cobrado,
            "numero_reclamo": cobro.numero_reclamo,
        },
        ip_origen=ip_origen,
    )
    return cobro


def listar_cobros(
    db: Session,
    *,
    turno_id: int | None = None,
    punto_de_venta_id: int | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    pagina: int = 1,
    tamano: int = 10,
) -> tuple[list[CobroJoyero], int]:
    consulta = select(CobroJoyero).options(
        joinedload(CobroJoyero.medio_de_pago),
        joinedload(CobroJoyero.registrado_por),
        joinedload(CobroJoyero.punto_de_venta),
    )
    if turno_id is not None:
        consulta = consulta.where(CobroJoyero.turno_id == turno_id)
    if punto_de_venta_id is not None:
        consulta = consulta.where(CobroJoyero.punto_de_venta_id == punto_de_venta_id)
    if desde is not None:
        consulta = consulta.where(func.date(CobroJoyero.timestamp) >= desde)
    if hasta is not None:
        consulta = consulta.where(func.date(CobroJoyero.timestamp) <= hasta)

    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()
    filas = (
        db.execute(
            consulta.order_by(CobroJoyero.timestamp.desc(), CobroJoyero.id.desc())
            .limit(tamano)
            .offset((pagina - 1) * tamano)
        )
        .unique()
        .scalars()
        .all()
    )
    return list(filas), total
