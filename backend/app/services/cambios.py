"""
Service del módulo de cambios de producto.

Los cuatro tipos tienen reglas de valuación distintas para el precio
reconocido del ítem devuelto — ver calcular_precio_reconocido(). No mezclar.

Reglas globales:
- El cambio puede hacerse en cualquier local de la empresa.
- Si pasaron 30 días desde la venta: aviso pero NO bloqueo.
- Si el producto ya fue cambiado antes: aviso con contador pero NO bloqueo.
- La diferencia a favor del cliente NO se devuelve en dinero.
- Todo el efecto (stock, puntos, nuevo código) va en una sola transacción.
"""

import secrets
from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.utils import ahora_db
from app.models.cambio import (
    Cambio,
    CambioItemDevuelto,
    CambioItemNuevo,
    EstadoCambio,
    TipoCambio,
    TipoPromo,
)
from app.models.categoria import Categoria
from app.models.producto import Variante
from app.models.stock import TipoMovimiento
from app.models.usuario import Usuario
from app.models.venta import EstadoVenta, Venta, VentaItem
from app.services import clientes as servicio_clientes
from app.services import stock as servicio_stock
from app.services.roles import NoEncontrado, ReglaDeNegocio
from app.services.ventas import generar_codigo_cambio

_PLAZO_DIAS = 30
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O ni 1/I/L


# ── Utilidades ──────────────────────────────────────────────────────────────


def _variante(db: Session, variante_id: int) -> Variante:
    v = db.execute(
        select(Variante)
        .where(Variante.id == variante_id)
        .options(joinedload(Variante.producto))
    ).unique().scalar_one_or_none()
    if v is None:
        raise NoEncontrado(f"Variante {variante_id} no encontrada")
    return v


def _material_de_variante(db: Session, variante: Variante) -> Categoria | None:
    """Nivel 1 del árbol de categorías — el 'Material' del producto."""
    cat = variante.producto.categoria
    if cat is None:
        return None
    while cat.nivel > 1 and cat.parent_id is not None:
        parent = db.get(Categoria, cat.parent_id)
        if parent is None:
            break
        cat = parent
    return cat if cat.nivel == 1 else None


def _mismo_material(mat_a: Categoria | None, mat_b: Categoria | None) -> bool:
    if mat_a is None or mat_b is None:
        return False
    return mat_a.id == mat_b.id


def _generar_codigo_cambio_nuevo(db: Session) -> str:
    """Código único de 8 chars para los productos nuevos del cambio."""
    for _ in range(10):
        codigo = "".join(secrets.choice(_ALFABETO) for _ in range(8))
        existe_venta = db.execute(
            select(Venta.id).where(Venta.codigo_cambio == codigo)
        ).scalar_one_or_none()
        existe_cambio = db.execute(
            select(Cambio.id).where(Cambio.codigo_cambio_nuevo == codigo)
        ).scalar_one_or_none()
        if existe_venta is None and existe_cambio is None:
            return codigo
    raise ReglaDeNegocio(
        "No se pudo generar un código de cambio único: reintentá la operación"
    )


# ── Valuación del ítem devuelto ─────────────────────────────────────────────


