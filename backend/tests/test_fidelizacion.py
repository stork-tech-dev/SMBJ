"""
Tests de fidelización: categorías por puntos y descuento en el mes del
cumpleaños.

  1. La categoría sale de los puntos históricos: canjear no la baja.
  2. En el mes del cumpleaños, el % de la categoría se aplica solo a lo que no
     tiene promoción ni descuento manual, respetando el tope de la venta.
  3. La vendedora puede quitarlo en la venta; vuelve con otro cliente.
  4. Las categorías las edita solo la Cuenta Maestra, auditadas.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.permisos import ROL_DUENO
from app.core.utils import ahora_db
from app.models.auditoria import Auditoria
from app.models.cliente import TipoPunto
from app.services import clientes as servicio_clientes
from app.services import descuentos as servicio_descuentos
from app.services import fidelizacion as servicio
from app.services import ventas as servicio_ventas
from app.services.roles import ReglaDeNegocio

from tests.test_ventas import (  # noqa: F401
    autor,
    catalogo,
    cliente,
    config,
    crear_variante,
    dispositivo,
    local,
    venta,
)

CATEGORIAS = [
    {"nombre": "Plata", "puntos_desde": 10, "porcentaje_cumpleanos": Decimal("10")},
    {"nombre": "Oro", "puntos_desde": 100, "porcentaje_cumpleanos": Decimal("15")},
]


def _este_mes() -> date:
    hoy = ahora_db().date()
    return date(1990, hoy.month, 1)


def _otro_mes() -> date:
    hoy = ahora_db().date()
    return date(1990, hoy.month % 12 + 1, 1)


def _sumar_puntos(db, autor, cliente, cantidad):
    servicio_clientes.registrar_movimiento_puntos(
        db, autor, cliente_id=cliente.id, tipo=TipoPunto.ACUMULACION, cantidad=cantidad
    )


@pytest.fixture
def categorias(db, autor):
    return servicio.reemplazar_categorias(db, autor.id, CATEGORIAS)


@pytest.fixture
def cumpleanero(db, autor, cliente, categorias):
    """Cliente Oro que cumple años este mes."""
    cliente.fecha_nacimiento = _este_mes()
    _sumar_puntos(db, autor, cliente, 150)
    db.flush()
    return cliente


# ── Categoría ───────────────────────────────────────────────────────────────


def test_categoria_por_puntos_historicos_y_canjear_no_la_baja(db, autor, cliente, categorias):
    assert servicio.categoria_de(db, cliente.id) is None

    _sumar_puntos(db, autor, cliente, 120)
    assert servicio.categoria_de(db, cliente.id).nombre == "Oro"

    servicio_clientes.registrar_movimiento_puntos(
        db, autor, cliente_id=cliente.id, tipo=TipoPunto.CANJE, cantidad=100
    )
    assert servicio_clientes.saldo_puntos(db, cliente.id) == 20
    assert servicio.categoria_de(db, cliente.id).nombre == "Oro"


# ── Descuento de cumpleaños ─────────────────────────────────────────────────


def test_en_su_mes_se_aplica_solo_y_con_el_motivo_cumpleanos(
    db, autor, venta, crear_variante, cumpleanero
):
    variante = crear_variante("Anillo", "10000")
    item, _ = servicio_ventas.agregar_item(db, autor, venta, variante_id=variante.id)
    servicio_ventas.asociar_cliente(db, autor, venta, cumpleanero.id)

    assert item.descuento_item == Decimal("15")
    assert item.descuento_automatico is True
    assert item.motivo_descuento_id == servicio.motivo_cumpleanos(db).id
    assert Decimal(item.precio_final) == Decimal("8500")

    # Un producto que se agrega después también lo lleva.
    otra = crear_variante("Aros", "2000")
    segundo, _ = servicio_ventas.agregar_item(db, autor, venta, variante_id=otra.id)
    assert segundo.descuento_item == Decimal("15")


def test_respeta_el_tope_de_la_venta(db, autor, venta, crear_variante, cumpleanero):
    """Producto con 40% propio + 15% de cumpleaños, tope 50: queda en 10%."""
    variante = crear_variante("Anillo", "10000", descuento_producto="40")
    item, _ = servicio_ventas.agregar_item(db, autor, venta, variante_id=variante.id)
    servicio_ventas.asociar_cliente(db, autor, venta, cumpleanero.id)

    assert item.descuento_item == Decimal("10")


def test_un_descuento_manual_reemplaza_al_de_cumpleanos(
    db, autor, venta, crear_variante, cumpleanero
):
    motivo = servicio_descuentos.crear_motivo(db, autor, nombre="Liquidación")
    variante = crear_variante("Anillo", "10000")
    item, _ = servicio_ventas.agregar_item(db, autor, venta, variante_id=variante.id)
    servicio_ventas.asociar_cliente(db, autor, venta, cumpleanero.id)

    servicio_ventas.aplicar_descuento_item(
        db, autor, venta, item.id, motivo_id=motivo.id, porcentaje=Decimal("30")
    )
    assert (item.descuento_item, item.descuento_automatico) == (Decimal("30"), False)

    # Otro recálculo (agregar un producto) no lo pisa.
    servicio_ventas.agregar_item(db, autor, venta, variante_id=crear_variante("Aros", "2000").id)
    assert item.descuento_item == Decimal("30")


def test_otro_mes_o_sin_categoria_no_aplica(db, autor, venta, crear_variante, cumpleanero):
    cumpleanero.fecha_nacimiento = _otro_mes()
    db.flush()
    variante = crear_variante("Anillo", "10000")
    item, _ = servicio_ventas.agregar_item(db, autor, venta, variante_id=variante.id)
    servicio_ventas.asociar_cliente(db, autor, venta, cumpleanero.id)
    assert item.descuento_item == Decimal("0")

    # Su mes, pero sin categorías cargadas.
    cumpleanero.fecha_nacimiento = _este_mes()
    servicio.reemplazar_categorias(db, autor.id, [])
    servicio_ventas.asociar_cliente(db, autor, venta, cumpleanero.id)
    assert item.descuento_item == Decimal("0")


def test_la_vendedora_lo_quita_y_con_otro_cliente_vuelve(
    db, autor, venta, crear_variante, cumpleanero
):
    variante = crear_variante("Anillo", "10000")
    item, _ = servicio_ventas.agregar_item(db, autor, venta, variante_id=variante.id)
    servicio_ventas.asociar_cliente(db, autor, venta, cumpleanero.id)

    servicio_ventas.cambiar_descuento_cumpleanos(db, autor, venta, activo=False)
    assert item.descuento_item == Decimal("0")
    servicio_ventas.agregar_item(db, autor, venta, variante_id=crear_variante("Aros", "2000").id)
    assert item.descuento_item == Decimal("0")

    servicio_ventas.cambiar_descuento_cumpleanos(db, autor, venta, activo=True)
    assert item.descuento_item == Decimal("15")


def test_la_respuesta_de_la_venta_informa_el_beneficio(
    client, db, autor, venta, crear_variante, cumpleanero, dispositivo
):
    servicio_ventas.agregar_item(db, autor, venta, variante_id=crear_variante("Anillo", "10000").id)
    db.commit()
    client.cookies.set("device_uuid", str(dispositivo.uuid))
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    datos = client.post(f"/api/v1/ventas/{venta.id}/cliente",
                        json={"cliente_id": cumpleanero.id}).json()
    assert datos["categoria_cliente"] == "Oro"
    assert datos["beneficio_cumpleanos"]["activo"] is True
    assert Decimal(datos["beneficio_cumpleanos"]["porcentaje"]) == Decimal("15")

    datos = client.post(f"/api/v1/ventas/{venta.id}/descuento-cumpleanos",
                        json={"activo": False}).json()
    assert datos["beneficio_cumpleanos"]["activo"] is False
    assert Decimal(datos["a_cobrar"]) == Decimal("10000")


# ── Configuración ───────────────────────────────────────────────────────────


def test_categorias_solo_cuenta_maestra_y_auditadas(client, db, autor, crear_usuario):
    crear_usuario("dueno1", ROL_DUENO)
    db.commit()

    client.post("/api/v1/auth/login", json={"username": "dueno1", "password": "Test1234!"})
    assert client.get("/api/v1/ajustes/categorias").status_code == 403

    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})
    cuerpo = {"categorias": [
        {"nombre": "Oro", "puntos_desde": 100, "porcentaje_cumpleanos": "15"},
        {"nombre": "Plata", "puntos_desde": 10, "porcentaje_cumpleanos": "10"},
    ]}
    r = client.put("/api/v1/ajustes/categorias", json=cuerpo)
    assert r.status_code == 200, r.text
    assert [c["nombre"] for c in r.json()["categorias"]] == ["Plata", "Oro"]
    assert db.execute(
        select(Auditoria).where(Auditoria.accion == "fidelizacion.categorias")
    ).scalar_one_or_none() is not None

    duplicado = {"categorias": [
        {"nombre": "A", "puntos_desde": 10, "porcentaje_cumpleanos": "5"},
        {"nombre": "B", "puntos_desde": 10, "porcentaje_cumpleanos": "5"},
    ]}
    assert client.put("/api/v1/ajustes/categorias", json=duplicado).status_code == 409


def test_fecha_de_nacimiento_futura_se_rechaza(db, autor):
    with pytest.raises(ReglaDeNegocio, match="futura"):
        servicio_clientes.crear_cliente(
            db, autor, apellido="Prueba", nombre="X", email="x@prueba.com",
            fecha_nacimiento=date(2999, 1, 1),
        )
