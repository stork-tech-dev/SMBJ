"""
Tests del control de stock.

El foco está en la regla que gobierna el módulo: el stock NUNCA cambia sin un
movimiento que lo explique, y los dos se confirman o se descartan juntos. Lo
segundo en importancia es el aislamiento por dispositivo: un vendedor no
puede ver ni tocar mercadería de otro local.
"""

from decimal import Decimal

import pytest

from app.core.device_scope import DeviceScope, get_punto_de_venta_scope
from app.core.permisos import (
    ROL_AUDITOR,
    ROL_CUENTA_MAESTRA,
    ROL_DISTRIBUCION,
    ROL_DUENO,
    ROL_VENDEDOR,
)
from app.models.configuracion import ConfiguracionSistema
from app.models.punto_de_venta import TipoPuntoVenta
from app.models.remito import EstadoRemito
from app.models.stock import MovimientoStock, Stock, TipoMovimiento
from app.services import auditoria_inventario as servicio_auditoria
from app.services import bajas_stock as servicio_bajas
from app.services import categorias as servicio_categorias
from app.services import productos as servicio_productos
from app.services import proveedores as servicio_proveedores
from app.services import remitos as servicio_remitos
from app.services import stock as servicio
from app.services.roles import NoEncontrado, ReglaDeNegocio

# Sin restricción: es lo que devuelve `get_device_scope` para cualquier rol
# que no sea vendedor.
LIBRE = DeviceScope(restringido=False)


@pytest.fixture
def autor(crear_usuario):
    return crear_usuario("admin", ROL_CUENTA_MAESTRA)


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
    return crear_punto_de_venta("CD", "Depósito central", TipoPuntoVenta.CD)


@pytest.fixture
def local(crear_punto_de_venta):
    return crear_punto_de_venta("MPO", "Patio Olmos", TipoPuntoVenta.LOCAL)


@pytest.fixture
def otro_local(crear_punto_de_venta):
    return crear_punto_de_venta("MPJ", "Paseo del Jockey", TipoPuntoVenta.LOCAL)


@pytest.fixture
def variante(db, autor, config):
    """Un producto con su variante BASE, que es la que tiene stock."""
    categoria = servicio_categorias.crear_categoria(db, autor, nombre="Calzado")
    proveedor = servicio_proveedores.crear_proveedor(
        db, autor, nombre="Distribuidora Norte", dolar_actual=Decimal("1000")
    )
    producto = servicio_productos.crear_producto(
        db, autor,
        categoria_id=categoria.id,
        proveedor_id=proveedor.id,
        precio_usd=Decimal("10"),
        descripcion="Zapatilla running",
    )
    db.flush()
    return producto.variantes[0]


@pytest.fixture
def con_stock(db, autor, variante, cd):
    """100 unidades en el CD, ingresadas como corresponde: con un movimiento."""
    servicio.aplicar_movimiento(
        db, autor,
        tipo=TipoMovimiento.INGRESO_PROVEEDOR,
        variante_id=variante.id,
        cantidad=100,
        punto_venta_destino_id=cd.id,
    )
    db.flush()
    return variante


# ============================================================================
# LA REGLA FUNDAMENTAL: EL STOCK NO CAMBIA SIN MOVIMIENTO
# ============================================================================


def test_el_ingreso_crea_la_fila_de_stock_y_su_movimiento(db, autor, variante, cd):
    """
    Las dos cosas en la misma transacción. Un stock sin movimiento no se
    puede explicar, y un movimiento sin stock no pasó.
    """
    movimiento = servicio.aplicar_movimiento(
        db, autor,
        tipo=TipoMovimiento.INGRESO_PROVEEDOR,
        variante_id=variante.id,
        cantidad=40,
        punto_venta_destino_id=cd.id,
    )

    assert servicio.cantidad_en(db, variante.id, cd.id) == 40
    assert movimiento.tipo == TipoMovimiento.INGRESO_PROVEEDOR
    assert movimiento.cantidad == 40


def test_la_fila_de_stock_se_crea_recien_con_el_primer_movimiento(db, variante, cd):
    """
    5.000 variantes por 6 ubicaciones serían 30.000 filas en cero que no
    dicen nada. "Sin fila" y "cantidad 0" significan lo mismo.
    """
    assert servicio.cantidad_en(db, variante.id, cd.id) == 0
    assert db.query(Stock).count() == 0


def test_no_se_puede_sacar_mas_de_lo_que_hay(db, autor, con_stock, cd, local):
    with pytest.raises(ReglaDeNegocio, match="No hay stock suficiente"):
        servicio.aplicar_movimiento(
            db, autor,
            tipo=TipoMovimiento.ENVIO_CD_LOCAL,
            variante_id=con_stock.id,
            cantidad=101,
            punto_venta_origen_id=cd.id,
            punto_venta_destino_id=local.id,
        )