def calcular_precio_reconocido(
    tipo: TipoCambio,
    venta_item: VentaItem | None,
    variante_devuelta: Variante,
    variante_nueva: Variante,
    material_devuelto: Categoria | None,
    material_nuevo: Categoria | None,
) -> Decimal:
    """
    CAMBIO COMÚN (comun):
      precio_lista del venta_item — el valor de lista al momento de la compra,
      SIN descuentos. Nunca precio_final.

    CAMBIO DE PROMOCIÓN (promocion):
      precio_lista del venta_item × porcentaje según tipo de promo y material:
        2x1, mismo material:  100%
        2x1, otro material:   50%
        3x2, mismo material:  100%
        3x2, otro material:   66%

    CAMBIO POR FALLA (falla):
      Precio de venta ACTUAL de la variante devuelta (sin historial).
      Siempre 100%.

    GIFT CARD FÍSICA (gift_card_fisica):
      Precio de venta ACTUAL. Siempre 100%.
    """
    if tipo == TipoCambio.COMUN:
        if venta_item is None:
            raise ReglaDeNegocio("El cambio común requiere el ítem de venta original")
        return Decimal(venta_item.precio_lista)

    if tipo == TipoCambio.PROMOCION:
        if venta_item is None:
            raise ReglaDeNegocio("El cambio de promoción requiere el ítem de venta original")
        precio_base = Decimal(venta_item.precio_lista)
        # Determinar tipo de promo del ítem
        from app.models.venta import MotivoDescuento  # noqa — import local para evitar ciclos
        tipo_promo_str = None
        if venta_item.en_promocion and venta_item.venta:
            tipo_promo_str = (
                venta_item.venta.promocion.tipo.value
                if venta_item.venta and venta_item.venta.promocion
                else None
            )
        mismo = _mismo_material(material_devuelto, material_nuevo)
        if tipo_promo_str == "tres_x_dos":
            porcentaje = Decimal("1.00") if mismo else Decimal("0.66")
        else:
            # dos_x_uno o sin dato: usar regla de 2x1
            porcentaje = Decimal("1.00") if mismo else Decimal("0.50")
        return (precio_base * porcentaje).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)

    if tipo in (TipoCambio.FALLA, TipoCambio.GIFT_CARD_FISICA):
        return Decimal(variante_devuelta.precio_venta_efectivo)

    raise ReglaDeNegocio(f"Tipo de cambio desconocido: {tipo}")


def es_mismo_producto_sin_diferencia(
    db: Session,
    variante_devuelta: Variante,
    variante_nueva: Variante,
) -> bool:
    """
    TRUE si ambas variantes pertenecen al mismo producto padre y TODAS las
    variantes de ese producto heredan el precio (precio_usd=NULL).

    Cuando aplica: el precio_reconocido = precio_actual de la variante nueva
    (el cliente no paga diferencia aunque el precio haya subido).
    """
    if variante_devuelta.producto_id != variante_nueva.producto_id:
        return False
    variantes = db.execute(
        select(Variante).where(Variante.producto_id == variante_devuelta.producto_id)
    ).scalars().all()
    return all(v.precio_usd is None and v.precio_venta is None for v in variantes)


# ── Búsqueda de venta para cambio ──────────────────────────────────────────


def buscar_ventas_para_cambio(
    db: Session,
    punto_de_venta_id: int,
    fecha_desde: date,
    fecha_hasta: date,
    sku: str | None = None,
    descripcion: str | None = None,
) -> list[Venta]:
    """
    Ventas del local en el rango de fechas con codigo_cambio_activo=TRUE.
    Filtros opcionales por SKU o descripción del producto vendido.
    """
    consulta = (
        select(Venta)
        .where(
            Venta.punto_de_venta_id == punto_de_venta_id,
            Venta.estado == EstadoVenta.CONFIRMADA,
            Venta.codigo_cambio_activo.is_(True),
            Venta.created_at >= fecha_desde,
            Venta.created_at < fecha_hasta + timedelta(days=1),
        )
        .options(
            joinedload(Venta.items).joinedload(VentaItem.variante).joinedload(Variante.producto)
        )
        .order_by(Venta.created_at.desc())
        .limit(50)
    )

    if sku or descripcion:
        from sqlalchemy import exists, ilike  # noqa — import local
        from app.models.producto import Producto

        sub = select(VentaItem.venta_id).join(
            Variante, VentaItem.variante_id == Variante.id
        ).join(Producto, Variante.producto_id == Producto.id)

        if sku:
            sku_clean = f"%{sku.strip()}%"
            sub = sub.where(Variante.codigo_completo.ilike(sku_clean))
        if descripcion:
            desc_clean = f"%{descripcion.strip()}%"
            sub = sub.where(Producto.descripcion.ilike(desc_clean))

        consulta = consulta.where(Venta.id.in_(sub))

    return db.execute(consulta).unique().scalars().all()


# ── Operaciones principales ─────────────────────────────────────────────────


