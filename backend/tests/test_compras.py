"""
Tests del módulo de compras a proveedores.

Cubre el flujo completo: iniciar borrador → agregar ítems → cerrar (con
actualización de stock y precios), detección del cambio de precio >30%,
y las restricciones de un solo borrador por usuario.
"""

from decimal import Decimal

import pytest

from app.core.permisos import ROL_CUENTA_MAESTRA, ROL_DISTRIBUCION
from app.models.compra import EstadoCompra
from app.models.configuracion import ConfiguracionSistema
from app.models.punto_de_venta import TipoPuntoVenta
from app.models.stock import Stock, TipoMovimiento
from app.services import categorias as servicio_categorias
from app.services import compras as servicio
from app.services import productos as servicio_productos
from app.services import proveedores as servicio_proveedores
from app.services import stock as servicio_stock
from app.services.roles import ReglaDeNegocio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def autor(crear_usuario):
    return crear_usuario("admin", ROL_CUENTA_MAESTRA)


@pytest.fixture
def otro_usuario(crear_usuario):
    return crear_usuario("operador", ROL_DISTRIBUCION)


@pytest.fixture
def config(db, autor):
    fila = ConfiguracionSistema(
        redondeo=Decimal("1000.00"),
        descuento_maximo=Decimal("30.00"),
        metodo_descuento="encadenado",
        letra_empresa="S",
        updated_by=autor.id,
    )
    db.add(fila)
    db.flush()
    return fila


@pytest.fixture
def cd(crear_punto_de_venta):
    return crear_punto_de_venta("CD", "Centro de Distribución", TipoPuntoVenta.CD)


@pytest.fixture
def proveedor(db, autor):
    return servicio_proveedores.crear_proveedor(
        db, autor, nombre="Proveedor Test", dolar_actual=Decimal("1000"),
    )


@pytest.fixture
def variante(db, autor, config, proveedor):
    """Un producto con su variante BASE."""
    categoria = servicio_categorias.crear_categoria(db, autor, nombre="Joyas")
    producto = servicio_productos.crear_producto(
        db, autor,
        categoria_id=categoria.id,
        proveedor_id=proveedor.id,
        precio_usd=Decimal("10"),
        descripcion="Anillo plata",
    )
    db.flush()
    return producto.variantes[0]


# ---------------------------------------------------------------------------
# Iniciar compra
# ---------------------------------------------------------------------------

def test_iniciar_compra_crea_borrador(db, autor, proveedor, cd, config):
    compra = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    assert compra.estado == EstadoCompra.BORRADOR
    assert compra.proveedor_id == proveedor.id
    assert compra.punto_de_venta_id == cd.id


def test_iniciar_compra_retoma_borrador(db, autor, proveedor, cd, config):
    primera = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    segunda = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    assert primera.id == segunda.id


