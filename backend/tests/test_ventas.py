"""
Tests del módulo de ventas.

El foco está en las tres reglas que, si se rompen, cuestan plata:

  1. Los descuentos: de 5 en 5, con tope del 50% controlado SUMANDO y precio
     calculado ENCADENANDO.
  2. Las promociones: se cobran las más caras y quedan en $0 las más
     baratas de cada grupo COMPLETO.
  3. La confirmación: stock, puntos y señas se aplican juntos o no se aplica
     ninguno.

Lo cuarto es el aislamiento por dispositivo: una vendedora no ve ni toca
ventas de otro local.
"""

from decimal import Decimal

import pytest

from app.core.device_scope import DeviceScope
from app.core.permisos import ROL_CUENTA_MAESTRA, ROL_VENDEDOR
from app.models.cliente import PuntoCliente, TipoPunto
from app.models.configuracion import ConfiguracionSistema
from app.models.dispositivo import Dispositivo
from app.models.promocion import TipoAlcance, TipoPromocion
from app.models.punto_de_venta import TipoPuntoVenta
from app.models.stock import MovimientoStock, TipoMovimiento
from app.models.venta import EstadoVenta
from app.services import categorias as servicio_categorias
from app.services import clientes as servicio_clientes
from app.services import descuentos as servicio_descuentos
from app.services import medios_pago as servicio_medios
from app.services import productos as servicio_productos
from app.services import promociones as servicio_promociones
from app.services import proveedores as servicio_proveedores
from app.services import senas as servicio_senas
from app.services import stock as servicio_stock
from app.services import ventas as servicio
from app.services.roles import NoEncontrado, ReglaDeNegocio

LIBRE = DeviceScope(restringido=False)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def autor(crear_usuario):
    return crear_usuario("admin", ROL_CUENTA_MAESTRA)


@pytest.fixture
def config(db, autor):
    """
    Redondeo de 1 peso: los tests de descuento comparan importes exactos, y
    con un múltiplo grande el redondeo taparía la cuenta que se quiere
    verificar. El de 100 tiene su propio test.
    """
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
    return crear_punto_de_venta("MPO", "Patio Olmos", TipoPuntoVenta.LOCAL)


@pytest.fixture
def otro_local(crear_punto_de_venta):
    return crear_punto_de_venta("MPJ", "Paseo del Jockey", TipoPuntoVenta.LOCAL)


@pytest.fixture
def dispositivo(db, local):
    equipo = Dispositivo(punto_de_venta_id=local.id, activo=True, descripcion="Celu 1")
    db.add(equipo)
    db.flush()
    return equipo


@pytest.fixture
def catalogo(db, autor, config):
    """Categoría y proveedor con dólar a $1: así `precio_usd` es el precio final."""
    categoria = servicio_categorias.crear_categoria(db, autor, nombre="Plata")
    proveedor = servicio_proveedores.crear_proveedor(
        db, autor, nombre="Joyas del Sur", dolar_actual=Decimal("1")
    )
    return categoria, proveedor


@pytest.fixture
def crear_variante(db, autor, catalogo):
    """Fábrica de productos: devuelve la variante BASE, que es la que tiene stock."""
    categoria, proveedor = catalogo

    def _crear(descripcion: str, precio: str, descuento_producto: str = "0"):
        producto = servicio_productos.crear_producto(
            db, autor,
            categoria_id=categoria.id,
            proveedor_id=proveedor.id,
            precio_usd=Decimal(precio),
            descripcion=descripcion,
        )
        producto.descuento_producto = Decimal(descuento_producto)
        db.flush()
        return producto.variantes[0]

    return _crear


@pytest.fixture
def con_stock(db, autor, local):
    """Deja unidades en el local, ingresadas como corresponde: con movimiento."""

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
    """
    El medio que siembra la migración 0024, no uno nuevo: sin al menos un
    medio de pago no se puede confirmar ninguna venta el día que se instala,
    así que el seed lo trae y crear otro "Efectivo" choca contra el UNIQUE.
    """
    return next(m for m in servicio_medios.listar_medios(db) if m.nombre == "Efectivo")


@pytest.fixture
def medio_sena(db):
    """El medio marcado `es_sena`, que también viene del seed."""
    return servicio_medios.medio_de_sena(db)


@pytest.fixture
def venta(db, autor, dispositivo):
    return servicio.iniciar_venta(db, autor, dispositivo, LIBRE)


@pytest.fixture
def cliente(db, autor):
    return servicio_clientes.crear_cliente(db, autor, nombre="Leandra Carballo", dni="39059158")


def _cobrar_todo(db, autor, venta, medio):
    """Registra un único pago que cubre la venta entera."""
    a_cobrar = sum((Decimal(i.precio_final) for i in venta.items), Decimal("0"))
    return servicio.registrar_pagos(
        db, autor, venta, [{"medio_de_pago_id": medio.id, "monto": a_cobrar}]
    )


# ============================================================================
# DESCUENTOS
# ============================================================================


def test_porcentaje_fuera_de_la_lista_se_rechaza():
    """De 5 en 5 y hasta 50: la lista es la interfaz, no un campo libre."""
    for valido in (5, 25, 50):
        assert servicio_descuentos.validar_porcentaje(valido) == Decimal(valido)

    for invalido in (7, 12.5, 55, 0, -10):
        with pytest.raises(ReglaDeNegocio):
            servicio_descuentos.validar_porcentaje(invalido)