def test_si_el_movimiento_falla_el_stock_no_cambia(db, autor, con_stock, cd, local):
    """
    Atomicidad: es el criterio de aceptación del módulo. Se valida ANTES de
    tocar el stock, así que un rechazo no deja nada a medias.
    """
    antes = servicio.cantidad_en(db, con_stock.id, cd.id)
    movimientos_antes = db.query(MovimientoStock).count()

    with pytest.raises(ReglaDeNegocio):
        servicio.aplicar_movimiento(
            db, autor,
            tipo=TipoMovimiento.ENVIO_CD_LOCAL,
            variante_id=con_stock.id,
            cantidad=999,
            punto_venta_origen_id=cd.id,
            punto_venta_destino_id=local.id,
        )

    assert servicio.cantidad_en(db, con_stock.id, cd.id) == antes
    assert db.query(MovimientoStock).count() == movimientos_antes


def test_una_transferencia_con_origen_igual_al_destino_no_se_permite(
    db, autor, con_stock, cd
):
    with pytest.raises(ReglaDeNegocio, match="no mueve nada"):
        servicio.aplicar_movimiento(
            db, autor,
            tipo=TipoMovimiento.ENVIO_CD_LOCAL,
            variante_id=con_stock.id,
            cantidad=1,
            punto_venta_origen_id=cd.id,
            punto_venta_destino_id=cd.id,
        )


def test_el_stock_infinito_no_lleva_la_cuenta(db, autor, variante, cd, local):
    """
    Servicios y productos a pedido: descontarles unidades sería inventar un
    inventario que no existe. El movimiento igual queda registrado.
    """
    variante.producto.stock_infinito = True
    db.flush()

    servicio.aplicar_movimiento(
        db, autor,
        tipo=TipoMovimiento.ENVIO_CD_LOCAL,
        variante_id=variante.id,
        cantidad=5,
        punto_venta_origen_id=cd.id,
        punto_venta_destino_id=local.id,
    )

    # Ni se fue de un lado ni llegó al otro, y no hizo falta stock previo.
    assert servicio.cantidad_en(db, variante.id, cd.id) == 0
    assert servicio.cantidad_en(db, variante.id, local.id) == 0
    assert db.query(MovimientoStock).count() == 1


# ============================================================================
# MÍNIMOS Y ALERTAS
# ============================================================================


def test_el_minimo_que_aplica_depende_del_tipo_de_ubicacion(db, autor, variante, cd, local):
    """
    El CD abastece a todos los locales: su colchón es de otro orden que el de
    una góndola. Cuál aplica lo decide el tipo, no quien carga el dato.
    """
    en_cd = servicio.definir_minimos(
        db, autor, variante.id, cd.id, stock_minimo_cd=20, stock_minimo_local=3
    )
    en_local = servicio.definir_minimos(
        db, autor, variante.id, local.id, stock_minimo_cd=20, stock_minimo_local=3
    )

    assert en_cd.stock_minimo == 20
    assert en_local.stock_minimo == 3


def test_las_alertas_traen_lo_que_esta_en_el_minimo_o_por_debajo(
    db, autor, variante, cd
):
    """Con `<=`: estar justo en el mínimo ya es la señal de reponer."""
    servicio.aplicar_movimiento(
        db, autor,
        tipo=TipoMovimiento.INGRESO_PROVEEDOR,
        variante_id=variante.id,
        cantidad=5,
        punto_venta_destino_id=cd.id,
    )
    servicio.definir_minimos(db, autor, variante.id, cd.id, stock_minimo_cd=5)
    db.flush()

    assert len(servicio.alertas(db, LIBRE)) == 1


def test_las_alertas_ignoran_las_filas_sin_minimo_configurado(db, autor, variante, cd):
    """
    Si entraran, todo artículo sin stock aparecería como alerta y la lista
    dejaría de servir para decidir qué pedir.
    """
    servicio.fila_de_stock(db, variante.id, cd.id)
    db.flush()

    assert servicio.alertas(db, LIBRE) == []


def test_los_minimos_no_pueden_ser_negativos(db, autor, variante, cd):
    with pytest.raises(ReglaDeNegocio, match="no puede ser negativo"):
        servicio.definir_minimos(db, autor, variante.id, cd.id, stock_minimo_cd=-1)


# ============================================================================
# REMITOS
# ============================================================================


