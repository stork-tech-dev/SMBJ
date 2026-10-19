"""
Reporte "Historial del Producto": toda la vida de un producto en un informe.

Cinco partes, cada una de lo más reciente a lo más viejo, que abarcan todas
las variantes del producto (cada fila dice de cuál es):

1. Carga — el alta (del producto y de cada variante) y los ingresos de
   mercadería.
2. Movimientos — todo lo que movió su stock: ingresos, envíos, ventas,
   devoluciones, bajas, ajustes y retiros.
3. Ventas — las confirmadas (ni anuladas ni en curso), con el resumen por
   local.
4. Fallas — los cambios por falla confirmados donde se devolvió y las bajas
   de stock con su motivo.
5. Precios — las ediciones que cambiaron precio o descuento y cada cambio
   de dólar de su proveedor desde el alta (que recalcula el precio de
   venta).

Solo lectura: todo sale de tablas que ya registran estos hechos —la
auditoría, `movimientos_stock`, ventas, cambios y el historial de dólar—
sin guardar nada nuevo (Principio 4).
"""

from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.auditoria import Auditoria
from app.models.cambio import Cambio, CambioItemDevuelto, EstadoCambio, TipoCambio
from app.models.producto import Producto, Variante
from app.models.proveedor import ProveedorDolarHistorial
from app.models.remito import Remito
from app.models.stock import MovimientoStock, Stock, TipoMovimiento
from app.models.usuario import Usuario
from app.models.venta import EstadoVenta, Venta, VentaItem
from app.services.roles import NoEncontrado

# Los campos de la auditoría que son "precio". Una edición que no toca
# ninguno (descripción, peso, temporada) no es un cambio de precio.
CAMPOS_PRECIO = ("precio_usd", "precio_venta", "descuento_producto")


def _etiqueta_variante(variante: Variante | None) -> str:
    """"ABC12345 — Roja": el código de la etiqueta y, si no es la BASE, su nombre."""
    if variante is None:
        return "—"
    codigo = f"{variante.codigo_completo}{variante.verificador}"
    return f"{codigo} — {variante.descripcion_sufijo}" if variante.descripcion_sufijo else codigo


def _nombre(punto) -> str | None:
    return punto.nombre if punto is not None else None


def _mas_nuevo_primero(filas: list[dict]) -> list[dict]:
    return sorted(filas, key=lambda f: f["fecha"], reverse=True)


# ---------------------------------------------------------------------------
# Búsqueda
# ---------------------------------------------------------------------------


def buscar_productos(db: Session, texto: str, limite: int = 10) -> list[Producto]:
    """
    Productos por SKU, descripción o código de etiqueta (con o sin dígito
    verificador): las mismas formas de nombrar un artículo que el listado
    de productos (`condiciones_codigo_variante`).
    """
    from app.services.productos import condiciones_codigo_variante

    limpio = (texto or "").strip()
    if not limpio:
        return []
    mayus = limpio.upper()
    patron = f"%{limpio}%"
    por_codigo = select(Variante.producto_id).where(or_(*condiciones_codigo_variante(mayus)))
    consulta = (
        select(Producto)
        .where(or_(
            Producto.sku.ilike(f"%{mayus}%"),
            Producto.descripcion.ilike(patron),
            Producto.id.in_(por_codigo),
        ))
        .options(selectinload(Producto.fotos))
        .order_by(func.lower(Producto.descripcion))
        .limit(limite)
    )
    return list(db.execute(consulta).unique().scalars())


# ---------------------------------------------------------------------------
# Historial
# ---------------------------------------------------------------------------


def _carga(db: Session, producto: Producto, ids: list[int], variantes: dict) -> list[dict]:
    altas = db.execute(
        select(Auditoria, Usuario.nombre)
        .outerjoin(Usuario, Usuario.id == Auditoria.usuario_id)
        .where(or_(
            (Auditoria.accion == "producto.crear") & (Auditoria.entidad_id == producto.id),
            (Auditoria.accion == "variante.crear") & (Auditoria.entidad_id.in_(ids)),
        ))
    ).all()
    filas = [
        {
            "fecha": a.timestamp,
            "tipo": "alta",
            "variante": (_etiqueta_variante(variantes.get(a.entidad_id))
                         if a.accion == "variante.crear" else None),
            "cantidad": None,
            "punto_de_venta": None,
            "usuario": usuario,
        }
        for a, usuario in altas
    ]
    ingresos = db.execute(
        select(MovimientoStock)
        .options(joinedload(MovimientoStock.destino), joinedload(MovimientoStock.usuario))
        .where(MovimientoStock.variante_id.in_(ids),
               MovimientoStock.tipo == TipoMovimiento.INGRESO_PROVEEDOR)
    ).scalars().all()
    filas += [
        {
            "fecha": m.timestamp,
            "tipo": "ingreso",
            "variante": _etiqueta_variante(variantes.get(m.variante_id)),
            "cantidad": m.cantidad,
            "punto_de_venta": _nombre(m.destino),
            "usuario": m.usuario.nombre,
        }
        for m in ingresos
    ]
    return _mas_nuevo_primero(filas)