def obtener_cambio(db: Session, cambio_id: int) -> Cambio:
    cambio = db.execute(
        select(Cambio)
        .where(Cambio.id == cambio_id)
        .options(
            joinedload(Cambio.items_devueltos).joinedload(CambioItemDevuelto.variante)
            .joinedload(Variante.producto),
            joinedload(Cambio.items_nuevos).joinedload(CambioItemNuevo.variante)
            .joinedload(Variante.producto),
            joinedload(Cambio.venta_origen),
            joinedload(Cambio.punto_de_venta),
            joinedload(Cambio.usuario),
            joinedload(Cambio.autorizador),
            joinedload(Cambio.medio_pago_diferencia),
        )
    ).unique().scalar_one_or_none()
    if cambio is None:
        raise NoEncontrado(f"Cambio {cambio_id} no encontrado")
    return cambio


def iniciar_cambio(
    db: Session,
    autor: Usuario,
    tipo: TipoCambio,
    punto_de_venta_id: int,
    codigo_cambio: str | None = None,
    autorizador_id: int | None = None,
    ip_origen: str | None = None,
) -> tuple[Cambio, list[str]]:
    """
    Crea un cambio en estado 'pendiente'.

    Retorna (cambio, avisos): los avisos son mensajes informativos (plazo
    vencido, cambios previos) que el frontend debe mostrar pero no bloquean.
    """
    avisos: list[str] = []
    venta_origen = None

    if tipo in (TipoCambio.COMUN, TipoCambio.PROMOCION, TipoCambio.GIFT_CARD_FISICA):
        if not codigo_cambio:
            raise ReglaDeNegocio(
                "Ingresá el código de cambio del ticket"
            )
        codigo_clean = codigo_cambio.strip().upper()
        venta_origen = db.execute(
            select(Venta)
            .where(Venta.codigo_cambio == codigo_clean)
            .options(
                joinedload(Venta.items).joinedload(VentaItem.variante)
                .joinedload(Variante.producto)
            )
        ).unique().scalar_one_or_none()

        if venta_origen is None:
            raise NoEncontrado(f"No hay ninguna venta con el código '{codigo_clean}'")
        if not venta_origen.codigo_cambio_activo:
            raise ReglaDeNegocio(
                "Este código de cambio ya fue utilizado o la venta fue anulada"
            )
        if venta_origen.estado != EstadoVenta.CONFIRMADA:
            raise ReglaDeNegocio("Solo se pueden cambiar artículos de ventas confirmadas")

        # Aviso de plazo
        dias = (ahora_db().date() - venta_origen.created_at.date()).days
        if dias > _PLAZO_DIAS:
            avisos.append(
                f"Pasaron {dias} días desde la venta (el plazo habitual es {_PLAZO_DIAS} días). "
                "Podés continuar igual o cancelar."
            )

    elif tipo == TipoCambio.FALLA:
        if autorizador_id is None:
            raise ReglaDeNegocio("El cambio por falla requiere un autorizador")
        autorizador = db.get(Usuario, autorizador_id)
        if autorizador is None:
            raise NoEncontrado("Autorizador no encontrado")

    ahora = ahora_db()
    cambio = Cambio(
        tipo=tipo,
        venta_origen_id=venta_origen.id if venta_origen else None,
        punto_de_venta_id=punto_de_venta_id,
        usuario_id=autor.id,
        autorizador_id=autorizador_id,
        estado=EstadoCambio.PENDIENTE,
        created_at=ahora,
        updated_at=ahora,
    )
    db.add(cambio)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="cambio.iniciado",
        entidad="cambios",
        entidad_id=cambio.id,
        estado_anterior=None,
        estado_nuevo={"tipo": tipo.value, "venta_origen_id": cambio.venta_origen_id},
        ip_origen=ip_origen,
    )

    return cambio, avisos


