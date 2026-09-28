"""
Tests de la primera pantalla del cambio en el celular: los productos del
ticket del código de cambio, para elegir ahí cuáles devuelve el cliente.
"""

from decimal import Decimal

import pytest

from app.models.cambio import TipoCambio
from app.services import cambios as servicio_cambios
from app.services import medios_pago as servicio_medios
from app.services import ventas as servicio_ventas
from app.services.roles import NoEncontrado, ReglaDeNegocio

# Los fixtures de venta de los tests de arqueo: local, dispositivo, catálogo
# con variantes y stock.
from tests.test_arqueo import (  # noqa: F401
    LIBRE,
    autor,
    catalogo,
    con_stock,
    config,
    crear_variante,
    dispositivo,
    local,
)


@pytest.fixture
def venta(db, autor, dispositivo, crear_variante, con_stock):
    """Venta confirmada de dos productos distintos, con su código de cambio."""
    anillo = crear_variante("Anillo", "1000")
    aro = crear_variante("Aro", "500")
    for v in (anillo, aro):
        con_stock(v, 5)

    venta = servicio_ventas.iniciar_venta(db, autor, dispositivo, LIBRE)
    for v in (anillo, aro):
        servicio_ventas.agregar_item(db, autor, venta, variante_id=v.id)
    efectivo = next(m for m in servicio_medios.listar_medios(db) if m.nombre == "Efectivo")
    servicio_ventas.registrar_pagos(
        db, autor, venta, [{"medio_de_pago_id": efectivo.id, "monto": venta.total}]
    )
    servicio_ventas.confirmar_venta(db, autor, venta, LIBRE)
    db.flush()
    return venta


def test_items_del_ticket_trae_cada_producto_de_la_venta(db, venta):
    ticket = servicio_cambios.items_del_ticket(db, venta.codigo_cambio.lower())

    assert ticket["origen"] == "venta"
    assert [i["descripcion"] for i in ticket["items"]] == ["Anillo", "Aro"]
    assert all(i["disponible"] for i in ticket["items"])
    primero = ticket["items"][0]
    item_venta = min(venta.items, key=lambda i: i.id)
    assert primero["venta_item_id"] == item_venta.id
    # El código como está en la etiqueta: con el dígito verificador.
    variante = item_venta.variante
    assert primero["codigo"] == variante.codigo_completo + variante.verificador
    assert primero["precio"] == item_venta.precio_unitario
    assert "foto_url" in primero


def test_items_del_ticket_valida_el_codigo(db, venta):
    with pytest.raises(NoEncontrado):
        servicio_cambios.items_del_ticket(db, "ZZZZ9999")

    venta.codigo_cambio_activo = False
    db.flush()
    with pytest.raises(ReglaDeNegocio, match="ya fue utilizado"):
        servicio_cambios.items_del_ticket(db, venta.codigo_cambio)


def test_api_ticket(client, db, venta):
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    resp = client.get("/api/v1/cambios/ticket", params={"codigo": venta.codigo_cambio})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 2
    assert client.get("/api/v1/cambios/ticket", params={"codigo": "ZZZZ9999"}).status_code == 404


def test_la_primera_pantalla_ofrece_elegir_del_ticket(client, db, autor, dispositivo):
    db.commit()
    client.cookies.set("device_uuid", str(dispositivo.uuid))
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    html = client.get("/cambios/nuevo").text
    assert "buscarTicket()" in html
    assert "¿Qué devuelve el cliente?" in html


# ── Solo el cambio confirmado se lleva los ítems ────────────────────────────


def _cambio_con(db, autor, local, venta, item):
    """Cambio común que devuelve `item` del ticket y se lleva lo mismo (diferencia 0)."""
    cambio, _ = servicio_cambios.iniciar_cambio(
        db, autor, tipo=TipoCambio.COMUN, punto_de_venta_id=local.id,
        codigo_cambio=venta.codigo_cambio,
    )
    servicio_cambios.agregar_item_devuelto(db, cambio, item["variante_id"], item["venta_item_id"])
    servicio_cambios.agregar_item_nuevo(db, cambio, item["variante_id"])
    db.flush()
    db.refresh(cambio)
    return cambio


def _disponibles(db, venta):
    return {
        i["descripcion"]: i["disponible"]
        for i in servicio_cambios.items_del_ticket(db, venta.codigo_cambio)["items"]
    }


def test_un_cambio_sin_confirmar_no_se_lleva_los_items(db, autor, local, venta):
    anillo = servicio_cambios.items_del_ticket(db, venta.codigo_cambio)["items"][0]
    _cambio_con(db, autor, local, venta, anillo)  # queda sin realizar

    # Sigue siendo de la venta original: se ofrece y otro cambio lo puede tomar.
    assert _disponibles(db, venta)["Anillo"] is True
    otro = _cambio_con(db, autor, local, venta, anillo)
    servicio_cambios.confirmar_cambio(db, autor, otro)
    db.flush()

    assert _disponibles(db, venta)["Anillo"] is False


def test_al_confirmar_se_controla_que_no_se_haya_devuelto_en_otro(db, autor, local, venta):
    anillo = servicio_cambios.items_del_ticket(db, venta.codigo_cambio)["items"][0]
    primero = _cambio_con(db, autor, local, venta, anillo)
    segundo = _cambio_con(db, autor, local, venta, anillo)

    servicio_cambios.confirmar_cambio(db, autor, primero)
    db.flush()
    with pytest.raises(ReglaDeNegocio, match="ya se devolvió en otro cambio confirmado"):
        servicio_cambios.confirmar_cambio(db, autor, segundo)


def test_no_se_devuelve_dos_veces_lo_mismo_en_un_cambio(db, autor, local, venta):
    anillo = servicio_cambios.items_del_ticket(db, venta.codigo_cambio)["items"][0]
    cambio, _ = servicio_cambios.iniciar_cambio(
        db, autor, tipo=TipoCambio.COMUN, punto_de_venta_id=local.id,
        codigo_cambio=venta.codigo_cambio,
    )
    servicio_cambios.agregar_item_devuelto(db, cambio, anillo["variante_id"], anillo["venta_item_id"])
    db.flush()
    db.refresh(cambio)
    with pytest.raises(ReglaDeNegocio, match="ya está entre los devueltos"):
        servicio_cambios.agregar_item_devuelto(
            db, cambio, anillo["variante_id"], anillo["venta_item_id"]
        )