def test_el_envio_descuenta_del_origen_al_crearse(db, autor, con_stock, cd, local):
    """
    Criterio de aceptación: el stock del CD se descuenta al crear el envío, no
    al confirmar la recepción. La mercadería se bajó de la estantería ahora.
    """
    servicio_remitos.crear_remito(
        db, autor, LIBRE,
        punto_venta_origen_id=cd.id,
        punto_venta_destino_id=local.id,
        items=[{"variante_id": con_stock.id, "cantidad": 30}],
    )
    db.flush()

    assert servicio.cantidad_en(db, con_stock.id, cd.id) == 70
    # Y NO llegó al local todavía: está en el camión.
    assert servicio.cantidad_en(db, con_stock.id, local.id) == 0


def test_la_recepcion_suma_al_destino(db, autor, con_stock, cd, local):
    remito = servicio_remitos.crear_remito(
        db, autor, LIBRE,
        punto_venta_origen_id=cd.id,
        punto_venta_destino_id=local.id,
        items=[{"variante_id": con_stock.id, "cantidad": 30}],
    )
    servicio_remitos.confirmar_recepcion(
        db, autor, LIBRE, remito.id, numero_confirmacion=remito.numero, recibidos={}
    )
    db.flush()

    assert servicio.cantidad_en(db, con_stock.id, local.id) == 30
    assert remito.estado == EstadoRemito.CONFIRMADO
    # Las dos puntas quedaron registradas: la salida y la entrada.
    assert db.query(MovimientoStock).filter_by(remito_id=remito.id).count() == 2


def test_un_numero_de_confirmacion_incorrecto_no_recibe_nada(
    db, autor, con_stock, cd, local
):
    """
    Criterio de aceptación: un código de confirmación incorrecto devuelve 403.
    El número del remito es el que está impreso en el papel que viaja con la
    carga: tenerlo es la prueba de que la mercadería llegó.
    """
    remito = servicio_remitos.crear_remito(
        db, autor, LIBRE,
        punto_venta_origen_id=cd.id,
        punto_venta_destino_id=local.id,
        items=[{"variante_id": con_stock.id, "cantidad": 10}],
    )

    with pytest.raises(servicio_remitos.CodigoIncorrecto):
        servicio_remitos.confirmar_recepcion(
            db, autor, LIBRE, remito.id,
            numero_confirmacion="R-999999",
            recibidos={},
        )

    assert servicio.cantidad_en(db, con_stock.id, local.id) == 0


def test_recibir_menos_deja_el_remito_con_diferencia(db, autor, con_stock, cd, local):
    """
    Entra lo que llegó, no lo que se envió. Lo que falta NO vuelve al origen:
    ya salió de ahí, y darlo por presente en los dos lados sería inventar
    mercadería.
    """
    remito = servicio_remitos.crear_remito(
        db, autor, LIBRE,
        punto_venta_origen_id=cd.id,
        punto_venta_destino_id=local.id,
        items=[{"variante_id": con_stock.id, "cantidad": 30}],
    )
    servicio_remitos.confirmar_recepcion(
        db, autor, LIBRE, remito.id,
        numero_confirmacion=remito.numero,
        recibidos={con_stock.id: 28},
    )
    db.flush()

    assert remito.estado == EstadoRemito.CON_DIFERENCIA
    assert servicio.cantidad_en(db, con_stock.id, local.id) == 28
    assert servicio.cantidad_en(db, con_stock.id, cd.id) == 70
    assert remito.items[0].diferencia == -2


def test_no_se_puede_recibir_mas_de_lo_enviado(db, autor, con_stock, cd, local):
    remito = servicio_remitos.crear_remito(
        db, autor, LIBRE,
        punto_venta_origen_id=cd.id,
        punto_venta_destino_id=local.id,
        items=[{"variante_id": con_stock.id, "cantidad": 10}],
    )

    with pytest.raises(ReglaDeNegocio, match="no puede recibirse más"):
        servicio_remitos.confirmar_recepcion(
            db, autor, LIBRE, remito.id,
            numero_confirmacion=remito.numero,
            recibidos={con_stock.id: 11},
        )


def test_un_remito_confirmado_no_se_confirma_dos_veces(db, autor, con_stock, cd, local):
    """Sin esto, cada confirmación volvería a sumar el stock al destino."""
    remito = servicio_remitos.crear_remito(
        db, autor, LIBRE,
        punto_venta_origen_id=cd.id,
        punto_venta_destino_id=local.id,
        items=[{"variante_id": con_stock.id, "cantidad": 10}],
    )
    servicio_remitos.confirmar_recepcion(
        db, autor, LIBRE, remito.id, numero_confirmacion=remito.numero, recibidos={}
    )

    with pytest.raises(ReglaDeNegocio, match="no se puede volver a confirmar"):
        servicio_remitos.confirmar_recepcion(
            db, autor, LIBRE, remito.id, numero_confirmacion=remito.numero, recibidos={}
        )

    assert servicio.cantidad_en(db, con_stock.id, local.id) == 10