def test_el_tope_se_controla_sumando_no_encadenando():
    """
    30% + 30% da 60% sumado y 51% encadenado.

    Es EL test del tope: si se controlara encadenando, ese caso pasaría por
    debajo del límite de 50 y el cliente se llevaría el producto a menos de
    la mitad.
    """
    with pytest.raises(ReglaDeNegocio, match="60%"):
        servicio_descuentos.validar_tope(Decimal("30"), Decimal("30"))

    # Encadenado, ese mismo par descuenta 51%: más que el tope.
    efectivo = servicio_descuentos.calcular_descuento_total(Decimal("30"), Decimal("30"))
    assert efectivo == Decimal("51.00")

    # Justo en el tope sí pasa.
    servicio_descuentos.validar_tope(Decimal("20"), Decimal("30"))


def test_el_precio_se_calcula_encadenando():
    """20% y 30% sobre $10.000 dan $5.600, no $5.000 (que sería sumar)."""
    assert servicio_descuentos.aplicar_descuentos(
        Decimal("10000"), Decimal("20"), Decimal("30"), Decimal("1")
    ) == Decimal("5600")


def test_el_redondeo_del_descuento_va_hacia_abajo():
    """
    El precio de lista redondea hacia arriba y el descontado hacia abajo.

    Los dos por el mismo motivo: el redondeo no puede jugar en contra de
    quien está del otro lado. $9.999 al 10% da 8.999,1 y con múltiplo 100
    queda en 8.900 — si fuera hacia arriba, el 10% prometido sería 9,99%.
    """
    assert servicio_descuentos.aplicar_descuentos(
        Decimal("9999"), Decimal("0"), Decimal("10"), Decimal("100")
    ) == Decimal("8900")


def test_el_descuento_nunca_deja_el_precio_en_cero(db):
    """
    Con múltiplo 100, un producto de $80 al 50% daría $40 y el FLOOR lo
    dejaría en $0. Regalarlo no es lo que pidió nadie.
    """
    resultado = servicio_descuentos.aplicar_descuentos(
        Decimal("80"), Decimal("0"), Decimal("50"), Decimal("100")
    )
    assert resultado > 0


def test_descuento_en_venta_respeta_motivo_y_tope(db, autor, venta, crear_variante):
    """El motivo es obligatorio y el tope suma el descuento propio del producto."""
    motivo = servicio_descuentos.crear_motivo(
        db, autor, nombre="Cumpleaños", porcentaje_sugerido=Decimal("20")
    )
    # El producto ya trae 40% propio: con 20% más suman 60% y no entra.
    variante = crear_variante("Anillo", "10000", descuento_producto="40")
    item, _ = servicio.agregar_item(db, autor, venta, variante_id=variante.id)

    with pytest.raises(ReglaDeNegocio, match="60%"):
        servicio.aplicar_descuento_item(
            db, autor, venta, item.id, motivo_id=motivo.id, porcentaje=Decimal("20")
        )

    # Con 10% suman 50%: justo el tope.
    servicio.aplicar_descuento_item(
        db, autor, venta, item.id, motivo_id=motivo.id, porcentaje=Decimal("10")
    )
    # Encadenado: 10000 × 0,60 × 0,90 = 5400.
    assert Decimal(item.precio_final) == Decimal("5400")


def test_porcentaje_modificado_queda_registrado(db, autor, venta, crear_variante):
    """
    Si la vendedora se aparta del sugerido, queda el rastro.

    No la bloquea —el caso "hoy hacemos 30 en vez de 20" es real— pero el
    reporte de descuentos tiene que poder distinguirlo.
    """
    motivo = servicio_descuentos.crear_motivo(
        db, autor, nombre="Empleada", porcentaje_sugerido=Decimal("20")
    )
    variante = crear_variante("Cadena", "10000")
    item, _ = servicio.agregar_item(db, autor, venta, variante_id=variante.id)

    servicio.aplicar_descuento_item(
        db, autor, venta, item.id, motivo_id=motivo.id, porcentaje=Decimal("20")
    )
    assert item.porcentaje_modificado is False

    servicio.aplicar_descuento_item(
        db, autor, venta, item.id, motivo_id=motivo.id, porcentaje=Decimal("30")
    )
    assert item.porcentaje_modificado is True


def test_motivo_sin_sugerido_obliga_a_elegir(db, autor, venta, crear_variante):
    motivo = servicio_descuentos.crear_motivo(db, autor, nombre="Liquidación")
    variante = crear_variante("Pulsera", "5000")
    item, _ = servicio.agregar_item(db, autor, venta, variante_id=variante.id)

    with pytest.raises(ReglaDeNegocio, match="porcentaje sugerido"):
        servicio.aplicar_descuento_item(
            db, autor, venta, item.id, motivo_id=motivo.id, porcentaje=None
        )


# ============================================================================
# PROMOCIONES
# ============================================================================


def _promo(db, autor, categoria, tipo, nombre="Promo"):
    return servicio_promociones.crear_promocion(
        db, autor,
        nombre=nombre,
        tipo=tipo,
        alcances=[{"tipo_alcance": TipoAlcance.CATEGORIA, "referencia_id": categoria.id}],
    )


