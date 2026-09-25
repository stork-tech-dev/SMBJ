"""
Retiros de mercadería de empleadas (sesión 09).

Una empleada se lleva un producto que se descuenta del sueldo. No es venta:
no toca la caja ni el arqueo, ni aparece en los reportes de ventas. Sí
descuenta stock del local y genera un código de cambio, porque el producto
puede ser para regalo; ese código se canjea después como un cambio común,
al precio de lista (ver `services/cambios.py`).

Identificación de la empleada: se busca entre los usuarios del sistema (por
usuario o nombre). Si no está, es de la otra empresa y sus datos van a mano.
El descuento es el mismo para todas: el del motivo marcado como
`es_descuento_empleada` en `motivos_descuento`, nunca un número escrito acá.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.auditoria import registrar_auditoria
from app.core.utils import (
    ahora_db,
    normalizar_texto,
    sin_tildes,
    sin_tildes_sql,
)
from app.models.operaciones_caja import RetiroMercaderia
from app.models.producto import Variante
from app.models.stock import TipoMovimiento
from app.models.usuario import Usuario
from app.models.venta import MotivoDescuento
from app.services import descuentos as servicio_descuentos
from app.services import stock as servicio_stock
from app.services.roles import NoEncontrado, ReglaDeNegocio
from app.services.turnos import turno_para_operar


def buscar_empleadas(db: Session, texto: str, limite: int = 10) -> list[Usuario]:
    """Usuarios activos cuyo usuario o nombre contiene el texto (sin tildes)."""
    limpio = normalizar_texto(texto)
    if not limpio:
        return []
    patron = f"%{sin_tildes(limpio)}%"
    return list(
        db.execute(
            select(Usuario)
            .where(
                Usuario.activo.is_(True),
                or_(
                    sin_tildes_sql(Usuario.username).ilike(patron),
                    sin_tildes_sql(Usuario.nombre).ilike(patron),
                ),
            )
            .order_by(func.lower(Usuario.nombre))
            .limit(limite)
        )
        .unique()
        .scalars()
        .all()
    )


def motivo_empleada(db: Session) -> MotivoDescuento:
    """El motivo de descuento de empleadas, activo y con porcentaje."""
    motivo = db.execute(
        select(MotivoDescuento).where(MotivoDescuento.es_descuento_empleada.is_(True))
    ).scalar_one_or_none()
    if motivo is None or not motivo.activo:
        raise ReglaDeNegocio(
            "No hay un motivo de descuento activo marcado como 'Descuento de "
            "empleada': configuralo en Motivos de descuento"
        )
    if motivo.porcentaje_sugerido is None:
        raise ReglaDeNegocio(
            f"El motivo '{motivo.nombre}' no tiene porcentaje: cargale el "
            "porcentaje del descuento de empleada"
        )
    return motivo


def cotizar(db: Session, variante: Variante) -> dict:
    """
    Precio de lista, porcentaje y lo que se descuenta del sueldo.

    El descuento de empleada se aplica sobre el precio de lista, con el mismo
    cálculo que el resto de los descuentos (`aplicar_descuentos`, redondeo
    hacia abajo).
    """
    from app.services.ventas import _redondeo

    motivo = motivo_empleada(db)
    precio_lista = Decimal(variante.precio_venta_efectivo)
    porcentaje = Decimal(motivo.porcentaje_sugerido)
    precio = servicio_descuentos.aplicar_descuentos(
        precio_lista, Decimal("0"), porcentaje, _redondeo(db)
    )
    return {
        "motivo": motivo,
        "precio_lista": precio_lista,
        "descuento": porcentaje,
        "precio_con_descuento": precio,
    }


def registrar_retiro(
    db: Session,
    autor: Usuario,
    *,
    punto_de_venta_id: int,
    variante_id: int,
    empleada_usuario_id: int | None = None,
    empleada_nombre: str | None = None,
    empleada_dni: str | None = None,
    ip_origen: str | None = None,
) -> RetiroMercaderia:
    """
    Registra el retiro, descuenta el stock y genera el código de cambio,
    todo en la misma transacción.

    Con `empleada_usuario_id` es de esta empresa; sin él, de la otra, y el
    nombre es obligatorio.
    """
    from app.services.ventas import generar_codigo_cambio

    turno = turno_para_operar(punto_de_venta_id, db)

    if empleada_usuario_id is not None:
        empleada = db.get(Usuario, empleada_usuario_id)
        if empleada is None or not empleada.activo:
            raise NoEncontrado("La empleada elegida no existe o está inactiva")
        es_propia, nombre, dni = True, None, None
    else:
        nombre = normalizar_texto(empleada_nombre)
        if not nombre:
            raise ReglaDeNegocio(
                "Empleada de otra empresa: hay que cargar nombre y apellido"
            )
        es_propia, dni = False, normalizar_texto(empleada_dni)

    variante = servicio_stock.obtener_variante(db, variante_id)
    if not variante.activo or not variante.producto.activo:
        raise ReglaDeNegocio(
            f"'{variante.producto.descripcion}' está dado de baja: no se puede retirar"
        )

    cotizacion = cotizar(db, variante)

    retiro = RetiroMercaderia(
        turno_id=turno.id,
        punto_de_venta_id=punto_de_venta_id,
        empleada_usuario_id=empleada_usuario_id,
        empleada_nombre=nombre,
        empleada_dni=dni,
        es_empresa_propia=es_propia,
        variante_id=variante.id,
        precio_lista=cotizacion["precio_lista"],
        motivo_descuento_id=cotizacion["motivo"].id,
        descuento_aplicado=cotizacion["descuento"],
        precio_con_descuento=cotizacion["precio_con_descuento"],
        codigo_cambio=generar_codigo_cambio(db),
        registrado_por_id=autor.id,
        timestamp=ahora_db(),
    )
    db.add(retiro)
    db.flush()

    # El producto sale del local. Sin `permitir_faltante`: a diferencia de una
    # venta, un retiro no se hace con mercadería que el sistema no ve.
    servicio_stock.aplicar_movimiento(
        db,
        autor,
        tipo=TipoMovimiento.RETIRO_MERCADERIA,
        variante_id=variante.id,
        cantidad=1,
        punto_venta_origen_id=punto_de_venta_id,
        retiro_mercaderia_id=retiro.id,
        notas=f"Retiro de mercadería de empleada #{retiro.id}",
        ip_origen=ip_origen,
    )

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="caja.retiro_mercaderia",
        entidad="retiros_mercaderia",
        entidad_id=retiro.id,
        estado_nuevo=retiro,
        ip_origen=ip_origen,
    )
    return retiro


def _consulta(
    punto_de_venta_id: int | None,
    desde: date | None,
    hasta: date | None,
    empleada: str | None,
    es_empresa_propia: bool | None,
    turno_ids: list[int] | None = None,
):
    consulta = (
        select(RetiroMercaderia)
        .outerjoin(Usuario, Usuario.id == RetiroMercaderia.empleada_usuario_id)
        .options(
            joinedload(RetiroMercaderia.empleada),
            joinedload(RetiroMercaderia.variante).joinedload(Variante.producto),
            joinedload(RetiroMercaderia.punto_de_venta),
            joinedload(RetiroMercaderia.registrado_por),
        )
    )
    if punto_de_venta_id is not None:
        consulta = consulta.where(RetiroMercaderia.punto_de_venta_id == punto_de_venta_id)
    if desde is not None:
        consulta = consulta.where(func.date(RetiroMercaderia.timestamp) >= desde)
    if hasta is not None:
        consulta = consulta.where(func.date(RetiroMercaderia.timestamp) <= hasta)
    if es_empresa_propia is not None:
        consulta = consulta.where(RetiroMercaderia.es_empresa_propia.is_(es_empresa_propia))
    if turno_ids is not None:
        consulta = consulta.where(RetiroMercaderia.turno_id.in_(turno_ids))
    if empleada:
        patron = f"%{sin_tildes(empleada.strip())}%"
        consulta = consulta.where(
            or_(
                sin_tildes_sql(Usuario.nombre).ilike(patron),
                sin_tildes_sql(RetiroMercaderia.empleada_nombre).ilike(patron),
            )
        )
    return consulta


def _nombre_empleada_sql():
    return func.lower(func.coalesce(Usuario.nombre, RetiroMercaderia.empleada_nombre))


def listar_retiros(
    db: Session,
    *,
    punto_de_venta_id: int | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    empleada: str | None = None,
    es_empresa_propia: bool | None = None,
    pagina: int = 1,
    tamano: int | None = 10,
) -> tuple[list[RetiroMercaderia], int]:
    """Historial, más reciente primero."""
    consulta = _consulta(punto_de_venta_id, desde, hasta, empleada, es_empresa_propia)
    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()
    consulta = consulta.order_by(
        RetiroMercaderia.timestamp.desc(), RetiroMercaderia.id.desc()
    )
    if tamano is not None:
        consulta = consulta.limit(tamano).offset((pagina - 1) * tamano)
    return list(db.execute(consulta).unique().scalars().all()), total


def reporte(
    db: Session,
    *,
    punto_de_venta_id: int | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    turno_ids: list[int] | None = None,
    pagina: int = 1,
    tamano: int | None = 10,
) -> tuple[list[RetiroMercaderia], int]:
    """
    `turno_ids` acota a esos turnos (lo usa Reportes de Caja, que filtra
    por los turnos del día).

    Para liquidar sueldos: primero las empleadas de esta empresa (ordenadas
    por empleada), después las de la otra empresa (para pasarle el dato).
    """
    consulta = _consulta(punto_de_venta_id, desde, hasta, None, None, turno_ids)
    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()
    consulta = consulta.order_by(
        case((RetiroMercaderia.es_empresa_propia.is_(True), 0), else_=1),
        _nombre_empleada_sql(),
        RetiroMercaderia.timestamp,
    )
    if tamano is not None:
        consulta = consulta.limit(tamano).offset((pagina - 1) * tamano)
    return list(db.execute(consulta).unique().scalars().all()), total