def test_los_numeros_de_remito_son_correlativos_y_no_se_repiten(
    db, autor, con_stock, cd, local
):
    numeros = {
        servicio_remitos.crear_remito(
            db, autor, LIBRE,
            punto_venta_origen_id=cd.id,
            punto_venta_destino_id=local.id,
            items=[{"variante_id": con_stock.id, "cantidad": 1}],
        ).numero
        for _ in range(5)
    }

    assert len(numeros) == 5
    assert all(n.startswith("R-") and len(n) == 8 for n in numeros)


def test_un_remito_sin_items_no_se_crea(db, autor, cd, local):
    with pytest.raises(ReglaDeNegocio, match="no mueve nada"):
        servicio_remitos.crear_remito(
            db, autor, LIBRE,
            punto_venta_origen_id=cd.id,
            punto_venta_destino_id=local.id,
            items=[],
        )


def test_no_se_manda_mercaderia_a_una_ubicacion_inactiva(
    db, autor, con_stock, cd, local
):
    local.activo = False
    db.flush()

    with pytest.raises(ReglaDeNegocio, match="inactivo"):
        servicio_remitos.crear_remito(
            db, autor, LIBRE,
            punto_venta_origen_id=cd.id,
            punto_venta_destino_id=local.id,
            items=[{"variante_id": con_stock.id, "cantidad": 1}],
        )


def test_despachar_genera_el_pdf_y_no_mueve_stock(db, autor, con_stock, cd, local):
    """
    Criterio de aceptación: el PDF se genera automáticamente al despachar.
    El stock ya se descontó al armar el envío.
    """
    remito = servicio_remitos.crear_remito(
        db, autor, LIBRE,
        punto_venta_origen_id=cd.id,
        punto_venta_destino_id=local.id,
        items=[{"variante_id": con_stock.id, "cantidad": 30}],
    )
    en_cd = servicio.cantidad_en(db, con_stock.id, cd.id)

    servicio_remitos.despachar(db, autor, LIBRE, remito.id)
    db.flush()

    assert remito.estado == EstadoRemito.EN_CAMINO
    assert remito.pdf_url and remito.pdf_url.endswith(f"{remito.numero}.pdf")
    assert servicio.cantidad_en(db, con_stock.id, cd.id) == en_cd


# ============================================================================
# BAJAS
# ============================================================================


def test_la_baja_descuenta_y_queda_con_su_motivo(db, autor, con_stock, cd):
    motivo = servicio_bajas.crear_motivo(db, autor, "Rotura en depósito")

    movimiento = servicio_bajas.registrar_baja(
        db, autor, LIBRE,
        variante_id=con_stock.id,
        punto_de_venta_id=cd.id,
        cantidad=3,
        motivo_baja_id=motivo.id,
    )
    db.flush()

    assert servicio.cantidad_en(db, con_stock.id, cd.id) == 97
    assert movimiento.tipo == TipoMovimiento.BAJA
    assert movimiento.motivo_baja_id == motivo.id


def test_no_se_da_de_baja_con_un_motivo_inactivo(db, autor, con_stock, cd):
    """
    Un motivo inactivo sigue explicando las bajas viejas, pero no se ofrece
    para nuevas.
    """
    motivo = servicio_bajas.crear_motivo(db, autor, "Motivo viejo")
    servicio_bajas.editar_motivo(db, autor, motivo.id, activo=False)

    with pytest.raises(ReglaDeNegocio, match="inactivo"):
        servicio_bajas.registrar_baja(
            db, autor, LIBRE,
            variante_id=con_stock.id,
            punto_de_venta_id=cd.id,
            cantidad=1,
            motivo_baja_id=motivo.id,
        )


def test_no_hay_dos_motivos_de_baja_con_el_mismo_nombre(db, autor):
    """Los reportes por motivo quedarían partidos en dos."""
    servicio_bajas.crear_motivo(db, autor, "Robo en local")

    with pytest.raises(ReglaDeNegocio, match="Ya existe un motivo"):
        servicio_bajas.crear_motivo(db, autor, "robo en local")


# ============================================================================
# AUDITORÍA DE INVENTARIO
# ============================================================================