def test_dos_x_uno_deja_en_cero_las_mas_baratas(
    db, autor, venta, crear_variante, catalogo
):
    """
    Cinco productos con un 2x1: dos grupos completos, dos unidades gratis, y
    las gratis son las MÁS BARATAS.

    Los grupos se arman de más caro a más barato: [100, 90] y [80, 70],
    y sobra el de 60, que no completa ninguno y se cobra entero. Se regalan
    90 y 70 — nunca 100, que es la más cara de su grupo.
    """
    categoria, _ = catalogo
    _promo(db, autor, categoria, TipoPromocion.DOS_X_UNO, "2x1 Plata")

    for precio in ("100", "90", "80", "70", "60"):
        variante = crear_variante(f"Anillo {precio}", precio)
        servicio.agregar_item(db, autor, venta, variante_id=variante.id)

    gratis = sorted(Decimal(i.precio_unitario) for i in venta.items if i.en_promocion)
    assert gratis == [Decimal("70"), Decimal("90")]
    # 100 + 80 + 60 = 240.
    assert Decimal(venta.total) == Decimal("240")


def test_tres_x_dos_cobra_dos_por_grupo(db, autor, venta, crear_variante, catalogo):
    """
    Siete productos con un 3x2: dos grupos completos, dos unidades gratis.

    Con [100, 90, 80, 70, 60, 50, 40] se regalan 80 y 50: la más barata de
    cada grupo de tres. Sobra uno, que se cobra entero.
    """
    categoria, _ = catalogo
    _promo(db, autor, categoria, TipoPromocion.TRES_X_DOS, "3x2 Acero")

    for precio in ("100", "90", "80", "70", "60", "50", "40"):
        variante = crear_variante(f"Dije {precio}", precio)
        servicio.agregar_item(db, autor, venta, variante_id=variante.id)

    gratis = sorted(Decimal(i.precio_unitario) for i in venta.items if i.en_promocion)
    assert gratis == [Decimal("50"), Decimal("80")]
    # 100 + 90 + 70 + 60 + 40 = 360: se cobran dos por grupo más el sobrante.
    assert Decimal(venta.total) == Decimal("360")


def test_grupo_incompleto_se_cobra_entero(db, autor, venta, crear_variante, catalogo):
    """Un solo producto con un 2x1 activo no regala nada."""
    categoria, _ = catalogo
    _promo(db, autor, categoria, TipoPromocion.DOS_X_UNO)

    variante = crear_variante("Anillo solo", "1000")
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)

    assert venta.promocion_id is None
    assert Decimal(venta.total) == Decimal("1000")


def test_promocion_bloquea_descuento_en_el_item(
    db, autor, venta, crear_variante, catalogo
):
    """Promoción y descuento sobre la misma unidad serían dos beneficios."""
    categoria, _ = catalogo
    _promo(db, autor, categoria, TipoPromocion.DOS_X_UNO)
    motivo = servicio_descuentos.crear_motivo(
        db, autor, nombre="Cumpleaños", porcentaje_sugerido=Decimal("10")
    )

    for precio in ("1000", "800"):
        variante = crear_variante(f"Aro {precio}", precio)
        servicio.agregar_item(db, autor, venta, variante_id=variante.id)

    regalado = next(i for i in venta.items if i.en_promocion)
    with pytest.raises(ReglaDeNegocio, match="promoción"):
        servicio.aplicar_descuento_item(
            db, autor, venta, regalado.id, motivo_id=motivo.id, porcentaje=Decimal("10")
        )


def test_quitar_un_item_recalcula_la_promocion(
    db, autor, venta, crear_variante, catalogo
):
    """
    Sacar un producto del carrito no puede dejar regalado uno que ya no
    completa ningún grupo. Es lo que garantiza el reset de `_recalcular`.
    """
    categoria, _ = catalogo
    _promo(db, autor, categoria, TipoPromocion.DOS_X_UNO)

    ids = []
    for precio in ("1000", "800"):
        variante = crear_variante(f"Aro {precio}", precio)
        item, _ = servicio.agregar_item(db, autor, venta, variante_id=variante.id)
        ids.append(item.id)

    assert Decimal(venta.total) == Decimal("1000")

    servicio.quitar_item(db, autor, venta, ids[0])
    assert not any(i.en_promocion for i in venta.items)
    assert Decimal(venta.total) == Decimal("800")


# ============================================================================
# STOCK EN CERO
# ============================================================================


def test_stock_cero_avisa_pero_no_bloquea(db, autor, venta, crear_variante):
    """
    La vendedora tiene el producto en la mano: el que está mal es el sistema.

    Frenar la venta ahí significaría no vender algo que está sobre el
    mostrador, así que el aviso viaja como dato, no como error.
    """
    variante = crear_variante("Anillo fantasma", "1000")
    item, aviso = servicio.agregar_item(db, autor, venta, variante_id=variante.id)

    assert item is not None
    assert aviso is not None and "controlá bien el código" in aviso


def test_confirmar_sin_stock_deja_la_cantidad_en_negativo(
    db, autor, venta, crear_variante, efectivo, local
):
    """
    El negativo es la señal de que ese artículo necesita una auditoría de
    inventario. Lo que NO puede pasar es que la venta no se registre.
    """
    variante = crear_variante("Anillo fantasma", "1000")
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)
    _cobrar_todo(db, autor, venta, efectivo)
    servicio.confirmar_venta(db, autor, venta, LIBRE)

    assert venta.estado == EstadoVenta.CONFIRMADA
    assert servicio_stock.cantidad_en(db, variante.id, local.id) == -1