def agregar_item_devuelto(
    db: Session,
    cambio: Cambio,
    variante_id: int,
    venta_item_id: int | None = None,
) -> tuple[CambioItemDevuelto, list[str]]:
    """
    Agrega un ítem devuelto al cambio pendiente.

    Para tipos comun/promocion: venta_item_id es obligatorio (valida que
    pertenezca a la venta origen). Para falla: puede ser None.

    Retorna (item, avisos) — avisos incluye "ya fue cambiado N veces" si aplica.
    """
    if cambio.estado != EstadoCambio.PENDIENTE:
        raise ReglaDeNegocio("Solo se pueden agregar ítems a un cambio pendiente")

    avisos: list[str] = []
    variante = _variante(db, variante_id)
    venta_item = None

    if cambio.tipo in (TipoCambio.COMUN, TipoCambio.PROMOCION, TipoCambio.GIFT_CARD_FISICA):
        if venta_item_id is None:
            raise ReglaDeNegocio(
                f"El cambio '{cambio.tipo.value}' requiere el ítem de venta original"
            )
        venta_item = db.get(VentaItem, venta_item_id)
        if venta_item is None:
            raise NoEncontrado("Ítem de venta no encontrado")
        if cambio.venta_origen_id and venta_item.venta_id != cambio.venta_origen_id:
            raise ReglaDeNegocio("El ítem no pertenece a la venta de origen del cambio")
        if venta_item.variante_id != variante_id:
            raise ReglaDeNegocio("El ítem de venta no corresponde a la variante indicada")

    # Contar cambios previos de esta variante
    cambios_previos = db.execute(
        select(CambioItemDevuelto)
        .join(Cambio, CambioItemDevuelto.cambio_id == Cambio.id)
        .where(
            CambioItemDevuelto.variante_id == variante_id,
            Cambio.estado == EstadoCambio.CONFIRMADO,
        )
    ).scalars().all()

    if cambios_previos:
        n = len(cambios_previos)
        avisos.append(f"Este producto ya fue cambiado {n} vez{'es' if n > 1 else ''} antes.")

    material = _material_de_variante(db, variante)

    # Valor reconocido — necesitamos una variante nueva de referencia para
    # el cálculo de promo; si todavía no hay items nuevos, usamos la misma
    # variante devuelta (se recalcula al agregar items nuevos si hace falta).
    variante_nueva_ref = variante  # placeholder para calcular_precio_reconocido
    mat_nueva_ref = material

    precio = calcular_precio_reconocido(
        cambio.tipo,
        venta_item,
        variante,
        variante_nueva_ref,
        material,
        mat_nueva_ref,
    )

    tipo_promo = None
    en_promocion = False
    if venta_item and venta_item.en_promocion:
        en_promocion = True
        if venta_item.venta and venta_item.venta.promocion:
            tipo_promo_val = venta_item.venta.promocion.tipo.value
            tipo_promo = TipoPromo(tipo_promo_val) if tipo_promo_val in TipoPromo._value2member_map_ else None

    item = CambioItemDevuelto(
        cambio_id=cambio.id,
        venta_item_id=venta_item_id,
        variante_id=variante_id,
        precio_reconocido=precio,
        en_promocion=en_promocion,
        tipo_promo=tipo_promo,
        material_id=material.id if material else None,
    )
    db.add(item)
    db.flush()
    return item, avisos


def agregar_item_nuevo(
    db: Session,
    cambio: Cambio,
    variante_id: int,
) -> CambioItemNuevo:
    """Agrega un producto nuevo que el cliente se lleva."""
    if cambio.estado != EstadoCambio.PENDIENTE:
        raise ReglaDeNegocio("Solo se pueden agregar ítems a un cambio pendiente")

    variante = _variante(db, variante_id)
    material = _material_de_variante(db, variante)

    precio_actual = Decimal(variante.precio_venta_efectivo)

    item = CambioItemNuevo(
        cambio_id=cambio.id,
        variante_id=variante_id,
        precio_actual=precio_actual,
        material_id=material.id if material else None,
    )
    db.add(item)
    db.flush()
    return item