def test_la_diferencia_la_calcula_el_motor(db, autor, con_stock, cd):
    """
    Criterio de aceptación: `diferencia` es GENERATED ALWAYS AS. El código no
    la escribe — se pide la fila y ya viene calculada.
    """
    auditoria = servicio_auditoria.iniciar(db, autor, LIBRE, punto_de_venta_id=cd.id)
    servicio_auditoria.registrar_items(
        db, autor, LIBRE, auditoria.id,
        [{"variante_id": con_stock.id, "cantidad_contada": 95}],
    )
    db.flush()
    db.expire_all()

    item = servicio_auditoria.obtener(db, auditoria.id).items[0]
    assert item.cantidad_sistema == 100
    assert item.cantidad_contada == 95
    assert item.diferencia == -5


def test_aprobar_ajusta_el_stock_a_lo_contado(db, autor, con_stock, cd):
    """
    Criterio de aceptación: cada variante con diferencia distinta de cero
    genera un movimiento `ajuste_auditoria` y el stock se actualiza.
    """
    auditoria = servicio_auditoria.iniciar(db, autor, LIBRE, punto_de_venta_id=cd.id)
    servicio_auditoria.registrar_items(
        db, autor, LIBRE, auditoria.id,
        [{"variante_id": con_stock.id, "cantidad_contada": 95}],
    )
    servicio_auditoria.finalizar(db, autor, LIBRE, auditoria.id)
    servicio_auditoria.aprobar(db, autor, auditoria.id)
    db.flush()

    assert servicio.cantidad_en(db, con_stock.id, cd.id) == 95
    ajustes = db.query(MovimientoStock).filter_by(
        tipo=TipoMovimiento.AJUSTE_AUDITORIA
    ).all()
    assert len(ajustes) == 1
    assert ajustes[0].cantidad == 5
    # Se contó MENOS que lo que decía el sistema: la mercadería sale.
    assert ajustes[0].punto_venta_origen_id == cd.id
    assert ajustes[0].punto_venta_destino_id is None


def test_contar_de_mas_suma_al_stock(db, autor, con_stock, cd):
    auditoria = servicio_auditoria.iniciar(db, autor, LIBRE, punto_de_venta_id=cd.id)
    servicio_auditoria.registrar_items(
        db, autor, LIBRE, auditoria.id,
        [{"variante_id": con_stock.id, "cantidad_contada": 104}],
    )
    servicio_auditoria.finalizar(db, autor, LIBRE, auditoria.id)
    servicio_auditoria.aprobar(db, autor, auditoria.id)
    db.flush()

    assert servicio.cantidad_en(db, con_stock.id, cd.id) == 104


def test_rechazar_no_cambia_el_stock(db, autor, con_stock, cd):
    """Criterio de aceptación: al rechazar, el stock no cambia."""
    auditoria = servicio_auditoria.iniciar(db, autor, LIBRE, punto_de_venta_id=cd.id)
    servicio_auditoria.registrar_items(
        db, autor, LIBRE, auditoria.id,
        [{"variante_id": con_stock.id, "cantidad_contada": 40}],
    )
    servicio_auditoria.finalizar(db, autor, LIBRE, auditoria.id)
    servicio_auditoria.rechazar(db, autor, auditoria.id, notas="Se contó mal el estante")
    db.flush()

    assert servicio.cantidad_en(db, con_stock.id, cd.id) == 100
    assert db.query(MovimientoStock).filter_by(
        tipo=TipoMovimiento.AJUSTE_AUDITORIA
    ).count() == 0
    # El conteo NO se borra: queda con su diferencia y el motivo del rechazo.
    auditoria = servicio_auditoria.obtener(db, auditoria.id)
    assert auditoria.items[0].diferencia == -60
    assert "Se contó mal" in auditoria.notas


def test_un_conteo_que_coincide_no_genera_ningun_ajuste(db, autor, con_stock, cd):
    """Una fila por cada código contado llenaría el historial de ruido."""
    auditoria = servicio_auditoria.iniciar(db, autor, LIBRE, punto_de_venta_id=cd.id)
    servicio_auditoria.registrar_items(
        db, autor, LIBRE, auditoria.id,
        [{"variante_id": con_stock.id, "cantidad_contada": 100}],
    )
    servicio_auditoria.finalizar(db, autor, LIBRE, auditoria.id)
    servicio_auditoria.aprobar(db, autor, auditoria.id)

    assert db.query(MovimientoStock).filter_by(
        tipo=TipoMovimiento.AJUSTE_AUDITORIA
    ).count() == 0