def test_el_faltante_sigue_bloqueando_a_los_demas_movimientos(
    db, autor, crear_variante, local
):
    """
    La excepción es SOLO de la venta: un remito no puede mandar mercadería
    que no está.
    """
    variante = crear_variante("Anillo", "1000")
    with pytest.raises(ReglaDeNegocio, match="stock suficiente"):
        servicio_stock.aplicar_movimiento(
            db, autor,
            tipo=TipoMovimiento.BAJA,
            variante_id=variante.id,
            cantidad=1,
            punto_venta_origen_id=local.id,
        )


# ============================================================================
# COBRO
# ============================================================================


def test_recargo_solo_sobre_la_parte_financiada(
    db, autor, venta, crear_variante, con_stock, efectivo
):
    """
    Mitad efectivo y mitad tarjeta al 20%: el recargo es de la mitad
    financiada, no del total.

    Es el error caro del módulo: cobrado sobre el total serían $2.000 de
    interés en vez de $1.000.
    """
    tarjeta = servicio_medios.crear_medio(db, autor, nombre="Visa", soporta_cuotas=True)
    plan = servicio_medios.crear_plan(
        db, autor, tarjeta.id,
        cuotas=6, recargo_cliente=Decimal("20"), costo_medio=Decimal("8"),
    )

    variante = crear_variante("Anillo", "10000")
    con_stock(variante, 5)
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)

    servicio.registrar_pagos(db, autor, venta, [
        {"medio_de_pago_id": efectivo.id, "monto": Decimal("5000")},
        {"medio_de_pago_id": tarjeta.id, "monto": Decimal("5000"),
         "plan_cuotas_id": plan.id},
    ])

    assert Decimal(venta.recargo_total) == Decimal("1000")
    assert Decimal(venta.total) == Decimal("11000")


def test_costo_medio_no_toca_lo_que_paga_el_cliente(
    db, autor, venta, crear_variante, efectivo
):
    """
    `costo_medio` es lo que cobra la terminal y solo va a reportes.

    Un plan con 0% de recargo y 8% de costo se cobra sin un peso de más.
    """
    tarjeta = servicio_medios.crear_medio(db, autor, nombre="Maestro", soporta_cuotas=True)
    plan = servicio_medios.crear_plan(
        db, autor, tarjeta.id,
        cuotas=1, recargo_cliente=Decimal("0"), costo_medio=Decimal("8"),
    )

    variante = crear_variante("Anillo", "10000")
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)
    servicio.registrar_pagos(db, autor, venta, [
        {"medio_de_pago_id": tarjeta.id, "monto": Decimal("10000"),
         "plan_cuotas_id": plan.id},
    ])

    assert Decimal(venta.recargo_total) == Decimal("0")
    assert Decimal(venta.total) == Decimal("10000")


def test_plan_por_debajo_del_monto_minimo_no_se_ofrece(db, autor):
    """La vendedora solo ve los planes que el monto habilita."""
    tarjeta = servicio_medios.crear_medio(db, autor, nombre="Visa", soporta_cuotas=True)
    servicio_medios.crear_plan(
        db, autor, tarjeta.id,
        cuotas=12, recargo_cliente=Decimal("30"), costo_medio=Decimal("0"),
        monto_minimo=Decimal("50000"),
    )

    assert servicio_medios.planes_disponibles(db, tarjeta.id, Decimal("10000")) == []
    assert len(servicio_medios.planes_disponibles(db, tarjeta.id, Decimal("50000"))) == 1


def test_motivo_habilita_cuotas_sin_interes_por_debajo_del_minimo(db, autor):
    """
    Los planes SIN INTERÉS se ofrecen igual si el motivo lo habilita.

    Solo los sin interés: un motivo de descuento no puede habilitar un plan
    que le sale más caro al cliente.
    """
    tarjeta = servicio_medios.crear_medio(db, autor, nombre="Visa", soporta_cuotas=True)
    sin_interes = servicio_medios.crear_plan(
        db, autor, tarjeta.id,
        cuotas=3, recargo_cliente=Decimal("0"), costo_medio=Decimal("5"),
        monto_minimo=Decimal("90000"),
    )
    servicio_medios.crear_plan(
        db, autor, tarjeta.id,
        cuotas=12, recargo_cliente=Decimal("30"), costo_medio=Decimal("0"),
        monto_minimo=Decimal("90000"),
    )

    disponibles = servicio_medios.planes_disponibles(
        db, tarjeta.id, Decimal("10000"), habilita_sin_interes=True
    )
    assert [p.id for p in disponibles] == [sin_interes.id]


def test_los_pagos_tienen_que_cubrir_el_total(db, autor, venta, crear_variante, efectivo):
    variante = crear_variante("Anillo", "10000")
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)

    with pytest.raises(ReglaDeNegocio, match="coincidir"):
        servicio.registrar_pagos(db, autor, venta, [
            {"medio_de_pago_id": efectivo.id, "monto": Decimal("9000")},
        ])


