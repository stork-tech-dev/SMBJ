"""
Tests del módulo de promociones.

Cubre los tres tipos (2x1, 3x2, % Porcentaje) y los nuevos alcances
(todos los productos, todas las categorías, sucursal, medio de pago).
"""

from decimal import Decimal

import pytest

from app.core.permisos import ROL_CUENTA_MAESTRA
from app.models.configuracion import ConfiguracionSistema
from app.models.dispositivo import Dispositivo
from app.models.medio_pago import MedioDePago
from app.models.promocion import TipoAlcance, TipoPromocion
from app.models.punto_de_venta import TipoPuntoVenta
from app.services import categorias as servicio_categorias
from app.services import medios_pago as servicio_medios
from app.services import productos as servicio_productos
from app.services import promociones as servicio_promociones
from app.services import proveedores as servicio_proveedores
from app.services import stock as servicio_stock
from app.services import ventas as servicio_ventas
from app.services.roles import ReglaDeNegocio
from app.core.device_scope import DeviceScope
from app.models.stock import TipoMovimiento

LIBRE = DeviceScope(restringido=False)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def autor(crear_usuario):
    return crear_usuario("admin", ROL_CUENTA_MAESTRA)


@pytest.fixture
def config(db, autor):
    fila = ConfiguracionSistema(
        redondeo=Decimal("1.00"),
        descuento_maximo=Decimal("50.00"),
        metodo_descuento="encadenado",
        letra_empresa="S",
        updated_by=autor.id,
    )
    db.add(fila)
    db.flush()
    return fila


@pytest.fixture
def local(crear_punto_de_venta):
    return crear_punto_de_venta("PLY", "Patio Olmos Test", TipoPuntoVenta.LOCAL)


@pytest.fixture
def otro_local(crear_punto_de_venta):
    return crear_punto_de_venta("PJK", "Jockey Test", TipoPuntoVenta.LOCAL)


@pytest.fixture
def dispositivo(db, local):
    equipo = Dispositivo(punto_de_venta_id=local.id, activo=True, descripcion="Test Celu")
    db.add(equipo)
    db.flush()
    return equipo


@pytest.fixture
def catalogo(db, autor, config):
    categoria = servicio_categorias.crear_categoria(db, autor, nombre="TestPlata")
    proveedor = servicio_proveedores.crear_proveedor(
        db, autor, nombre="Joyas Test", dolar_actual=Decimal("1")
    )
    return categoria, proveedor


@pytest.fixture
def crear_variante(db, autor, catalogo):
    categoria, proveedor = catalogo

    def _crear(descripcion: str, precio: str):
        producto = servicio_productos.crear_producto(
            db, autor,
            categoria_id=categoria.id,
            proveedor_id=proveedor.id,
            precio_usd=Decimal(precio),
            descripcion=descripcion,
        )
        return producto.variantes[0]

    return _crear


@pytest.fixture
def con_stock(db, autor, local):
    def _cargar(variante, cantidad: int):
        servicio_stock.aplicar_movimiento(
            db, autor,
            tipo=TipoMovimiento.INGRESO_PROVEEDOR,
            variante_id=variante.id,
            cantidad=cantidad,
            punto_venta_destino_id=local.id,
        )
    return _cargar


@pytest.fixture
def efectivo(db):
    return next(m for m in servicio_medios.listar_medios(db) if m.nombre == "Efectivo")


@pytest.fixture
def venta_base(db, autor, dispositivo):
    return servicio_ventas.iniciar_venta(db, autor, dispositivo, LIBRE)


# ============================================================================
# TIPO PORCENTAJE — VALIDACIONES
# ============================================================================


def test_porcentaje_requiere_porcentaje_descuento(db, autor, catalogo):
    """Crear tipo PORCENTAJE sin porcentaje levanta ReglaDeNegocio."""
    categoria, _ = catalogo
    with pytest.raises(ReglaDeNegocio, match="porcentaje"):
        servicio_promociones.crear_promocion(
            db, autor,
            nombre="Sin porcentaje",
            tipo=TipoPromocion.PORCENTAJE,
            porcentaje_descuento=None,
            alcances=[{"tipo_alcance": TipoAlcance.TODOS_PRODUCTOS, "referencia_id": 0}],
        )


def test_porcentaje_se_guarda_y_recupera(db, autor):
    """El porcentaje persiste en la base y llega en la respuesta."""
    promo = servicio_promociones.crear_promocion(
        db, autor,
        nombre="Promo 20pct",
        tipo=TipoPromocion.PORCENTAJE,
        porcentaje_descuento=20,
        alcances=[{"tipo_alcance": TipoAlcance.TODOS_PRODUCTOS, "referencia_id": 0}],
    )
    db.flush()
    assert promo.porcentaje_descuento == 20
    assert promo.tipo == TipoPromocion.PORCENTAJE