def test_el_sistema_se_congela_al_contar_cada_item(db, autor, con_stock, cd, local):
    """
    `cantidad_sistema` se captura al registrar el ítem, no al abrir la
    auditoría. Si se congelara al inicio, una venta hecha entre la apertura y
    el conteo de ese estante aparecería como un faltante que nadie podría
    explicar.
    """
    auditoria = servicio_auditoria.iniciar(db, autor, LIBRE, punto_de_venta_id=cd.id)

    # Entre la apertura y el conteo, salen 10 unidades.
    servicio.aplicar_movimiento(
        db, autor,
        tipo=TipoMovimiento.ENVIO_CD_LOCAL,
        variante_id=con_stock.id,
        cantidad=10,
        punto_venta_origen_id=cd.id,
        punto_venta_destino_id=local.id,
        puntas=("origen",),
    )
    servicio_auditoria.registrar_items(
        db, autor, LIBRE, auditoria.id,
        [{"variante_id": con_stock.id, "cantidad_contada": 90}],
    )
    db.flush()
    db.expire_all()

    item = servicio_auditoria.obtener(db, auditoria.id).items[0]
    assert item.cantidad_sistema == 90
    assert item.diferencia == 0, "el envío no puede aparecer como faltante"


def test_no_hay_dos_auditorias_abiertas_en_la_misma_ubicacion(db, autor, cd):
    """La segunda tomaría como "sistema" un número que la primera va a corregir."""
    servicio_auditoria.iniciar(db, autor, LIBRE, punto_de_venta_id=cd.id)

    with pytest.raises(ReglaDeNegocio, match="sin cerrar"):
        servicio_auditoria.iniciar(db, autor, LIBRE, punto_de_venta_id=cd.id)


def test_una_auditoria_vacia_no_se_puede_cerrar(db, autor, cd):
    auditoria = servicio_auditoria.iniciar(db, autor, LIBRE, punto_de_venta_id=cd.id)

    with pytest.raises(ReglaDeNegocio, match="vacía"):
        servicio_auditoria.finalizar(db, autor, LIBRE, auditoria.id)


def test_recontar_un_codigo_sobreescribe(db, autor, con_stock, cd):
    """Contar dos veces un estante es normal: vale el último conteo."""
    auditoria = servicio_auditoria.iniciar(db, autor, LIBRE, punto_de_venta_id=cd.id)
    for contada in (80, 97):
        servicio_auditoria.registrar_items(
            db, autor, LIBRE, auditoria.id,
            [{"variante_id": con_stock.id, "cantidad_contada": contada}],
        )
    db.flush()

    auditoria = servicio_auditoria.obtener(db, auditoria.id)
    assert len(auditoria.items) == 1
    assert auditoria.items[0].cantidad_contada == 97


def test_no_se_aprueba_una_auditoria_que_no_esta_cerrada(db, autor, con_stock, cd):
    auditoria = servicio_auditoria.iniciar(db, autor, LIBRE, punto_de_venta_id=cd.id)
    servicio_auditoria.registrar_items(
        db, autor, LIBRE, auditoria.id,
        [{"variante_id": con_stock.id, "cantidad_contada": 1}],
    )

    with pytest.raises(ReglaDeNegocio, match="solo se aprueba"):
        servicio_auditoria.aprobar(db, autor, auditoria.id)


# ============================================================================
# AISLAMIENTO POR DISPOSITIVO
# ============================================================================


def _dispositivo(db, activo=True, punto_de_venta_id=None):
    from app.models.dispositivo import Dispositivo

    d = Dispositivo(descripcion="Equipo de prueba", activo=activo,
                    punto_de_venta_id=punto_de_venta_id)
    db.add(d)
    db.flush()
    return d


def test_un_vendedor_queda_limitado_al_local_de_su_dispositivo(
    db, crear_usuario, local
):
    vendedor = crear_usuario("vende", ROL_VENDEDOR)
    scope = get_punto_de_venta_scope(vendedor, _dispositivo(db, True, local.id))

    assert scope.restringido is True
    assert scope.punto_de_venta_id == local.id
    assert scope.sin_asignacion is False


@pytest.mark.parametrize(
    "rol", [ROL_CUENTA_MAESTRA, ROL_DUENO, ROL_DISTRIBUCION, ROL_AUDITOR]
)
def test_los_demas_roles_no_estan_limitados(db, crear_usuario, local, rol):
    """
    Un supervisor que solo pudiera ver el local donde está parado no podría
    supervisar nada.
    """
    usuario = crear_usuario(f"u_{rol}", rol)
    scope = get_punto_de_venta_scope(usuario, _dispositivo(db, True, local.id))

    assert scope.restringido is False
    assert scope.permite(local.id) and scope.permite(999)