def test_no_se_admiten_mas_de_dos_medios(db, autor, venta, crear_variante, efectivo):
    variante = crear_variante("Anillo", "3000")
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)

    with pytest.raises(ReglaDeNegocio, match="hasta 2"):
        servicio.registrar_pagos(db, autor, venta, [
            {"medio_de_pago_id": efectivo.id, "monto": Decimal("1000")},
            {"medio_de_pago_id": efectivo.id, "monto": Decimal("1000")},
            {"medio_de_pago_id": efectivo.id, "monto": Decimal("1000")},
        ])


# ============================================================================
# CONFIRMACIÓN
# ============================================================================


def test_confirmar_descuenta_stock_y_genera_codigo(
    db, autor, venta, crear_variante, con_stock, efectivo, local
):
    variante = crear_variante("Anillo", "10000")
    con_stock(variante, 5)
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)
    _cobrar_todo(db, autor, venta, efectivo)

    servicio.confirmar_venta(db, autor, venta, LIBRE)

    assert venta.estado == EstadoVenta.CONFIRMADA
    assert servicio_stock.cantidad_en(db, variante.id, local.id) == 3

    assert venta.codigo_cambio is not None
    assert len(venta.codigo_cambio) == 8
    # Sin caracteres que se confundan al leer una letra escrita a mano.
    assert not set(venta.codigo_cambio) & set("IO01")

    # Un movimiento de 2, no dos de 1: el movimiento describe lo que salió.
    movimiento = db.query(MovimientoStock).filter_by(referencia_venta_id=venta.id).one()
    assert movimiento.tipo == TipoMovimiento.VENTA
    assert movimiento.cantidad == 2


def test_confirmar_suma_puntos_al_cliente(
    db, autor, venta, crear_variante, con_stock, efectivo, cliente
):
    variante = crear_variante("Anillo", "10000")
    con_stock(variante, 5)
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)
    servicio.asociar_cliente(db, autor, venta, cliente.id)
    _cobrar_todo(db, autor, venta, efectivo)

    servicio.confirmar_venta(db, autor, venta, LIBRE)

    esperados = servicio_clientes.puntos_por_venta(venta.total)
    assert venta.puntos_acumulados == esperados
    assert servicio_clientes.saldo_puntos(db, cliente.id) == esperados


def test_venta_sin_cliente_se_completa(
    db, autor, venta, crear_variante, con_stock, efectivo
):
    """El caso normal del mostrador: nadie se identifica."""
    variante = crear_variante("Anillo", "10000")
    con_stock(variante, 5)
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)
    _cobrar_todo(db, autor, venta, efectivo)

    servicio.confirmar_venta(db, autor, venta, LIBRE)

    assert venta.estado == EstadoVenta.CONFIRMADA
    assert venta.cliente_id is None
    assert venta.puntos_acumulados == 0


def test_confirmar_es_atomico(db, autor, venta, crear_variante, con_stock, efectivo, local):
    """
    Si algo falla a mitad de la confirmación, no queda NADA aplicado.

    Se fuerza el fallo con un código de cambio imposible de generar. Sin
    atomicidad, el stock quedaría descontado por una venta que nunca se
    cerró.
    """
    variante = crear_variante("Anillo", "10000")
    con_stock(variante, 5)
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)
    _cobrar_todo(db, autor, venta, efectivo)

    antes = servicio_stock.cantidad_en(db, variante.id, local.id)

    def _explota(_db):
        raise ReglaDeNegocio("falla simulada al generar el código de cambio")

    original = servicio.generar_codigo_cambio
    servicio.generar_codigo_cambio = _explota
    # Un SAVEPOINT y no `db.rollback()`: el rollback llano se llevaría puesta
    # la transacción del test entera —con el producto y el local que armaron
    # el escenario— y el assert de abajo no tendría contra qué comparar. El
    # savepoint deshace exactamente lo que hizo la confirmación, que es lo
    # que se quiere medir.
    punto = db.begin_nested()
    try:
        with pytest.raises(ReglaDeNegocio):
            servicio.confirmar_venta(db, autor, venta, LIBRE)
    finally:
        punto.rollback()
        servicio.generar_codigo_cambio = original

    assert servicio_stock.cantidad_en(db, variante.id, local.id) == antes
    assert venta.estado == EstadoVenta.EN_CURSO


def test_no_se_confirma_una_venta_sin_productos(db, autor, venta):
    with pytest.raises(ReglaDeNegocio, match="sin productos"):
        servicio.confirmar_venta(db, autor, venta, LIBRE)


def test_no_se_confirma_sin_medios_de_pago(db, autor, venta, crear_variante, con_stock):
    variante = crear_variante("Anillo", "10000")
    con_stock(variante, 5)
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)

    with pytest.raises(ReglaDeNegocio, match="medios de pago"):
        servicio.confirmar_venta(db, autor, venta, LIBRE)


def test_una_venta_confirmada_no_se_modifica(
    db, autor, venta, crear_variante, con_stock, efectivo
):
    variante = crear_variante("Anillo", "10000")
    con_stock(variante, 5)
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)
    _cobrar_todo(db, autor, venta, efectivo)
    servicio.confirmar_venta(db, autor, venta, LIBRE)

    with pytest.raises(ReglaDeNegocio, match="confirmada"):
        servicio.agregar_item(db, autor, venta, variante_id=variante.id)


# ============================================================================
# SEÑAS
# ============================================================================


