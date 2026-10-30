"""
Service del módulo de cambios de producto.

Los cuatro tipos tienen reglas de valuación distintas para el precio
reconocido del ítem devuelto — ver calcular_precio_reconocido(). No mezclar.

Reglas globales:
- El cambio puede hacerse en cualquier local de la empresa.
- Puede juntar varios tickets (`cambio_origenes`): lo devuelto de todos suma.
  Todos del mismo tipo de cambio y de compras del mismo cliente.
- Si pasaron 30 días desde la venta: aviso pero NO bloqueo.
- Si el producto ya fue cambiado antes: aviso con contador pero NO bloqueo.
- La diferencia a favor del cliente NO se devuelve en dinero.
- Todo el efecto (stock, puntos, nuevo código) va en una sola transacción.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.utils import ahora_db
from app.models.cambio import (
    Cambio,
    CambioItemDevuelto,
    CambioItemNuevo,
    CambioOrigen,
    EstadoCambio,
    TipoCambio,
    TipoPromo,
)
from app.models.categoria import Categoria
from app.models.operaciones_caja import RetiroMercaderia
from app.models.producto import Variante
from app.models.stock import TipoMovimiento
from app.models.usuario import Usuario
from app.models.venta import EstadoVenta, Venta, VentaItem
from app.services import clientes as servicio_clientes
from app.services import configuracion as servicio_configuracion
from app.services import stock as servicio_stock
from app.services.roles import NoEncontrado, ReglaDeNegocio
from app.services.ventas import generar_codigo_cambio


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


def _venta_items_ya_devueltos(excepto_cambio_id: int | None = None):
    """
    Subconsulta: ítems de venta ya devueltos en un cambio CONFIRMADO.

    Un cambio pendiente es un cambio sin realizar: no reserva nada. Hasta que
    se confirma, sus ítems siguen siendo de la venta original y otro cambio
    puede tomarlos (`confirmar_cambio` vuelve a controlar al confirmar).
    """
    consulta = (
        select(CambioItemDevuelto.venta_item_id)
        .join(Cambio, CambioItemDevuelto.cambio_id == Cambio.id)
        .where(
            CambioItemDevuelto.venta_item_id.is_not(None),
            Cambio.estado == EstadoCambio.CONFIRMADO,
        )
    )
    if excepto_cambio_id is not None:
        consulta = consulta.where(Cambio.id != excepto_cambio_id)
    return consulta


def _retiro_ya_devuelto(db: Session, retiro_id: int, excepto_cambio_id: int | None = None) -> bool:
    """Si el producto de ese retiro ya se devolvió en un cambio CONFIRMADO."""
    consulta = (
        select(CambioItemDevuelto.id)
        .join(Cambio, CambioItemDevuelto.cambio_id == Cambio.id)
        .where(
            CambioItemDevuelto.retiro_mercaderia_id == retiro_id,
            Cambio.estado == EstadoCambio.CONFIRMADO,
        )
    )
    if excepto_cambio_id is not None:
        consulta = consulta.where(Cambio.id != excepto_cambio_id)
    return db.execute(consulta.limit(1)).first() is not None


def _en_este_cambio(db: Session, cambio: Cambio) -> set[int]:
    """
    Ítems de venta que este mismo cambio ya tiene como devueltos. Consulta la
    base y no `cambio.items_devueltos`, que no se entera de lo agregado en
    la misma sesión.
    """
    return set(db.execute(
        select(CambioItemDevuelto.venta_item_id).where(
            CambioItemDevuelto.cambio_id == cambio.id,
            CambioItemDevuelto.venta_item_id.is_not(None),
        )
    ).scalars())


def _retiro_en_este_cambio(db: Session, cambio: Cambio, retiro_id: int) -> bool:
    return db.execute(
        select(CambioItemDevuelto.id).where(
            CambioItemDevuelto.cambio_id == cambio.id,
            CambioItemDevuelto.retiro_mercaderia_id == retiro_id,
        ).limit(1)
    ).first() is not None


def _ids_ventas_origen(db: Session, cambio: Cambio) -> list[int]:
    """Las ventas de los tickets del cambio. Consulta la base: un origen
    recién agregado en la misma sesión no está en `cambio.origenes`."""
    return list(db.execute(
        select(CambioOrigen.venta_id).where(
            CambioOrigen.cambio_id == cambio.id, CambioOrigen.venta_id.is_not(None)
        )
    ).scalars())


def _ids_retiros_origen(db: Session, cambio: Cambio) -> list[int]:
    return list(db.execute(
        select(CambioOrigen.retiro_mercaderia_id).where(
            CambioOrigen.cambio_id == cambio.id,
            CambioOrigen.retiro_mercaderia_id.is_not(None),
        )
    ).scalars())


def _venta_item_disponible(db: Session, cambio: Cambio, variante_id: int) -> int:
    """
    El ítem de alguna de las ventas de origen para esta variante que todavía
    no se devolvió en un cambio confirmado ni está ya en este mismo cambio.

    El frontend nunca manda `venta_item_id`: el buscador de producto del
    wizard es el catálogo general (`/productos/variantes`), que no sabe
    nada de la venta de origen. Se resuelve acá porque el service sí tiene
    los dos datos (la venta y la variante elegida) y evita que se devuelva
    dos veces la misma unidad física cuando la venta tenía la variante
    repetida (ej. compró dos anillos iguales).
    """
    ya_usados = _venta_items_ya_devueltos()
    en_este = _en_este_cambio(db, cambio)
    disponible = db.execute(
        select(VentaItem.id)
        .where(
            VentaItem.venta_id.in_(_ids_ventas_origen(db, cambio)),
            VentaItem.variante_id == variante_id,
            VentaItem.id.not_in(ya_usados),
            *([VentaItem.id.not_in(en_este)] if en_este else []),
        )
        .order_by(VentaItem.id)
        .limit(1)
    ).scalar_one_or_none()
    if disponible is None:
        raise ReglaDeNegocio(
            "No se encontró en los tickets del cambio un ítem de esa variante "
            "disponible para devolver (puede que ya se haya devuelto)."
        )
    return disponible


def _mismo_material(mat_a: Categoria | None, mat_b: Categoria | None) -> bool:
    if mat_a is None or mat_b is None:
        return False
    return mat_a.id == mat_b.id


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
            joinedload(Cambio.origenes).joinedload(CambioOrigen.venta),
            joinedload(Cambio.origenes).joinedload(CambioOrigen.retiro_mercaderia),
            joinedload(Cambio.punto_de_venta),
            joinedload(Cambio.usuario),
            joinedload(Cambio.autorizador),
            joinedload(Cambio.medio_pago_diferencia),
        )
    ).unique().scalar_one_or_none()
    if cambio is None:
        raise NoEncontrado(f"Cambio {cambio_id} no encontrado")
    return cambio


def _origen_por_codigo(
    db: Session, codigo_cambio: str
) -> tuple[Venta | None, RetiroMercaderia | None]:
    """
    La venta del código de cambio del ticket o, si no hay, el retiro de
    mercadería de empleada con ese código (sesión 09: un producto para regalo
    que quien lo recibió viene a cambiar, como un cambio común al precio de
    lista). NoEncontrado si no es ninguno de los dos.
    """
    codigo_clean = codigo_cambio.strip().upper()
    venta = db.execute(
        select(Venta)
        .where(Venta.codigo_cambio == codigo_clean)
        .options(
            joinedload(Venta.items).joinedload(VentaItem.variante)
            .joinedload(Variante.producto)
        )
    ).unique().scalar_one_or_none()
    if venta is not None:
        return venta, None

    retiro = db.execute(
        select(RetiroMercaderia).where(RetiroMercaderia.codigo_cambio == codigo_clean)
    ).scalar_one_or_none()
    if retiro is None:
        raise NoEncontrado(f"No hay ninguna venta con el código '{codigo_clean}'")
    return None, retiro


def _validar_venta_origen(venta: Venta) -> None:
    """Una venta sirve de origen si su código sigue activo y está confirmada."""
    if not venta.codigo_cambio_activo:
        raise ReglaDeNegocio(
            "Este código de cambio ya fue utilizado o la venta fue anulada"
        )
    if venta.estado != EstadoVenta.CONFIRMADA:
        raise ReglaDeNegocio("Solo se pueden cambiar artículos de ventas confirmadas")


def _descripcion(variante: Variante) -> str:
    descripcion = variante.producto.descripcion
    if variante.descripcion_sufijo:
        descripcion = f"{descripcion} — {variante.descripcion_sufijo}"
    return descripcion


def items_del_ticket(db: Session, codigo_cambio: str) -> dict:
    """
    Los productos del ticket del código de cambio, para elegir en la primera
    pantalla del cambio cuáles devuelve el cliente. Cada ítem dice si todavía
    se puede devolver (`disponible`): una unidad ya devuelta en otro cambio
    no cancelado no vuelve a ofrecerse. Mismas validaciones que
    `iniciar_cambio`, para que el error aparezca apenas se ingresa el código.
    """
    venta, retiro = _origen_por_codigo(db, codigo_cambio)

    def _item(variante, venta_item_id, precio, disponible, retiro_id=None):
        return {
            "venta_item_id": venta_item_id,
            "retiro_mercaderia_id": retiro_id,
            "variante_id": variante.id,
            "descripcion": _descripcion(variante),
            "codigo": variante.codigo_con_verificador,
            "foto_url": variante.foto_url,
            "precio": precio,
            "disponible": disponible,
        }

    if retiro is not None:
        variante = _variante(db, retiro.variante_id)
        return {
            "origen": "retiro",
            "items": [_item(variante, None, retiro.precio_lista,
                            not _retiro_ya_devuelto(db, retiro.id), retiro.id)],
        }

    _validar_venta_origen(venta)
    usados = set(db.execute(_venta_items_ya_devueltos()).scalars())
    return {
        "origen": "venta",
        "items": [
            _item(vi.variante, vi.id, vi.precio_unitario, vi.id not in usados)
            for vi in sorted(venta.items, key=lambda i: i.id)
        ],
    }


def _cliente_de_ventas(ventas: list[Venta]) -> int | None:
    """
    El cliente de los tickets del cambio. No se juntan compras de clientes
    distintos: los puntos de lo que se lleva tienen que ir a alguien. Las
    compras sin cliente se juntan con cualquiera.
    """
    clientes = {v.cliente_id for v in ventas if v.cliente_id is not None}
    if len(clientes) > 1:
        raise ReglaDeNegocio(
            "Los tickets son de compras de clientes distintos: no se pueden juntar "
            "en un mismo cambio"
        )
    return next(iter(clientes), None)


def _sumar_origen(
    db: Session, cambio: Cambio, codigo_cambio: str, plazo: int
) -> list[str]:
    """
    Suma un ticket al cambio, con todas sus validaciones, y devuelve los
    avisos de plazo (no bloquean). La regla de mismo cliente se controla
    contra los tickets que el cambio ya tiene.
    """
    if not (codigo_cambio or "").strip():
        raise ReglaDeNegocio("Ingresá el código de cambio del ticket")
    if cambio.tipo == TipoCambio.FALLA:
        raise ReglaDeNegocio("El cambio por falla no lleva ticket")

    codigo = codigo_cambio.strip().upper()
    venta, retiro = _origen_por_codigo(db, codigo)
    avisos: list[str] = []

    if retiro is not None:
        if cambio.tipo != TipoCambio.COMUN:
            raise ReglaDeNegocio(
                "Ese código es de un retiro de mercadería: se cambia como cambio común"
            )
        if retiro.id in _ids_retiros_origen(db, cambio):
            raise ReglaDeNegocio(f"El ticket {codigo} ya está en este cambio")
        dias = (ahora_db().date() - retiro.timestamp.date()).days
        if dias > plazo:
            avisos.append(
                f"{codigo}: pasaron {dias} días desde el retiro (el plazo habitual es "
                f"{plazo} días). Podés continuar igual o cancelar."
            )
        db.add(CambioOrigen(cambio_id=cambio.id, retiro_mercaderia_id=retiro.id,
                            created_at=ahora_db()))
    else:
        _validar_venta_origen(venta)
        ids = _ids_ventas_origen(db, cambio)
        if venta.id in ids:
            raise ReglaDeNegocio(f"El ticket {codigo} ya está en este cambio")
        otras = list(db.execute(select(Venta).where(Venta.id.in_(ids))).scalars()) if ids else []
        _cliente_de_ventas([*otras, venta])
        dias = (ahora_db().date() - venta.created_at.date()).days
        if dias > plazo:
            avisos.append(
                f"{codigo}: pasaron {dias} días desde la venta (el plazo habitual es "
                f"{plazo} días). Podés continuar igual o cancelar."
            )
        db.add(CambioOrigen(cambio_id=cambio.id, venta_id=venta.id, created_at=ahora_db()))

    db.flush()
    return avisos


def iniciar_cambio(
    db: Session,
    autor: Usuario,
    tipo: TipoCambio,
    punto_de_venta_id: int,
    codigos_cambio: list[str] | None = None,
    autorizador_id: int | None = None,
    ip_origen: str | None = None,
) -> tuple[Cambio, list[str]]:
    """
    Crea un cambio en estado 'pendiente' con sus tickets.

    Común, promoción y gift card llevan uno o más códigos de cambio: lo
    devuelto de todos suma, para que el cliente pueda llevarse algo de más
    valor. Falla no lleva ticket y sí un autorizador.

    Retorna (cambio, avisos): los avisos son mensajes informativos (plazo
    vencido) que el frontend debe mostrar pero no bloquean.
    """
    codigos = [c.strip().upper() for c in (codigos_cambio or []) if c and c.strip()]
    if len(set(codigos)) != len(codigos):
        raise ReglaDeNegocio("Hay un código de cambio repetido")

    if tipo == TipoCambio.FALLA:
        if codigos:
            raise ReglaDeNegocio("El cambio por falla no lleva ticket")
        if autorizador_id is None:
            raise ReglaDeNegocio("El cambio por falla requiere un autorizador")
        if db.get(Usuario, autorizador_id) is None:
            raise NoEncontrado("Autorizador no encontrado")
    elif not codigos:
        raise ReglaDeNegocio("Ingresá el código de cambio del ticket")

    ahora = ahora_db()
    cambio = Cambio(
        tipo=tipo,
        punto_de_venta_id=punto_de_venta_id,
        usuario_id=autor.id,
        autorizador_id=autorizador_id,
        estado=EstadoCambio.PENDIENTE,
        created_at=ahora,
        updated_at=ahora,
    )
    db.add(cambio)
    db.flush()

    # Plazo habitual de cambio, de "Ajustes". Pasado, avisa: no bloquea.
    plazo = servicio_configuracion.dias_plazo_cambio(db)
    avisos: list[str] = []
    for codigo in codigos:
        avisos += _sumar_origen(db, cambio, codigo, plazo)

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="cambio.iniciado",
        entidad="cambios",
        entidad_id=cambio.id,
        estado_anterior=None,
        estado_nuevo={"tipo": tipo.value, "codigos_cambio": codigos},
        ip_origen=ip_origen,
    )

    return cambio, avisos


def agregar_origen(
    db: Session,
    autor: Usuario,
    cambio: Cambio,
    codigo_cambio: str,
    ip_origen: str | None = None,
) -> tuple[Cambio, list[str]]:
    """Suma otro ticket a un cambio pendiente (mismas validaciones que al iniciar)."""
    if cambio.estado != EstadoCambio.PENDIENTE:
        raise ReglaDeNegocio("Solo se pueden agregar tickets a un cambio pendiente")

    avisos = _sumar_origen(
        db, cambio, codigo_cambio, servicio_configuracion.dias_plazo_cambio(db)
    )
    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="cambio.ticket_agregado",
        entidad="cambios",
        entidad_id=cambio.id,
        estado_nuevo={"codigo_cambio": codigo_cambio.strip().upper()},
        ip_origen=ip_origen,
    )
    return cambio, avisos


def agregar_item_devuelto(
    db: Session,
    cambio: Cambio,
    variante_id: int,
    venta_item_id: int | None = None,
    retiro_mercaderia_id: int | None = None,
) -> tuple[CambioItemDevuelto, list[str]]:
    """
    Agrega un ítem devuelto al cambio pendiente.

    Para tipos comun/promocion/gift_card_fisica: hace falta el ítem de una de
    las ventas de los tickets. Si no llega `venta_item_id` (el buscador de
    producto del wizard no lo conoce, ver `_venta_item_disponible`), se
    resuelve solo buscándolo en esas ventas. La unidad de un retiro de
    mercadería llega con `retiro_mercaderia_id` (o, si el cambio tiene un
    solo retiro y ninguna venta con esa variante, se toma ese). Para falla:
    siempre None, no hay ticket.

    Retorna (item, avisos) — avisos incluye "ya fue cambiado N veces" si aplica.
    """
    if cambio.estado != EstadoCambio.PENDIENTE:
        raise ReglaDeNegocio("Solo se pueden agregar ítems a un cambio pendiente")

    avisos: list[str] = []
    variante = _variante(db, variante_id)
    venta_item = None

    retiros = _ids_retiros_origen(db, cambio)
    if retiro_mercaderia_id is not None:
        return _agregar_devuelto_de_retiro(db, cambio, variante, retiro_mercaderia_id)
    if retiros and venta_item_id is None:
        # Sin indicar de qué ticket es: si la variante es la de un retiro del
        # cambio, es esa unidad (el buscador de producto no sabe de tickets).
        # Primero uno todavía no devuelto en este cambio; si todos ya están,
        # el primero, para que el error diga eso.
        del_producto = [
            r for r in retiros if db.get(RetiroMercaderia, r).variante_id == variante_id
        ]
        libres = [r for r in del_producto if not _retiro_en_este_cambio(db, cambio, r)]
        if del_producto:
            return _agregar_devuelto_de_retiro(db, cambio, variante, (libres or del_producto)[0])
        if not _ids_ventas_origen(db, cambio):
            raise ReglaDeNegocio("Ese producto no es el de ningún retiro de mercadería del cambio")

    if cambio.tipo in (TipoCambio.COMUN, TipoCambio.PROMOCION, TipoCambio.GIFT_CARD_FISICA):
        if venta_item_id is None:
            venta_item_id = _venta_item_disponible(db, cambio, variante_id)
        venta_item = db.get(VentaItem, venta_item_id)
        if venta_item is None:
            raise NoEncontrado("Ítem de venta no encontrado")
        if venta_item.venta_id not in _ids_ventas_origen(db, cambio):
            raise ReglaDeNegocio("El ítem no pertenece a ninguno de los tickets del cambio")
        if venta_item.variante_id != variante_id:
            raise ReglaDeNegocio("El ítem de venta no corresponde a la variante indicada")
        if venta_item.id in _en_este_cambio(db, cambio):
            raise ReglaDeNegocio("Ese producto ya está entre los devueltos de este cambio")
        if db.execute(
            _venta_items_ya_devueltos().where(CambioItemDevuelto.venta_item_id == venta_item.id)
        ).first():
            raise ReglaDeNegocio("Ese producto ya se devolvió en otro cambio confirmado")

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


def _agregar_devuelto_de_retiro(
    db: Session, cambio: Cambio, variante: Variante, retiro_id: int
) -> tuple[CambioItemDevuelto, list[str]]:
    """
    Ítem devuelto de un cambio cuyo origen es un retiro de mercadería.

    El retiro es de UNA unidad: se devuelve esa variante y una sola vez. Se
    reconoce el precio de lista del momento del retiro —no lo que pagó la
    empleada con su descuento—, igual que un cambio común.
    """
    if retiro_id not in _ids_retiros_origen(db, cambio):
        raise ReglaDeNegocio("Ese retiro de mercadería no es uno de los tickets del cambio")
    retiro = db.get(RetiroMercaderia, retiro_id)
    if retiro is None:
        raise NoEncontrado("Retiro de mercadería no encontrado")
    if retiro.variante_id != variante.id:
        raise ReglaDeNegocio("Ese producto no es el del retiro de mercadería del código")

    if _retiro_en_este_cambio(db, cambio, retiro.id):
        raise ReglaDeNegocio("Ese producto ya está entre los devueltos de este cambio")
    if _retiro_ya_devuelto(db, retiro.id):
        raise ReglaDeNegocio("El producto de ese retiro de mercadería ya se devolvió")

    material = _material_de_variante(db, variante)
    item = CambioItemDevuelto(
        cambio_id=cambio.id,
        venta_item_id=None,
        retiro_mercaderia_id=retiro.id,
        variante_id=variante.id,
        precio_reconocido=Decimal(retiro.precio_lista),
        en_promocion=False,
        tipo_promo=None,
        material_id=material.id if material else None,
    )
    db.add(item)
    db.flush()
    return item, []


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


def _controlar_que_no_se_devolvio_antes(db: Session, cambio: Cambio) -> None:
    """
    Al confirmar: ninguno de sus devueltos puede estar ya en OTRO cambio
    confirmado. Pasa si dos cambios pendientes tomaron la misma unidad (los
    pendientes no reservan) y el otro se confirmó primero.
    """
    for item in cambio.items_devueltos:
        if item.retiro_mercaderia_id is not None and _retiro_ya_devuelto(
            db, item.retiro_mercaderia_id, excepto_cambio_id=cambio.id
        ):
            raise ReglaDeNegocio(
                "El producto de ese retiro de mercadería ya se devolvió en otro cambio confirmado"
            )
    ids = _en_este_cambio(db, cambio)
    if not ids:
        return
    repetidos = set(db.execute(
        _venta_items_ya_devueltos(excepto_cambio_id=cambio.id)
        .where(CambioItemDevuelto.venta_item_id.in_(ids))
    ).scalars())
    if repetidos:
        codigos = [
            i.variante.codigo_con_verificador
            for i in cambio.items_devueltos if i.venta_item_id in repetidos
        ]
        raise ReglaDeNegocio(
            f"{', '.join(codigos)} ya se devolvió en otro cambio confirmado"
        )


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
    _controlar_que_no_se_devolvio_antes(db, cambio)

    calculo = calcular_diferencia(db, cambio)
    diferencia = calculo["diferencia"]

    if diferencia > 0 and medio_pago_diferencia_id is None:
        raise ReglaDeNegocio(
            f"La diferencia es ${diferencia:.2f}. Indicá el medio de pago."
        )

    antes = snapshot(cambio)

    # ── Stock: devolver ítems entregados por el cliente ─────────────────────
    # Agrupado por (variante, venta de la unidad): con varios tickets, cada
    # devolución queda referida a la venta de la que salió.
    conteo_devueltos: dict[tuple[int, int | None], int] = {}
    for item in cambio.items_devueltos:
        clave = (item.variante_id, item.venta_item.venta_id if item.venta_item else None)
        conteo_devueltos[clave] = conteo_devueltos.get(clave, 0) + 1

    for (variante_id, venta_id), cantidad in conteo_devueltos.items():
        servicio_stock.aplicar_movimiento(
            db,
            autor,
            tipo=TipoMovimiento.DEVOLUCION_VENTA,
            variante_id=variante_id,
            cantidad=cantidad,
            punto_venta_destino_id=cambio.punto_de_venta_id,
            referencia_venta_id=venta_id,
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

    # ── Puntos: restar los de lo devuelto, sumar los de lo nuevo ────────────
    # Por la regla de mismo cliente, todos los tickets con cliente son del
    # mismo: se le restan los puntos de lo devuelto de cada venta (referidos
    # a esa venta) y se le suman los de lo nuevo.
    from app.models.cliente import TipoPunto

    ventas_origen = cambio.ventas_origen
    cliente_id = _cliente_de_ventas(ventas_origen)
    if cliente_id is not None:
        devuelto_por_venta: dict[int, Decimal] = {}
        for item in cambio.items_devueltos:
            if item.venta_item is not None:
                vid = item.venta_item.venta_id
                devuelto_por_venta[vid] = devuelto_por_venta.get(vid, Decimal("0")) + item.precio_reconocido
        for venta in ventas_origen:
            if venta.cliente_id is None:
                continue
            puntos_a_restar = servicio_clientes.puntos_por_venta(
                db, devuelto_por_venta.get(venta.id, Decimal("0"))
            )
            if puntos_a_restar > 0:
                servicio_clientes.registrar_movimiento_puntos(
                    db,
                    autor,
                    cliente_id=cliente_id,
                    tipo=TipoPunto.AJUSTE,
                    cantidad=-puntos_a_restar,
                    venta_id=venta.id,
                    descripcion=f"Cambio #{cambio.id}: ítems devueltos",
                    ip_origen=ip_origen,
                )
        puntos_nuevos = servicio_clientes.puntos_por_venta(db, calculo["total_nuevo"])
        if puntos_nuevos > 0:
            primera = next(v for v in ventas_origen if v.cliente_id is not None)
            servicio_clientes.registrar_movimiento_puntos(
                db,
                autor,
                cliente_id=cliente_id,
                tipo=TipoPunto.ACUMULACION,
                cantidad=puntos_nuevos,
                venta_id=primera.id,
                descripcion=f"Cambio #{cambio.id}: ítems nuevos",
                ip_origen=ip_origen,
            )

    # ── Generar nuevo código de cambio para los ítems nuevos ────────────────
    # El mismo generador que la venta y el retiro de mercadería: un solo
    # largo, un solo alfabeto y la unicidad contra los tres orígenes.
    codigo_nuevo = generar_codigo_cambio(db)

    # ── Actualizar contador de cambios previos en la venta origen ───────────
    # Cambios confirmados que comparten alguno de los tickets de este.
    ids_ventas = [v.id for v in ventas_origen]
    previos = db.execute(
        select(func.count(func.distinct(Cambio.id)))
        .join(CambioOrigen, CambioOrigen.cambio_id == Cambio.id)
        .where(
            CambioOrigen.venta_id.in_(ids_ventas),
            Cambio.estado == EstadoCambio.CONFIRMADO,
            Cambio.id != cambio.id,
        )
    ).scalar_one() if ids_ventas else 0
    cambio.contador_cambios_previos = previos

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
            joinedload(Cambio.origenes).joinedload(CambioOrigen.venta),
            joinedload(Cambio.origenes).joinedload(CambioOrigen.retiro_mercaderia),
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