@pytest.mark.parametrize(
    "activo,con_local", [(True, False), (False, True), (False, False)]
)
def test_un_vendedor_sin_asignacion_no_ve_nada(
    db, crear_usuario, local, activo, con_local
):
    """
    Un equipo sin registrar, desactivado o sin local son el mismo caso: no hay
    ubicación de la que hablar. Mostrarle el stock de todos los locales sería
    peor que no mostrarle ninguno.
    """
    vendedor = crear_usuario("vende", ROL_VENDEDOR)
    dispositivo = _dispositivo(db, activo, local.id if con_local else None)
    scope = get_punto_de_venta_scope(vendedor, dispositivo)

    assert scope.sin_asignacion is True
    assert not scope.permite(local.id)


def test_un_vendedor_sin_dispositivo_registrado_tampoco_ve_nada(db, crear_usuario):
    vendedor = crear_usuario("vende", ROL_VENDEDOR)
    assert get_punto_de_venta_scope(vendedor, None).sin_asignacion is True


def test_el_listado_de_stock_se_filtra_al_local_del_vendedor(
    db, autor, variante, cd, local, otro_local
):
    """El filtro lo aplica el service, no el endpoint: es una sola puerta."""
    for punto in (cd, local, otro_local):
        servicio.aplicar_movimiento(
            db, autor,
            tipo=TipoMovimiento.INGRESO_PROVEEDOR,
            variante_id=variante.id,
            cantidad=10,
            punto_venta_destino_id=punto.id,
        )
    db.flush()

    _, total_libre = servicio.listar_stock(db, LIBRE)
    filas, total = servicio.listar_stock(
        db, DeviceScope(restringido=True, punto_de_venta_id=local.id)
    )

    assert total_libre == 3
    assert total == 1
    assert filas[0].punto_de_venta_id == local.id


def test_el_listado_de_stock_de_un_vendedor_sin_asignacion_viene_vacio(
    db, autor, con_stock
):
    filas, total = servicio.listar_stock(
        db, DeviceScope(restringido=True, sin_asignacion=True)
    )

    assert (filas, total) == ([], 0)


def test_un_vendedor_no_puede_dar_de_baja_en_otro_local(
    db, autor, con_stock, cd, local
):
    """
    Criterio de aceptación: cualquier intento de acceder a otro local devuelve
    403. Se corta en el service, que es la última barrera antes del stock.
    """
    from fastapi import HTTPException

    motivo = servicio_bajas.crear_motivo(db, autor, "Rotura")
    scope = DeviceScope(restringido=True, punto_de_venta_id=local.id)

    with pytest.raises(HTTPException) as error:
        servicio_bajas.registrar_baja(
            db, autor, scope,
            variante_id=con_stock.id,
            punto_de_venta_id=cd.id,
            cantidad=1,
            motivo_baja_id=motivo.id,
        )

    assert error.value.status_code == 403
    assert servicio.cantidad_en(db, con_stock.id, cd.id) == 100


def test_el_mensaje_del_dispositivo_sin_asignar_es_uno_solo(db):
    """
    El texto lo muestran las tres pantallas y lo devuelve la API en el 403:
    vive en un solo lugar para que digan exactamente lo mismo (Principio 2).
    """
    from fastapi import HTTPException

    from app.core.device_scope import MENSAJE_SIN_ASIGNACION

    scope = DeviceScope(restringido=True, sin_asignacion=True)
    with pytest.raises(HTTPException) as error:
        scope.exigir(1)

    assert error.value.detail == MENSAJE_SIN_ASIGNACION
    assert "no tiene un local asignado" in MENSAJE_SIN_ASIGNACION


def test_un_vendedor_solo_confirma_los_remitos_de_su_local(
    db, autor, con_stock, cd, local, otro_local
):
    from fastapi import HTTPException

    remito = servicio_remitos.crear_remito(
        db, autor, LIBRE,
        punto_venta_origen_id=cd.id,
        punto_venta_destino_id=local.id,
        items=[{"variante_id": con_stock.id, "cantidad": 5}],
    )
    ajeno = DeviceScope(restringido=True, punto_de_venta_id=otro_local.id)

    with pytest.raises(HTTPException) as error:
        servicio_remitos.confirmar_recepcion(
            db, autor, ajeno, remito.id,
            numero_confirmacion=remito.numero,
            recibidos={},
        )

    assert error.value.status_code == 403
    assert servicio.cantidad_en(db, con_stock.id, local.id) == 0


# ============================================================================
# EL TOTAL QUE VE EL LISTADO DE PRODUCTOS
# ============================================================================