def test_sena_cubre_parte_y_el_resto_va_a_otro_medio(
    db, autor, venta, crear_variante, con_stock, efectivo, cliente, medio_sena
):
    """
    Si la seña no alcanza, se usa lo que hay y el resto lo cubre otro medio.

    No es un error: es el caso normal, y hacer que la vendedora calcule la
    diferencia a mano sería pedirle la cuenta que el sistema tiene que hacer.
    """
    sena = servicio_senas.registrar_sena(
        db, autor, cliente_id=cliente.id, monto=Decimal("4000")
    )

    variante = crear_variante("Anillo", "10000")
    con_stock(variante, 5)
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)
    servicio.asociar_cliente(db, autor, venta, cliente.id)

    servicio.registrar_pagos(db, autor, venta, [
        {"medio_de_pago_id": medio_sena.id, "monto": Decimal("4000"), "sena_id": sena.id},
        {"medio_de_pago_id": efectivo.id, "monto": Decimal("6000")},
    ])
    servicio.confirmar_venta(db, autor, venta, LIBRE)

    assert Decimal(sena.saldo) == Decimal("0")
    # Sin saldo deja de ofrecerse, pero sigue explicando la venta.
    assert sena.activo is False
    assert servicio_senas.senas_disponibles(db, cliente.id) == []


def test_no_se_paga_con_la_sena_de_otro_cliente(
    db, autor, venta, crear_variante, cliente, medio_sena
):
    otro = servicio_clientes.crear_cliente(db, autor, nombre="Otro Cliente", dni="11222333")
    sena_ajena = servicio_senas.registrar_sena(
        db, autor, cliente_id=otro.id, monto=Decimal("5000")
    )

    variante = crear_variante("Anillo", "5000")
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)
    servicio.asociar_cliente(db, autor, venta, cliente.id)

    with pytest.raises(ReglaDeNegocio, match="otro cliente"):
        servicio.registrar_pagos(db, autor, venta, [
            {"medio_de_pago_id": medio_sena.id, "monto": Decimal("5000"),
             "sena_id": sena_ajena.id},
        ])


def test_sena_exige_cliente_en_la_venta(db, autor, venta, crear_variante, cliente, medio_sena):
    sena = servicio_senas.registrar_sena(
        db, autor, cliente_id=cliente.id, monto=Decimal("5000")
    )
    variante = crear_variante("Anillo", "5000")
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)

    with pytest.raises(ReglaDeNegocio, match="asociar el cliente"):
        servicio.registrar_pagos(db, autor, venta, [
            {"medio_de_pago_id": medio_sena.id, "monto": Decimal("5000"),
             "sena_id": sena.id},
        ])


# ============================================================================
# ANULACIÓN
# ============================================================================


def test_anular_revierte_stock_puntos_y_sena(
    db, autor, venta, crear_variante, con_stock, efectivo, cliente, local, medio_sena
):
    """
    Las tres reversiones en la misma transacción.

    Devolver el stock sin sacar los puntos dejaría al cliente con puntos de
    una compra que no existió.
    """
    sena = servicio_senas.registrar_sena(
        db, autor, cliente_id=cliente.id, monto=Decimal("4000")
    )

    variante = crear_variante("Anillo", "10000")
    con_stock(variante, 5)
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)
    servicio.asociar_cliente(db, autor, venta, cliente.id)
    servicio.registrar_pagos(db, autor, venta, [
        {"medio_de_pago_id": medio_sena.id, "monto": Decimal("4000"), "sena_id": sena.id},
        {"medio_de_pago_id": efectivo.id, "monto": Decimal("6000")},
    ])
    servicio.confirmar_venta(db, autor, venta, LIBRE)

    assert servicio_stock.cantidad_en(db, variante.id, local.id) == 4
    puntos_sumados = servicio_clientes.saldo_puntos(db, cliente.id)
    assert puntos_sumados > 0

    servicio.anular_venta(db, autor, venta, motivo="Se arrepintió")

    assert venta.estado == EstadoVenta.ANULADA
    assert servicio_stock.cantidad_en(db, variante.id, local.id) == 5
    assert servicio_clientes.saldo_puntos(db, cliente.id) == 0
    assert Decimal(sena.saldo) == Decimal("4000")
    assert sena.activo is True

    # Los importes NO se tocan: la venta ocurrió y la caja de ese día tiene
    # que poder explicarse.
    assert Decimal(venta.total) == Decimal("10000")


def test_los_puntos_se_revierten_con_un_ajuste_no_borrando(
    db, autor, venta, crear_variante, con_stock, efectivo, cliente
):
    """
    `puntos_cliente` es append-only: el historial muestra que se sumaron y
    que se sacaron, no que nunca se sumaron.
    """
    variante = crear_variante("Anillo", "10000")
    con_stock(variante, 5)
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)
    servicio.asociar_cliente(db, autor, venta, cliente.id)
    _cobrar_todo(db, autor, venta, efectivo)
    servicio.confirmar_venta(db, autor, venta, LIBRE)
    servicio.anular_venta(db, autor, venta)

    movimientos = servicio_clientes.historial_puntos(db, cliente.id)
    tipos = sorted(m.tipo for m in movimientos)
    assert tipos == [TipoPunto.ACUMULACION, TipoPunto.AJUSTE]