def test_porcentaje_ignora_tamano_grupo(db, autor):
    """Las propiedades de grupo devuelven None para tipo PORCENTAJE."""
    promo = servicio_promociones.crear_promocion(
        db, autor,
        nombre="Promo grupos",
        tipo=TipoPromocion.PORCENTAJE,
        porcentaje_descuento=15,
        alcances=[{"tipo_alcance": TipoAlcance.TODOS_PRODUCTOS, "referencia_id": 0}],
    )
    assert promo.tamano_grupo is None
    assert promo.pagas_por_grupo is None


# ============================================================================
# ALCANCE — TODOS LOS PRODUCTOS / TODAS LAS CATEGORÍAS
# ============================================================================


def test_alcance_todos_productos_cubre_cualquier_producto(db, autor, crear_variante, con_stock):
    """Una promo con TODOS_PRODUCTOS alcanza a cualquier producto del catálogo."""
    variante_a = crear_variante("Anillo", "100")
    variante_b = crear_variante("Cadena", "200")
    con_stock(variante_a, 5)
    con_stock(variante_b, 5)

    promo = servicio_promociones.crear_promocion(
        db, autor,
        nombre="TodosProductos",
        tipo=TipoPromocion.DOS_X_UNO,
        alcances=[{"tipo_alcance": TipoAlcance.TODOS_PRODUCTOS, "referencia_id": 0}],
    )

    # productos_alcanzados devuelve None (= todos)
    resultado = servicio_promociones.productos_alcanzados(db, promo)
    assert resultado is None


def test_alcance_todos_categorias_devuelve_none(db, autor):
    """TODOS_CATEGORIAS también devuelve None de productos_alcanzados."""
    promo = servicio_promociones.crear_promocion(
        db, autor,
        nombre="TodasCategorias",
        tipo=TipoPromocion.DOS_X_UNO,
        alcances=[{"tipo_alcance": TipoAlcance.TODOS_CATEGORIAS, "referencia_id": 0}],
    )
    assert servicio_promociones.productos_alcanzados(db, promo) is None


# ============================================================================
# ALCANCE — SUCURSAL (PUNTO DE VENTA)
# ============================================================================


def test_alcance_sucursal_filtra_por_punto_de_venta(db, autor, local, otro_local):
    """Una promo restringida al local A no aplica en el local B."""
    promo = servicio_promociones.crear_promocion(
        db, autor,
        nombre="Solo Olmos",
        tipo=TipoPromocion.DOS_X_UNO,
        alcances=[
            {"tipo_alcance": TipoAlcance.TODOS_PRODUCTOS, "referencia_id": 0},
            {"tipo_alcance": TipoAlcance.PUNTO_DE_VENTA, "referencia_id": local.id},
        ],
    )

    assert servicio_promociones.aplica_en_contexto(promo, local.id) is True
    assert servicio_promociones.aplica_en_contexto(promo, otro_local.id) is False


def test_alcance_sucursal_vacia_aplica_siempre(db, autor, local, otro_local):
    """Una promo sin restricción de sucursal aplica en cualquier local."""
    promo = servicio_promociones.crear_promocion(
        db, autor,
        nombre="Todos los locales",
        tipo=TipoPromocion.DOS_X_UNO,
        alcances=[{"tipo_alcance": TipoAlcance.TODOS_PRODUCTOS, "referencia_id": 0}],
    )

    assert servicio_promociones.aplica_en_contexto(promo, local.id) is True
    assert servicio_promociones.aplica_en_contexto(promo, otro_local.id) is True
    assert servicio_promociones.aplica_en_contexto(promo, None) is True


# ============================================================================
# ALCANCE — MEDIO DE PAGO
# ============================================================================


def test_alcance_medio_de_pago_filtra(db, autor, efectivo):
    """Una promo restringida a efectivo no aplica con otro medio conocido."""
    tarjeta = MedioDePago(
        nombre="Tarjeta Test Promo",
        activo=True,
        es_sena=False,
        soporta_cuotas=False,
    )
    db.add(tarjeta)
    db.flush()

    promo = servicio_promociones.crear_promocion(
        db, autor,
        nombre="Solo Efectivo",
        tipo=TipoPromocion.DOS_X_UNO,
        alcances=[
            {"tipo_alcance": TipoAlcance.TODOS_PRODUCTOS, "referencia_id": 0},
            {"tipo_alcance": TipoAlcance.MEDIO_DE_PAGO, "referencia_id": efectivo.id},
        ],
    )

    assert servicio_promociones.aplica_en_contexto(promo, None, efectivo.id) is True
    assert servicio_promociones.aplica_en_contexto(promo, None, tarjeta.id) is False
    # Medio desconocido (carrito) no bloquea la aplicación automática
    assert servicio_promociones.aplica_en_contexto(promo, None, None) is True


# ============================================================================
# TIPO PORCENTAJE — APLICADO EN VENTA
# ============================================================================