def test_el_stock_total_de_la_variante_suma_las_ubicaciones(
    db, autor, variante, cd, local
):
    """
    El listado de productos muestra el total. Es un dato DERIVADO: la verdad
    son las filas de `stock` y el total se calcula, no se guarda.
    """
    for punto, cantidad in ((cd, 80), (local, 12)):
        servicio.aplicar_movimiento(
            db, autor,
            tipo=TipoMovimiento.INGRESO_PROVEEDOR,
            variante_id=variante.id,
            cantidad=cantidad,
            punto_venta_destino_id=punto.id,
        )
    db.flush()
    db.expire_all()

    filas, _ = servicio_productos.listar_variantes(db)
    assert filas[0].stock_total == 92


def test_bajo_minimo_se_enciende_si_alguna_ubicacion_esta_en_su_minimo(
    db, autor, variante, cd, local
):
    """
    La pregunta que responde la columna Stock en rojo: "¿hay algún lugar donde
    esto esté por reponerse?".
    """
    servicio.aplicar_movimiento(
        db, autor,
        tipo=TipoMovimiento.INGRESO_PROVEEDOR,
        variante_id=variante.id,
        cantidad=50,
        punto_venta_destino_id=cd.id,
    )
    servicio.definir_minimos(db, autor, variante.id, cd.id, stock_minimo_cd=10)
    db.flush()
    db.expire_all()

    filas, _ = servicio_productos.listar_variantes(db)
    assert filas[0].bajo_minimo is False

    # El local recibe 2 unidades con un mínimo de 5: ahí sí hay que reponer.
    servicio.aplicar_movimiento(
        db, autor,
        tipo=TipoMovimiento.INGRESO_PROVEEDOR,
        variante_id=variante.id,
        cantidad=2,
        punto_venta_destino_id=local.id,
    )
    servicio.definir_minimos(db, autor, variante.id, local.id, stock_minimo_local=5)
    db.flush()
    db.expire_all()

    filas, _ = servicio_productos.listar_variantes(db)
    assert filas[0].bajo_minimo is True


def test_no_se_divide_en_variantes_un_producto_con_stock_en_algun_local(
    db, autor, variante, local
):
    """
    La guarda de `agregar_variante` mira la tabla `stock`: con que UNA
    ubicación tenga mercadería alcanza para frenar la división.
    """
    servicio.aplicar_movimiento(
        db, autor,
        tipo=TipoMovimiento.INGRESO_PROVEEDOR,
        variante_id=variante.id,
        cantidad=1,
        punto_venta_destino_id=local.id,
    )
    db.flush()

    with pytest.raises(ReglaDeNegocio, match="stock cargado"):
        servicio_productos.agregar_variante(
            db, autor, variante.producto_id, sufijo="R", descripcion_sufijo="Rojo"
        )


# ============================================================================
# MOVIMIENTOS Y VALORIZADO
# ============================================================================


def test_el_historial_trae_los_movimientos_del_mas_nuevo_al_mas_viejo(
    db, autor, con_stock, cd, local
):
    servicio_remitos.crear_remito(
        db, autor, LIBRE,
        punto_venta_origen_id=cd.id,
        punto_venta_destino_id=local.id,
        items=[{"variante_id": con_stock.id, "cantidad": 5}],
    )
    db.flush()

    filas, total = servicio.listar_movimientos(db, LIBRE)

    assert total == 2
    assert filas[0].timestamp >= filas[1].timestamp


def test_un_vendedor_ve_los_movimientos_que_tocan_su_local(
    db, autor, con_stock, cd, local, otro_local
):
    """Por las dos puntas: lo que le llegó y lo que salió de ahí."""
    servicio.aplicar_movimiento(
        db, autor,
        tipo=TipoMovimiento.INGRESO_PROVEEDOR,
        variante_id=con_stock.id,
        cantidad=5,
        punto_venta_destino_id=otro_local.id,
    )
    servicio_remitos.crear_remito(
        db, autor, LIBRE,
        punto_venta_origen_id=cd.id,
        punto_venta_destino_id=local.id,
        items=[{"variante_id": con_stock.id, "cantidad": 5}],
    )
    db.flush()

    _, total = servicio.listar_movimientos(
        db, DeviceScope(restringido=True, punto_de_venta_id=local.id)
    )

    assert total == 1


def test_el_valorizado_usa_el_precio_efectivo(db, autor, con_stock, cd):
    """
    100 unidades a 10 USD con el dólar en 1.000 y redondeo al millar:
    el precio de venta es 10.000 y el valorizado 1.000.000.
    """
    assert servicio.valorizado(db, LIBRE) == Decimal("1000000.00")


def test_una_variante_inexistente_no_mueve_stock(db, autor, cd):
    with pytest.raises(NoEncontrado):
        servicio.aplicar_movimiento(
            db, autor,
            tipo=TipoMovimiento.INGRESO_PROVEEDOR,
            variante_id=99999,
            cantidad=1,
            punto_venta_destino_id=cd.id,
        )