def test_solo_se_anulan_las_confirmadas(db, autor, venta, crear_variante):
    variante = crear_variante("Anillo", "10000")
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)

    with pytest.raises(ReglaDeNegocio, match="solo se anulan"):
        servicio.anular_venta(db, autor, venta)


def test_puntos_cliente_es_inmutable_en_la_base(db, autor, cliente):
    """
    La garantía vive en la base, no en el código: un UPDATE directo tiene
    que fallar aunque alguien evite el service.
    """
    from sqlalchemy.exc import DatabaseError

    movimiento = servicio_clientes.registrar_movimiento_puntos(
        db, autor, cliente_id=cliente.id, tipo=TipoPunto.ACUMULACION, cantidad=10
    )
    db.flush()

    with pytest.raises(DatabaseError):
        db.execute(
            PuntoCliente.__table__.update()
            .where(PuntoCliente.id == movimiento.id)
            .values(cantidad=9999)
        )
    db.rollback()


# ============================================================================
# CÓDIGO DE CAMBIO Y AISLAMIENTO
# ============================================================================


def test_el_codigo_de_cambio_encuentra_la_venta(
    db, autor, venta, crear_variante, con_stock, efectivo
):
    variante = crear_variante("Anillo", "10000")
    con_stock(variante, 5)
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)
    _cobrar_todo(db, autor, venta, efectivo)
    servicio.confirmar_venta(db, autor, venta, LIBRE)

    # Insensible a mayúsculas: se copia de un papel escrito a mano.
    encontrada = servicio.por_codigo_cambio(db, venta.codigo_cambio.lower())
    assert encontrada.id == venta.id

    with pytest.raises(NoEncontrado):
        servicio.por_codigo_cambio(db, "NOEXISTE")


def test_una_vendedora_no_ve_ventas_de_otro_local(
    db, autor, venta, otro_local, crear_variante
):
    ajeno = DeviceScope(restringido=True, punto_de_venta_id=otro_local.id)

    with pytest.raises(Exception) as error:
        servicio.obtener_venta(db, venta.id, ajeno)
    assert "403" in str(error.value) or "local asignado" in str(error.value)


def test_iniciar_dos_veces_devuelve_la_misma_venta(db, autor, dispositivo):
    """
    Dos ventas `en_curso` de la misma vendedora significan que una quedó
    huérfana, con productos que nadie va a cobrar.
    """
    primera = servicio.iniciar_venta(db, autor, dispositivo, LIBRE)
    segunda = servicio.iniciar_venta(db, autor, dispositivo, LIBRE)
    assert primera.id == segunda.id


def test_venta_en_curso_alimenta_el_banner(db, autor, dispositivo, local):
    assert servicio.venta_en_curso(db, autor.id, local.id) is None

    abierta = servicio.iniciar_venta(db, autor, dispositivo, LIBRE)
    assert servicio.venta_en_curso(db, autor.id, local.id).id == abierta.id


# ============================================================================
# API: PERMISOS Y AISLAMIENTO POR DISPOSITIVO
# ============================================================================
#
# Los tests de arriba prueban las reglas de negocio contra los services. Estos
# prueban la otra mitad: que la API no deje entrar por la puerta de al lado.
# Un service impecable con un endpoint sin `requiere_permiso` no protege nada.


@pytest.fixture
def equipo_en(db):
    """Registra un dispositivo activo en un local y devuelve su UUID."""

    def _crear(punto):
        equipo = Dispositivo(
            punto_de_venta_id=punto.id, activo=True, descripcion=f"Caja {punto.codigo}"
        )
        db.add(equipo)
        db.flush()
        return str(equipo.uuid)

    return _crear


def test_una_vendedora_no_toca_ventas_de_otro_local(
    client, db, crear_usuario, dar_permiso, roles, local, otro_local, equipo_en,
    autor, dispositivo, venta, crear_variante
):
    """
    El aislamiento por dispositivo, verificado end-to-end.

    La venta existe en Patio Olmos; la vendedora está parada en Paseo del
    Jockey. Cambiar un id a mano en la URL tiene que dar 403, no la venta.
    """
    variante = crear_variante("Anillo", "10000")
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)
    db.commit()

    crear_usuario("vende", ROL_VENDEDOR)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo="ventas", ver=True, crear=True)
    db.commit()

    client.cookies.set("device_uuid", equipo_en(otro_local))
    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})

    assert client.get(f"/api/v1/ventas/{venta.id}").status_code == 403

    # Y su listado no la incluye: no es que la esconda de a una, es que el
    # filtro por local se aplica a la consulta entera.
    resp = client.get("/api/v1/ventas")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_anular_exige_el_permiso_de_anulacion(
    client, db, crear_usuario, dar_permiso, roles, autor, venta, crear_variante,
    con_stock, efectivo
):
    """
    Vender y anular son dos permisos distintos. Una vendedora con acceso
    total al módulo de ventas sigue sin poder anular: `venta.anular` se
    asigna aparte, y es lo que reserva la operación a Supervisor y Dueño.
    """
    variante = crear_variante("Anillo", "10000")
    con_stock(variante, 5)
    servicio.agregar_item(db, autor, venta, variante_id=variante.id)
    _cobrar_todo(db, autor, venta, efectivo)
    servicio.confirmar_venta(db, autor, venta, LIBRE)
    db.commit()

    crear_usuario("vende", ROL_VENDEDOR)
    dar_permiso(
        rol_id=roles[ROL_VENDEDOR].id, modulo="ventas",
        ver=True, crear=True, editar=True, eliminar=True,
    )
    db.commit()

    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})
    resp = client.patch(f"/api/v1/ventas/{venta.id}/anular", json={"motivo": "prueba"})
    assert resp.status_code == 403