def test_porcentaje_aplica_descuento_en_precio_final(
    db, autor, crear_variante, con_stock, venta_base, config
):
    """Una promo 20% baja el precio final de los ítems alcanzados."""
    variante = crear_variante("Pulsera Test", "100")
    con_stock(variante, 5)

    promo = servicio_promociones.crear_promocion(
        db, autor,
        nombre="20pct Test",
        tipo=TipoPromocion.PORCENTAJE,
        porcentaje_descuento=20,
        alcances=[{"tipo_alcance": TipoAlcance.TODOS_PRODUCTOS, "referencia_id": 0}],
    )
    db.flush()

    servicio_ventas.agregar_item(db, autor, venta_base, variante_id=variante.id)
    db.flush()

    item = venta_base.items[0]
    assert item.en_promocion is True
    # 100 * 0.80 = 80
    assert Decimal(item.precio_final) == Decimal("80")
    assert venta_base.promocion_id == promo.id


def test_porcentaje_no_aplica_si_hay_descuento_item(
    db, autor, crear_variante, con_stock, venta_base, config
):
    """Un ítem con descuento manual no entra en la promo de porcentaje.

    Secuencia: agregar ítem sin promo activa → aplicar descuento →
    crear promo → agregar otro ítem (fuerza recálculo) → el primero
    NO entra en la promo porque tiene descuento.
    """
    from app.services import descuentos as servicio_descuentos

    variante_a = crear_variante("Anillo Test Dcto", "200")
    variante_b = crear_variante("Cadena Test Dcto", "100")
    con_stock(variante_a, 5)
    con_stock(variante_b, 5)

    motivo = servicio_descuentos.crear_motivo(
        db, autor, nombre="Garantia Test", porcentaje_sugerido=None
    )

    # 1. Agregar ítem A (no hay promo aún)
    servicio_ventas.agregar_item(db, autor, venta_base, variante_id=variante_a.id)
    db.flush()

    # 2. Aplicar descuento al ítem A (posible porque no está en promo)
    servicio_ventas.aplicar_descuento_item(
        db, autor, venta_base, venta_base.items[0].id,
        motivo_id=motivo.id, porcentaje=Decimal("10"),
    )

    # 3. Crear promo PORCENTAJE 50%
    servicio_promociones.crear_promocion(
        db, autor,
        nombre="50pct Test",
        tipo=TipoPromocion.PORCENTAJE,
        porcentaje_descuento=50,
        alcances=[{"tipo_alcance": TipoAlcance.TODOS_PRODUCTOS, "referencia_id": 0}],
    )
    db.flush()

    # 4. Agregar ítem B → fuerza recálculo
    servicio_ventas.agregar_item(db, autor, venta_base, variante_id=variante_b.id)
    db.flush()

    # Ítem A tiene descuento → NO debe estar en promoción
    item_a = next(i for i in venta_base.items if i.variante_id == variante_a.id)
    item_b = next(i for i in venta_base.items if i.variante_id == variante_b.id)
    assert item_a.en_promocion is False
    # Ítem B sin descuento → SÍ entra en la promo
    assert item_b.en_promocion is True


def test_porcentaje_no_se_aplica_en_sucursal_incorrecta(
    db, autor, crear_punto_de_venta, crear_variante, config
):
    """Promo restringida al local A no aplica en venta abierta desde local B."""
    local_a = crear_punto_de_venta("PA1", "Local A Test Suc", TipoPuntoVenta.LOCAL)
    local_b = crear_punto_de_venta("PB1", "Local B Test Suc", TipoPuntoVenta.LOCAL)

    equipo_b = Dispositivo(punto_de_venta_id=local_b.id, activo=True, descripcion="Celu B2")
    db.add(equipo_b)
    db.flush()
    venta_b = servicio_ventas.iniciar_venta(db, autor, equipo_b, LIBRE)

    variante = crear_variante("Collar Test Suc", "150")
    servicio_stock.aplicar_movimiento(
        db, autor,
        tipo=TipoMovimiento.INGRESO_PROVEEDOR,
        variante_id=variante.id,
        cantidad=5,
        punto_venta_destino_id=local_b.id,
    )

    servicio_promociones.crear_promocion(
        db, autor,
        nombre="Solo Local A Promo",
        tipo=TipoPromocion.PORCENTAJE,
        porcentaje_descuento=30,
        alcances=[
            {"tipo_alcance": TipoAlcance.TODOS_PRODUCTOS, "referencia_id": 0},
            {"tipo_alcance": TipoAlcance.PUNTO_DE_VENTA, "referencia_id": local_a.id},
        ],
    )
    db.flush()

    servicio_ventas.agregar_item(db, autor, venta_b, variante_id=variante.id)
    db.flush()

    # La promo no aplica (venta en local_b, promo restringida a local_a)
    assert venta_b.promocion_id is None
    assert venta_b.items[0].en_promocion is False