def calcular_diferencia(db: Session, cambio: Cambio) -> dict:
    """
    Calcula la diferencia actual del cambio pendiente.

    Para cambios de promoción con items nuevos: recalcula el precio reconocido
    de los items devueltos tomando el material del primer item nuevo (para
    aplicar el % correcto según mismo/distinto material).
    """
    db.refresh(cambio)

    total_devuelto = Decimal("0")
    for item in cambio.items_devueltos:
        # Para promo: recalcular con el material del primer ítem nuevo si existe
        if cambio.tipo == TipoCambio.PROMOCION and cambio.items_nuevos:
            item_nuevo = cambio.items_nuevos[0]
            variante_nueva = _variante(db, item_nuevo.variante_id)
            mat_nueva = db.get(Categoria, item_nuevo.material_id) if item_nuevo.material_id else None
            variante_dev = _variante(db, item.variante_id)
            mat_dev = db.get(Categoria, item.material_id) if item.material_id else None
            venta_item = db.get(VentaItem, item.venta_item_id) if item.venta_item_id else None
            precio = calcular_precio_reconocido(
                cambio.tipo, venta_item, variante_dev, variante_nueva, mat_dev, mat_nueva
            )
            item.precio_reconocido = precio
            db.flush()
        total_devuelto += item.precio_reconocido

    total_nuevo = sum(Decimal(i.precio_actual) for i in cambio.items_nuevos)
    diferencia = total_nuevo - total_devuelto
    a_favor = diferencia < 0

    return {
        "diferencia": diferencia,
        "total_devuelto": total_devuelto,
        "total_nuevo": total_nuevo,
        "a_favor_cliente": a_favor,
        "mensaje": (
            "La diferencia queda a favor del cliente. No se devuelve en dinero: "
            "el cliente puede llevar más productos o la pierde."
        ) if a_favor else None,
    }


def confirmar_cambio(
    db: Session,
    autor: Usuario,
    cambio: Cambio,
    medio_pago_diferencia_id: int | None = None,
    plan_cuotas_diferencia_id: int | None = None,
    notas: str | None = None,
    ip_origen: str | None = None,
) -> Cambio:
    """
    Confirma el cambio: mueve el stock, ajusta puntos y genera el código nuevo.

    Todo en una sola transacción — si algo falla, nada se aplica.
    """
    if cambio.estado != EstadoCambio.PENDIENTE:
        raise ReglaDeNegocio("Solo se pueden confirmar cambios en estado pendiente")
    if not cambio.items_devueltos:
        raise ReglaDeNegocio("El cambio debe tener al menos un ítem devuelto")
    if not cambio.items_nuevos:
        raise ReglaDeNegocio("El cambio debe tener al menos un ítem nuevo")

    calculo = calcular_diferencia(db, cambio)
    diferencia = calculo["diferencia"]

    if diferencia > 0 and medio_pago_diferencia_id is None:
        raise ReglaDeNegocio(
            f"La diferencia es ${diferencia:.2f}. Indicá el medio de pago."
        )

    antes = snapshot(cambio)

    # ── Stock: devolver ítems entregados por el cliente ─────────────────────
    conteo_devueltos: dict[int, int] = {}
    for item in cambio.items_devueltos:
        conteo_devueltos[item.variante_id] = conteo_devueltos.get(item.variante_id, 0) + 1

    for variante_id, cantidad in conteo_devueltos.items():
        servicio_stock.aplicar_movimiento(
            db,
            autor,
            tipo=TipoMovimiento.DEVOLUCION_VENTA,
            variante_id=variante_id,
            cantidad=cantidad,
            punto_venta_destino_id=cambio.punto_de_venta_id,
            referencia_venta_id=cambio.venta_origen_id,
            notas=f"Cambio #{cambio.id}: devolución",
            ip_origen=ip_origen,
        )

    # ── Stock: descontar ítems nuevos que se lleva el cliente ───────────────
    conteo_nuevos: dict[int, int] = {}
    for item in cambio.items_nuevos:
        conteo_nuevos[item.variante_id] = conteo_nuevos.get(item.variante_id, 0) + 1

    for variante_id, cantidad in conteo_nuevos.items():
        servicio_stock.aplicar_movimiento(
            db,
            autor,
            tipo=TipoMovimiento.VENTA,
            variante_id=variante_id,
            cantidad=cantidad,
            punto_venta_origen_id=cambio.punto_de_venta_id,
            referencia_venta_id=None,
            notas=f"Cambio #{cambio.id}: productos nuevos",
            ip_origen=ip_origen,
        )

    # ── Puntos: restar los de los ítems devueltos, sumar los de los nuevos ──
    venta_origen = cambio.venta_origen
    if venta_origen and venta_origen.cliente_id:
        # Estimación proporcional de puntos a restar (por el valor devuelto)
        puntos_a_restar = servicio_clientes.puntos_por_venta(calculo["total_devuelto"])
        if puntos_a_restar > 0:
            servicio_clientes.registrar_movimiento_puntos(
                db,
                autor,
                cliente_id=venta_origen.cliente_id,
                tipo=__import__("app.models.cliente", fromlist=["TipoPunto"]).TipoPunto.AJUSTE,
                cantidad=-puntos_a_restar,
                venta_id=venta_origen.id,
                descripcion=f"Cambio #{cambio.id}: ítems devueltos",
                ip_origen=ip_origen,
            )
        puntos_nuevos = servicio_clientes.puntos_por_venta(calculo["total_nuevo"])
        if puntos_nuevos > 0:
            servicio_clientes.registrar_movimiento_puntos(
                db,
                autor,
                cliente_id=venta_origen.cliente_id,
                tipo=__import__("app.models.cliente", fromlist=["TipoPunto"]).TipoPunto.ACUMULACION,
                cantidad=puntos_nuevos,
                venta_id=venta_origen.id,
                descripcion=f"Cambio #{cambio.id}: ítems nuevos",
                ip_origen=ip_origen,
            )

    # ── Generar nuevo código de cambio para los ítems nuevos ────────────────
    codigo_nuevo = _generar_codigo_cambio_nuevo(db)

    # ── Actualizar contador de cambios previos en la venta origen ───────────
    previos = db.execute(
        select(Cambio)
        .where(
            Cambio.venta_origen_id == cambio.venta_origen_id,
            Cambio.estado == EstadoCambio.CONFIRMADO,
            Cambio.id != cambio.id,
        )
    ).scalars().all()
    cambio.contador_cambios_previos = len(previos)

    # ── Cerrar el cambio ────────────────────────────────────────────────────
    cambio.diferencia = diferencia
    cambio.medio_pago_diferencia_id = medio_pago_diferencia_id if diferencia > 0 else None
    cambio.plan_cuotas_diferencia_id = plan_cuotas_diferencia_id if diferencia > 0 else None
    cambio.codigo_cambio_nuevo = codigo_nuevo
    cambio.notas = notas
    cambio.estado = EstadoCambio.CONFIRMADO
    cambio.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="cambio.confirmado",
        entidad="cambios",
        entidad_id=cambio.id,
        estado_anterior=antes,
        estado_nuevo=snapshot(cambio),
        ip_origen=ip_origen,
    )

    return cambio