def test_el_descuento_exige_su_propio_permiso(
    client, db, crear_usuario, dar_permiso, roles, autor, venta, crear_variante
):
    """
    Descontar es una decisión comercial y no viene con el permiso de vender:
    `venta.descuento` se asigna aparte.
    """
    variante = crear_variante("Anillo", "10000")
    item, _ = servicio.agregar_item(db, autor, venta, variante_id=variante.id)
    motivo = servicio_descuentos.crear_motivo(
        db, autor, nombre="Cumpleaños", porcentaje_sugerido=Decimal("10")
    )
    db.commit()

    crear_usuario("vende", ROL_VENDEDOR)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo="ventas", ver=True, crear=True)
    db.commit()

    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})
    resp = client.post(
        f"/api/v1/ventas/{venta.id}/descuento",
        json={"item_id": item.id, "motivo_id": motivo.id, "porcentaje": 10},
    )
    assert resp.status_code == 403


def test_los_porcentajes_validos_los_sirve_la_api(
    client, db, crear_usuario, dar_permiso, roles
):
    """
    La lista sale del backend, de la MISMA constante que valida. Si la
    pantalla la tuviera escrita, terminaría ofreciendo un valor que la API
    rechaza y el error aparecería recién al guardar.
    """
    crear_usuario("vende", ROL_VENDEDOR)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo="ventas", ver=True)
    db.commit()

    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})
    datos = client.get("/api/v1/ventas/opciones-descuento").json()

    assert datos["porcentajes"] == list(servicio_descuentos.PORCENTAJES_VALIDOS)
    assert Decimal(datos["tope"]) == servicio_descuentos.TOPE_DESCUENTO


def test_el_aviso_de_stock_viaja_en_el_cuerpo_y_no_como_error(
    client, db, crear_usuario, dar_permiso, roles, local, equipo_en, crear_variante
):
    """
    Sin stock, agregar al carrito devuelve 201 con un aviso — no un 4xx.

    Es la diferencia entre avisar y bloquear, y es la que decide si se vende
    o no algo que está sobre el mostrador.
    """
    variante = crear_variante("Anillo fantasma", "10000")
    db.commit()

    crear_usuario("vende", ROL_VENDEDOR)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo="ventas", ver=True, crear=True)
    db.commit()

    client.cookies.set("device_uuid", equipo_en(local))
    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})

    venta_id = client.post("/api/v1/ventas").json()["id"]
    resp = client.post(
        f"/api/v1/ventas/{venta_id}/items", json={"variante_id": variante.id}
    )

    assert resp.status_code == 201
    assert resp.json()["aviso"] is not None
    assert len(resp.json()["venta"]["items"]) == 1


def test_el_recurso_de_promociones_no_abre_los_medios_de_pago(
    client, db, crear_usuario, dar_permiso, roles
):
    """
    El recurso `configuracion.promociones` existe para partir en dos lo que
    de otro modo sería un solo permiso.

    Sin él, habilitar al Supervisor a administrar promociones le abriría
    también los medios de pago y los motivos de descuento, que son de la
    Cuenta Maestra: ahí se define lo que se le cobra al cliente por
    financiar.

    El permiso se otorga acá a mano y no se toma del seed: en la base de
    tests los roles los crea una fixture DESPUÉS de correr las migraciones,
    así que el INSERT de la 0024 no encuentra a quién dárselo. Lo que este
    test verifica es la regla, que es lo que puede romperse al tocar código.
    """
    from app.core.permisos import ROL_SUPERVISOR

    crear_usuario("supervisora", ROL_SUPERVISOR)
    dar_permiso(
        rol_id=roles[ROL_SUPERVISOR].id,
        modulo="configuracion",
        recurso="configuracion.promociones",
        ver=True, crear=True, editar=True,
    )
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "supervisora", "password": "Test1234!"})

    assert client.get("/api/v1/configuracion/promociones").status_code == 200
    assert client.get("/api/v1/configuracion/medios-de-pago").status_code == 403
    assert client.get("/api/v1/configuracion/motivos-descuento").status_code == 403


def test_el_permiso_general_de_configuracion_llega_a_las_promociones(
    client, db, crear_usuario, dar_permiso, roles
):
    """
    La partición va en un solo sentido: quien tiene el permiso general del
    módulo llega también a sus recursos.

    Es la regla de `resolver_permiso` y hay que sostenerla acá, o la Cuenta
    Maestra y el Dueño perderían las promociones al agregarles un recurso
    propio.
    """
    from app.core.permisos import ROL_DUENO

    crear_usuario("duenio", ROL_DUENO)
    dar_permiso(
        rol_id=roles[ROL_DUENO].id, modulo="configuracion",
        ver=True, crear=True, editar=True,
    )
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "duenio", "password": "Test1234!"})

    assert client.get("/api/v1/configuracion/promociones").status_code == 200
    assert client.get("/api/v1/configuracion/medios-de-pago").status_code == 200