def test_otro_usuario_puede_tener_su_borrador(
    db, autor, otro_usuario, proveedor, cd, config
):
    c1 = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    c2 = servicio.iniciar_compra(
        db, otro_usuario, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    assert c1.id != c2.id


# ---------------------------------------------------------------------------
# Agregar ítems
# ---------------------------------------------------------------------------

def test_agregar_item(db, autor, proveedor, cd, variante, config):
    compra = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    item, requiere = servicio.agregar_item(
        db, autor,
        compra_id=compra.id, variante_id=variante.id,
        cantidad=5, precio_usd=Decimal("10"),
    )
    assert item.cantidad == 5
    assert item.precio_usd_anterior == Decimal("10")
    assert item.precio_usd_nuevo == Decimal("10")
    assert not requiere


def test_agregar_misma_variante_suma_cantidad(
    db, autor, proveedor, cd, variante, config
):
    compra = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    servicio.agregar_item(
        db, autor,
        compra_id=compra.id, variante_id=variante.id,
        cantidad=3, precio_usd=Decimal("10"),
    )
    item, _ = servicio.agregar_item(
        db, autor,
        compra_id=compra.id, variante_id=variante.id,
        cantidad=2, precio_usd=Decimal("10"),
    )
    assert item.cantidad == 5


def test_detecta_cambio_precio_mayor_30(
    db, autor, proveedor, cd, variante, config
):
    compra = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    # Precio actual: 10. Nuevo: 15 (+50%)
    item, requiere = servicio.agregar_item(
        db, autor,
        compra_id=compra.id, variante_id=variante.id,
        cantidad=5, precio_usd=Decimal("15"),
    )
    assert requiere is True
    assert not item.precio_actualizado


def test_no_detecta_cambio_precio_menor_30(
    db, autor, proveedor, cd, variante, config
):
    compra = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    # Precio actual: 10. Nuevo: 12 (+20%)
    item, requiere = servicio.agregar_item(
        db, autor,
        compra_id=compra.id, variante_id=variante.id,
        cantidad=5, precio_usd=Decimal("12"),
    )
    assert requiere is False
    assert item.precio_actualizado is True


# ---------------------------------------------------------------------------
# Confirmar precio
# ---------------------------------------------------------------------------

def test_confirmar_precio_acepta(db, autor, proveedor, cd, variante, config):
    compra = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    item, _ = servicio.agregar_item(
        db, autor,
        compra_id=compra.id, variante_id=variante.id,
        cantidad=5, precio_usd=Decimal("15"),
    )
    item = servicio.confirmar_cambio_precio(
        db, autor, compra_item_id=item.id, confirmar=True,
    )
    assert item.precio_actualizado is True
    assert item.precio_usd_nuevo == Decimal("15")


def test_confirmar_precio_rechaza(db, autor, proveedor, cd, variante, config):
    compra = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    item, _ = servicio.agregar_item(
        db, autor,
        compra_id=compra.id, variante_id=variante.id,
        cantidad=5, precio_usd=Decimal("15"),
    )
    item = servicio.confirmar_cambio_precio(
        db, autor, compra_item_id=item.id, confirmar=False,
    )
    assert item.precio_actualizado is False
    assert item.precio_usd_nuevo == Decimal("10")  # Volvió al anterior


# ---------------------------------------------------------------------------
# Cerrar compra
# ---------------------------------------------------------------------------

def test_cerrar_compra_actualiza_stock(
    db, autor, proveedor, cd, variante, config
):
    compra = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    servicio.agregar_item(
        db, autor,
        compra_id=compra.id, variante_id=variante.id,
        cantidad=10, precio_usd=Decimal("10"),
    )
    servicio.cerrar_compra(db, autor, compra_id=compra.id)

    stock = db.query(Stock).filter_by(
        variante_id=variante.id, punto_de_venta_id=cd.id,
    ).first()
    assert stock is not None
    assert stock.cantidad == 10


def test_cerrar_compra_crea_movimientos_con_compra_id(
    db, autor, proveedor, cd, variante, config
):
    compra = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    servicio.agregar_item(
        db, autor,
        compra_id=compra.id, variante_id=variante.id,
        cantidad=10, precio_usd=Decimal("10"),
    )
    servicio.cerrar_compra(db, autor, compra_id=compra.id)

    from app.models.stock import MovimientoStock
    mov = db.query(MovimientoStock).filter_by(compra_id=compra.id).all()
    assert len(mov) == 1
    assert mov[0].tipo == TipoMovimiento.INGRESO_PROVEEDOR
    assert mov[0].cantidad == 10


def test_cerrar_compra_actualiza_precios(
    db, autor, proveedor, cd, variante, config
):
    compra = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    # Cambio de precio <= 30%, se marca automáticamente.
    servicio.agregar_item(
        db, autor,
        compra_id=compra.id, variante_id=variante.id,
        cantidad=5, precio_usd=Decimal("12"),
    )
    servicio.cerrar_compra(db, autor, compra_id=compra.id)

    db.refresh(variante)
    # La variante base refleja el nuevo precio.
    assert variante.precio_usd is None or variante.producto.precio_usd == Decimal("12")
    # El precio de venta se recalculó (12 * 1000 = 12000).
    assert variante.producto.precio_venta == Decimal("12000")


def test_cerrar_sin_items_falla(db, autor, proveedor, cd, config):
    compra = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    with pytest.raises(ReglaDeNegocio, match="no tiene ítems"):
        servicio.cerrar_compra(db, autor, compra_id=compra.id)


def test_compra_cerrada_tiene_fecha_cierre(
    db, autor, proveedor, cd, variante, config
):
    compra = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    servicio.agregar_item(
        db, autor,
        compra_id=compra.id, variante_id=variante.id,
        cantidad=5, precio_usd=Decimal("10"),
    )
    compra = servicio.cerrar_compra(db, autor, compra_id=compra.id)
    assert compra.estado == EstadoCompra.CERRADA
    assert compra.fecha_cierre is not None


# ---------------------------------------------------------------------------
# Eliminar borrador
# ---------------------------------------------------------------------------

def test_eliminar_borrador(db, autor, proveedor, cd, config):
    compra = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    servicio.eliminar_borrador(db, autor, compra_id=compra.id)
    db.refresh(compra)
    assert compra.estado == EstadoCompra.ELIMINADA


def test_no_se_puede_eliminar_cerrada(
    db, autor, proveedor, cd, variante, config
):
    compra = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    servicio.agregar_item(
        db, autor,
        compra_id=compra.id, variante_id=variante.id,
        cantidad=5, precio_usd=Decimal("10"),
    )
    servicio.cerrar_compra(db, autor, compra_id=compra.id)
    with pytest.raises(ReglaDeNegocio, match="borrador"):
        servicio.eliminar_borrador(db, autor, compra_id=compra.id)


def test_borrador_eliminado_permite_crear_otro(
    db, autor, proveedor, cd, config
):
    compra1 = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    servicio.eliminar_borrador(db, autor, compra_id=compra1.id)
    compra2 = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    assert compra2.id != compra1.id


# ---------------------------------------------------------------------------
# Modificar y quitar ítems
# ---------------------------------------------------------------------------

def test_modificar_cantidad(db, autor, proveedor, cd, variante, config):
    compra = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    item, _ = servicio.agregar_item(
        db, autor,
        compra_id=compra.id, variante_id=variante.id,
        cantidad=5, precio_usd=Decimal("10"),
    )
    item, _ = servicio.modificar_item(
        db, autor, compra_id=compra.id, item_id=item.id, cantidad=8,
    )
    assert item.cantidad == 8


def test_quitar_item(db, autor, proveedor, cd, variante, config):
    compra = servicio.iniciar_compra(
        db, autor, proveedor_id=proveedor.id, punto_de_venta_id=cd.id,
    )
    item, _ = servicio.agregar_item(
        db, autor,
        compra_id=compra.id, variante_id=variante.id,
        cantidad=5, precio_usd=Decimal("10"),
    )
    servicio.quitar_item(db, autor, compra_id=compra.id, item_id=item.id)
    db.flush()
    compra = servicio.obtener_compra_completa(db, compra.id)
    assert len(compra.items) == 0