def cancelar_cambio(
    db: Session,
    autor: Usuario,
    cambio: Cambio,
    ip_origen: str | None = None,
) -> Cambio:
    """Cancela un cambio pendiente sin efectos en stock ni puntos."""
    if cambio.estado != EstadoCambio.PENDIENTE:
        raise ReglaDeNegocio("Solo se pueden cancelar cambios en estado pendiente")

    antes = snapshot(cambio)
    cambio.estado = EstadoCambio.CANCELADO
    cambio.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="cambio.cancelado",
        entidad="cambios",
        entidad_id=cambio.id,
        estado_anterior=antes,
        estado_nuevo=snapshot(cambio),
        ip_origen=ip_origen,
    )
    return cambio


def listar_cambios(
    db: Session,
    punto_de_venta_id: int | None = None,
    tipo: TipoCambio | None = None,
    estado: EstadoCambio | None = None,
    pagina: int = 1,
    tamano: int = 20,
) -> tuple[list[Cambio], int]:
    from sqlalchemy import func as sqlfunc

    consulta = (
        select(Cambio)
        .options(
            joinedload(Cambio.punto_de_venta),
            joinedload(Cambio.usuario),
            joinedload(Cambio.venta_origen),
        )
        .order_by(Cambio.created_at.desc())
    )

    if punto_de_venta_id:
        consulta = consulta.where(Cambio.punto_de_venta_id == punto_de_venta_id)
    if tipo:
        consulta = consulta.where(Cambio.tipo == tipo)
    if estado:
        consulta = consulta.where(Cambio.estado == estado)

    total = db.execute(
        select(sqlfunc.count()).select_from(consulta.subquery())
    ).scalar_one()

    filas = (
        db.execute(consulta.offset((pagina - 1) * tamano).limit(tamano))
        .unique().scalars().all()
    )
    return filas, total