def _movimientos(db: Session, ids: list[int], variantes: dict) -> list[MovimientoStock]:
    return list(db.execute(
        select(MovimientoStock)
        .options(
            joinedload(MovimientoStock.origen),
            joinedload(MovimientoStock.destino),
            joinedload(MovimientoStock.usuario),
            joinedload(MovimientoStock.motivo_baja),
        )
        .where(MovimientoStock.variante_id.in_(ids))
        .order_by(MovimientoStock.timestamp.desc(), MovimientoStock.id.desc())
    ).scalars())


def _referencia(m: MovimientoStock, remitos: dict, ventas: dict) -> str | None:
    """De dónde salió el movimiento: el remito, la venta o la compra."""
    if m.remito_id:
        return f"Remito {remitos.get(m.remito_id, m.remito_id)}"
    if m.referencia_venta_id:
        return f"Venta {ventas.get(m.referencia_venta_id, m.referencia_venta_id)}"
    if m.compra_id:
        return f"Compra #{m.compra_id}"
    return None


def _ventas(db: Session, ids: list[int], variantes: dict) -> dict:
    filas = db.execute(
        select(VentaItem, Venta)
        .join(Venta, Venta.id == VentaItem.venta_id)
        .options(joinedload(Venta.punto_de_venta))
        .where(VentaItem.variante_id.in_(ids), Venta.estado == EstadoVenta.CONFIRMADA)
    ).all()
    detalle = _mas_nuevo_primero([
        {
            "fecha": venta.created_at,
            "venta_id": venta.id,
            "numero": venta.numero,
            "punto_de_venta": venta.punto_de_venta.nombre,
            "variante": _etiqueta_variante(variantes.get(item.variante_id)),
            "precio": Decimal(item.precio_final),
        }
        for item, venta in filas
    ])
    por_local: dict[str, dict] = {}
    for fila in detalle:
        local = por_local.setdefault(
            fila["punto_de_venta"],
            {"punto_de_venta": fila["punto_de_venta"], "unidades": 0, "importe": Decimal("0")},
        )
        local["unidades"] += 1
        local["importe"] += fila["precio"]
    return {
        "detalle": detalle,
        "por_local": sorted(por_local.values(), key=lambda f: -f["unidades"]),
        "unidades": len(detalle),
        "importe": sum((f["precio"] for f in detalle), Decimal("0")),
    }


def _fallas(db: Session, ids: list[int], variantes: dict, movimientos) -> list[dict]:
    cambios = db.execute(
        select(CambioItemDevuelto, Cambio)
        .join(Cambio, Cambio.id == CambioItemDevuelto.cambio_id)
        .options(
            joinedload(Cambio.punto_de_venta),
            joinedload(Cambio.autorizador),
            joinedload(Cambio.usuario),
        )
        .where(CambioItemDevuelto.variante_id.in_(ids),
               Cambio.tipo == TipoCambio.FALLA,
               Cambio.estado == EstadoCambio.CONFIRMADO)
    ).all()
    filas = [
        {
            "fecha": cambio.created_at,
            "tipo": "cambio_falla",
            "variante": _etiqueta_variante(variantes.get(item.variante_id)),
            "cantidad": 1,
            "punto_de_venta": cambio.punto_de_venta.nombre,
            # En un cambio por falla, quién lo aprobó es lo que importa.
            "detalle": cambio.autorizador.nombre if cambio.autorizador else None,
            "usuario": cambio.usuario.nombre,
        }
        for item, cambio in cambios
    ]
    filas += [
        {
            "fecha": m.timestamp,
            "tipo": "baja",
            "variante": _etiqueta_variante(variantes.get(m.variante_id)),
            "cantidad": m.cantidad,
            "punto_de_venta": _nombre(m.origen),
            "detalle": m.motivo_baja.nombre if m.motivo_baja else None,
            "usuario": m.usuario.nombre,
        }
        for m in movimientos
        if m.tipo == TipoMovimiento.BAJA
    ]
    return _mas_nuevo_primero(filas)


