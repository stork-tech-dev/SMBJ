"""
Reglas de negocio de compras a proveedores.

El flujo es: iniciar borrador → agregar ítems → cerrar. Al cerrar se
actualizan el stock (vía `aplicar_movimiento`) y, opcionalmente, los precios
de las variantes cuyo precio cambió.

Solo puede haber UNA compra en borrador por usuario a la vez. Si el operador
ya tiene una, `iniciar_compra` la devuelve para retomar.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.auditoria import registrar_auditoria
from app.core.utils import ahora_db
from app.models.compra import Compra, CompraItem, EstadoCompra
from app.models.producto import Variante
from app.models.proveedor import EstadoProveedor, Proveedor
from app.models.punto_de_venta import PuntoDeVenta
from app.models.stock import TipoMovimiento
from app.models.usuario import Usuario
from app.services.productos import calcular_precio_venta
from app.services.roles import NoEncontrado, ReglaDeNegocio
from app.services.stock import aplicar_movimiento

# Umbral para el aviso de cambio de precio significativo.
_UMBRAL_PRECIO = Decimal("0.30")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _obtener_compra(db: Session, compra_id: int) -> Compra:
    compra = db.get(Compra, compra_id)
    if compra is None:
        raise NoEncontrado("Compra inexistente")
    return compra


def _validar_borrador_del_autor(compra: Compra, autor: Usuario) -> None:
    if compra.estado != EstadoCompra.BORRADOR:
        raise ReglaDeNegocio("Solo se puede modificar una compra en borrador")
    if compra.usuario_carga_id != autor.id:
        raise ReglaDeNegocio("La compra pertenece a otro usuario")


def _precio_anterior(variante: Variante) -> Decimal | None:
    """Precio USD efectivo de la variante antes de esta compra."""
    return variante.precio_usd_efectivo


def _requiere_confirmacion(anterior: Decimal | None, nuevo: Decimal) -> bool:
    """True si el cambio de precio supera el umbral del 30%."""
    if anterior is None or anterior == 0:
        return False
    return abs(nuevo - anterior) / anterior > _UMBRAL_PRECIO


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

def obtener_borrador_activo(db: Session, usuario_id: int) -> Compra | None:
    """Devuelve la compra en borrador del usuario, o None."""
    return db.execute(
        select(Compra)
        .options(
            joinedload(Compra.proveedor),
            joinedload(Compra.punto_de_venta),
            joinedload(Compra.items).joinedload(CompraItem.variante).joinedload(Variante.producto),
        )
        .where(Compra.usuario_carga_id == usuario_id)
        .where(Compra.estado == EstadoCompra.BORRADOR)
    ).unique().scalars().first()


def obtener_compra_completa(db: Session, compra_id: int) -> Compra:
    """Compra con todos sus joins para la respuesta completa."""
    compra = db.execute(
        select(Compra)
        .options(
            joinedload(Compra.proveedor),
            joinedload(Compra.punto_de_venta),
            joinedload(Compra.usuario_carga),
            joinedload(Compra.items).joinedload(CompraItem.variante).joinedload(Variante.producto),
        )
        .where(Compra.id == compra_id)
    ).unique().scalars().first()
    if compra is None:
        raise NoEncontrado("Compra inexistente")
    return compra


def listar_compras(
    db: Session,
    *,
    proveedor_id: int | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    pagina: int = 1,
    tamano: int = 25,
) -> tuple[list[Compra], int]:
    """Compras cerradas, ordenadas por fecha_carga descendente."""
    base = (
        select(Compra)
        .options(
            joinedload(Compra.proveedor),
            joinedload(Compra.punto_de_venta),
            joinedload(Compra.usuario_carga),
        )
        .where(Compra.estado == EstadoCompra.CERRADA)
    )
    conteo = select(func.count(Compra.id)).where(Compra.estado == EstadoCompra.CERRADA)

    if proveedor_id is not None:
        base = base.where(Compra.proveedor_id == proveedor_id)
        conteo = conteo.where(Compra.proveedor_id == proveedor_id)
    if desde:
        base = base.where(Compra.fecha_carga >= desde)
        conteo = conteo.where(Compra.fecha_carga >= desde)
    if hasta:
        base = base.where(Compra.fecha_carga <= hasta)
        conteo = conteo.where(Compra.fecha_carga <= hasta)

    total = db.execute(conteo).scalar() or 0
    filas = (
        db.execute(
            base.order_by(Compra.fecha_carga.desc())
            .offset((pagina - 1) * tamano)
            .limit(tamano)
        )
        .unique()
        .scalars()
        .all()
    )
    return list(filas), total


# ---------------------------------------------------------------------------
# Operaciones
# ---------------------------------------------------------------------------

def iniciar_compra(
    db: Session,
    autor: Usuario,
    *,
    proveedor_id: int,
    punto_de_venta_id: int,
    fecha_compra: str | None = None,
    notas: str | None = None,
    ip_origen: str | None = None,
) -> Compra:
    """
    Crea una compra en borrador, o devuelve la existente si ya hay una.

    Solo puede haber UNA compra en borrador por usuario a la vez.
    """
    existente = obtener_borrador_activo(db, autor.id)
    if existente is not None:
        return existente

    proveedor = db.get(Proveedor, proveedor_id)
    if proveedor is None:
        raise NoEncontrado("Proveedor inexistente")
    if proveedor.estado != EstadoProveedor.ACTIVO:
        raise ReglaDeNegocio("El proveedor no está activo")

    punto = db.get(PuntoDeVenta, punto_de_venta_id)
    if punto is None:
        raise NoEncontrado("Punto de venta inexistente")

    compra = Compra(
        proveedor_id=proveedor_id,
        punto_de_venta_id=punto_de_venta_id,
        estado=EstadoCompra.BORRADOR,
        fecha_compra=fecha_compra,
        fecha_carga=ahora_db(),
        usuario_carga_id=autor.id,
        notas=notas,
        created_at=ahora_db(),
        updated_at=ahora_db(),
    )
    db.add(compra)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="compra.iniciar",
        entidad="compras",
        entidad_id=compra.id,
        estado_nuevo=compra,
        ip_origen=ip_origen,
    )

    return compra


def agregar_item(
    db: Session,
    autor: Usuario,
    *,
    compra_id: int,
    variante_id: int,
    cantidad: int,
    precio_usd: Decimal,
    es_producto_nuevo: bool = False,
    ip_origen: str | None = None,
) -> tuple[CompraItem, bool]:
    """
    Agrega un ítem a la compra, o suma cantidad si la variante ya existe.

    Retorna (ítem, requiere_confirmacion). Si el cambio de precio supera
    el 30%, `requiere_confirmacion=True` y `precio_actualizado` queda en
    False hasta que se confirme explícitamente.
    """
    compra = _obtener_compra(db, compra_id)
    _validar_borrador_del_autor(compra, autor)

    variante = db.get(Variante, variante_id)
    if variante is None:
        raise NoEncontrado("Variante inexistente")

    anterior = _precio_anterior(variante)
    confirmacion = _requiere_confirmacion(anterior, precio_usd)

    # Si la variante ya está en la compra, sumar cantidad.
    existente = db.execute(
        select(CompraItem)
        .where(CompraItem.compra_id == compra_id)
        .where(CompraItem.variante_id == variante_id)
    ).scalars().first()

    if existente is not None:
        existente.cantidad += cantidad
        existente.precio_usd_nuevo = precio_usd
        existente.precio_usd_anterior = anterior
        if not confirmacion:
            existente.precio_actualizado = (
                anterior is not None and precio_usd != anterior
            )
        else:
            existente.precio_actualizado = False
        compra.updated_at = ahora_db()
        db.flush()
        return existente, confirmacion

    item = CompraItem(
        compra_id=compra_id,
        variante_id=variante_id,
        cantidad=cantidad,
        precio_usd_anterior=anterior,
        precio_usd_nuevo=precio_usd,
        precio_actualizado=(
            not confirmacion and anterior is not None and precio_usd != anterior
        ),
        es_producto_nuevo=es_producto_nuevo,
        created_at=ahora_db(),
    )
    db.add(item)
    compra.updated_at = ahora_db()
    db.flush()

    return item, confirmacion


def confirmar_cambio_precio(
    db: Session,
    autor: Usuario,
    *,
    compra_item_id: int,
    confirmar: bool,
    ip_origen: str | None = None,
) -> CompraItem:
    """
    Confirma o rechaza un cambio de precio que superó el umbral del 30%.
    """
    item = db.get(CompraItem, compra_item_id)
    if item is None:
        raise NoEncontrado("Ítem de compra inexistente")

    compra = _obtener_compra(db, item.compra_id)
    _validar_borrador_del_autor(compra, autor)

    if confirmar:
        item.precio_actualizado = True
    else:
        # Rechaza: vuelve al precio anterior.
        if item.precio_usd_anterior is not None:
            item.precio_usd_nuevo = item.precio_usd_anterior
        item.precio_actualizado = False

    compra.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="compra.confirmar_precio",
        entidad="compra_items",
        entidad_id=item.id,
        estado_nuevo={"confirmar": confirmar, "precio_usd_nuevo": str(item.precio_usd_nuevo)},
        ip_origen=ip_origen,
    )

    return item


def modificar_item(
    db: Session,
    autor: Usuario,
    *,
    compra_id: int,
    item_id: int,
    cantidad: int | None = None,
    precio_usd: Decimal | None = None,
    ip_origen: str | None = None,
) -> tuple[CompraItem, bool]:
    """Modifica cantidad y/o precio de un ítem existente."""
    compra = _obtener_compra(db, compra_id)
    _validar_borrador_del_autor(compra, autor)

    item = db.get(CompraItem, item_id)
    if item is None or item.compra_id != compra_id:
        raise NoEncontrado("Ítem de compra inexistente")

    confirmacion = False

    if cantidad is not None:
        item.cantidad = cantidad

    if precio_usd is not None:
        anterior = item.precio_usd_anterior
        confirmacion = _requiere_confirmacion(anterior, precio_usd)
        item.precio_usd_nuevo = precio_usd
        if not confirmacion:
            item.precio_actualizado = (
                anterior is not None and precio_usd != anterior
            )
        else:
            item.precio_actualizado = False

    compra.updated_at = ahora_db()
    db.flush()

    return item, confirmacion


def quitar_item(
    db: Session,
    autor: Usuario,
    *,
    compra_id: int,
    item_id: int,
    ip_origen: str | None = None,
) -> None:
    """Elimina un ítem de la compra."""
    compra = _obtener_compra(db, compra_id)
    _validar_borrador_del_autor(compra, autor)

    item = db.get(CompraItem, item_id)
    if item is None or item.compra_id != compra_id:
        raise NoEncontrado("Ítem de compra inexistente")

    db.delete(item)
    compra.updated_at = ahora_db()
    db.flush()


def cerrar_compra(
    db: Session,
    autor: Usuario,
    *,
    compra_id: int,
    ip_origen: str | None = None,
) -> Compra:
    """
    Cierra la compra: actualiza stock y precios en una sola transacción.

    Por cada ítem:
    1. Crea un movimiento de stock INGRESO_PROVEEDOR.
    2. Si `precio_actualizado`: actualiza precio_usd en la variante (y en
       el producto si es variante base) y recalcula precio_venta.
    """
    compra = obtener_compra_completa(db, compra_id)
    _validar_borrador_del_autor(compra, autor)

    if not compra.items:
        raise ReglaDeNegocio("La compra no tiene ítems")

    for item in compra.items:
        # 1. Movimiento de stock
        aplicar_movimiento(
            db, autor,
            tipo=TipoMovimiento.INGRESO_PROVEEDOR,
            variante_id=item.variante_id,
            cantidad=item.cantidad,
            punto_venta_destino_id=compra.punto_de_venta_id,
            compra_id=compra.id,
            ip_origen=ip_origen,
        )

        # 2. Actualización de precio
        if item.precio_actualizado:
            variante = item.variante
            dolar = compra.proveedor.dolar_actual
            # Calcular ANTES de asignar: la lectura de ConfiguracionSistema
            # dispara autoflush, y si precio_usd ya cambió sin precio_venta
            # el CHECK constraint lo rechaza.
            nuevo_venta = calcular_precio_venta(
                db, item.precio_usd_nuevo, dolar
            )
            if variante.es_base:
                # La variante base no tiene precio propio: el precio vive
                # en el producto. Actualizarlo ahí.
                producto = variante.producto
                producto.precio_usd = item.precio_usd_nuevo
                producto.precio_venta = nuevo_venta
            else:
                variante.precio_usd = item.precio_usd_nuevo
                variante.precio_venta = nuevo_venta

    compra.estado = EstadoCompra.CERRADA
    compra.fecha_cierre = ahora_db()
    compra.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="compra.cerrada",
        entidad="compras",
        entidad_id=compra.id,
        estado_nuevo=compra,
        ip_origen=ip_origen,
    )

    return compra


def eliminar_borrador(
    db: Session,
    autor: Usuario,
    *,
    compra_id: int,
    ip_origen: str | None = None,
) -> None:
    """Elimina lógicamente un borrador (no se borra físicamente)."""
    compra = _obtener_compra(db, compra_id)
    _validar_borrador_del_autor(compra, autor)

    compra.estado = EstadoCompra.ELIMINADA
    compra.updated_at = ahora_db()
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="compra.eliminada",
        entidad="compras",
        entidad_id=compra.id,
        ip_origen=ip_origen,
    )