def _precios(db: Session, producto: Producto, ids: list[int], variantes: dict) -> list[dict]:
    ediciones = db.execute(
        select(Auditoria, Usuario.nombre)
        .outerjoin(Usuario, Usuario.id == Auditoria.usuario_id)
        .where(or_(
            (Auditoria.accion == "producto.editar") & (Auditoria.entidad_id == producto.id),
            (Auditoria.accion == "variante.editar") & (Auditoria.entidad_id.in_(ids)),
        ))
    ).all()
    filas = []
    for a, usuario in ediciones:
        antes, despues = a.estado_anterior or {}, a.estado_nuevo or {}
        for campo in CAMPOS_PRECIO:
            if campo not in antes or campo not in despues:
                continue
            anterior, nuevo = antes[campo], despues[campo]
            # Comparación numérica: "1000.00" y "1000" son el mismo precio.
            if _decimal(anterior) == _decimal(nuevo):
                continue
            filas.append({
                "fecha": a.timestamp,
                "campo": campo,
                "variante": (_etiqueta_variante(variantes.get(a.entidad_id))
                             if a.accion == "variante.editar" else None),
                "anterior": _decimal(anterior),
                "nuevo": _decimal(nuevo),
                "usuario": usuario,
            })

    dolar = db.execute(
        select(ProveedorDolarHistorial)
        .options(joinedload(ProveedorDolarHistorial.usuario))
        .where(ProveedorDolarHistorial.proveedor_id == producto.proveedor_id,
               ProveedorDolarHistorial.timestamp >= producto.created_at)
    ).scalars().all()
    filas += [
        {
            "fecha": h.timestamp,
            "campo": "dolar_proveedor",
            "variante": None,
            "anterior": Decimal(h.valor_anterior),
            "nuevo": Decimal(h.valor_nuevo),
            "usuario": h.usuario.nombre if h.usuario else None,
            "origen": h.origen.value,
        }
        for h in dolar
    ]
    return _mas_nuevo_primero(filas)


def _decimal(valor) -> Decimal | None:
    return Decimal(str(valor)) if valor is not None else None


def historial_producto(db: Session, producto_id: int) -> dict:
    producto = db.get(Producto, producto_id)
    if producto is None:
        raise NoEncontrado("Producto inexistente")

    lista = db.execute(
        select(Variante).where(Variante.producto_id == producto.id)
    ).scalars().all()
    variantes = {v.id: v for v in lista}
    ids = list(variantes) or [-1]

    movimientos = _movimientos(db, ids, variantes)
    remitos = dict(db.execute(
        select(Remito.id, Remito.numero).where(
            Remito.id.in_({m.remito_id for m in movimientos if m.remito_id} or {-1})
        )
    ).all())
    ventas_ref = dict(db.execute(
        select(Venta.id, Venta.numero).where(
            Venta.id.in_({m.referencia_venta_id for m in movimientos
                          if m.referencia_venta_id} or {-1})
        )
    ).all())

    stock_total = db.execute(
        select(func.coalesce(func.sum(Stock.cantidad), 0)).where(Stock.variante_id.in_(ids))
    ).scalar_one()

    return {
        "ficha": {
            "producto_id": producto.id,
            "sku": producto.sku,
            "descripcion": producto.descripcion,
            "categoria": producto.categoria.nombre,
            "proveedor": producto.proveedor.nombre,
            "precio_usd": producto.precio_usd,
            "precio_venta": producto.precio_venta,
            "stock_total": int(stock_total),
            "activo": producto.activo,
            "created_at": producto.created_at,
            "variantes": [_etiqueta_variante(v) for v in lista],
        },
        "carga": _carga(db, producto, ids, variantes),
        "movimientos": [
            {
                "fecha": m.timestamp,
                "tipo": m.tipo.value,
                "variante": _etiqueta_variante(variantes.get(m.variante_id)),
                "cantidad": m.cantidad,
                "origen": _nombre(m.origen),
                "destino": _nombre(m.destino),
                "usuario": m.usuario.nombre,
                "referencia": _referencia(m, remitos, ventas_ref),
            }
            for m in movimientos
        ],
        "ventas": _ventas(db, ids, variantes),
        "fallas": _fallas(db, ids, variantes, movimientos),
        "precios": _precios(db, producto, ids, variantes),
    }
