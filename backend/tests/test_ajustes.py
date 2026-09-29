"""
Tests de "Ajustes": los parámetros globales que edita la Cuenta Maestra.

  1. Solo la Cuenta Maestra los ve y los edita (API, pantalla y sidebar).
  2. Cada guardado valida los valores combinados y deja una auditoría con
     el antes y el después de lo que cambió.
  3. Los valores se usan de verdad: lista y tope de descuentos, puntos y
     plazo de cambio salen de la configuración, no de constantes.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.permisos import ROL_DUENO
from app.models.auditoria import Auditoria
from app.services import clientes as servicio_clientes
from app.services import configuracion as servicio
from app.services import descuentos as servicio_descuentos
from app.services.roles import ReglaDeNegocio

from tests.test_ventas import autor, config  # noqa: F401


def _login(client, usuario):
    client.post("/api/v1/auth/login", json={"username": usuario, "password": "Test1234!"})


# ── Acceso ──────────────────────────────────────────────────────────────────


def test_solo_la_cuenta_maestra_lee_y_edita(client, db, autor, config, crear_usuario):
    crear_usuario("dueno1", ROL_DUENO)
    db.commit()

    _login(client, "dueno1")
    assert client.get("/api/v1/ajustes").status_code == 403
    assert client.patch("/api/v1/ajustes", json={"dias_plazo_cambio": 10}).status_code == 403
    assert client.get("/ajustes", follow_redirects=False).status_code == 303
    assert 'href="/ajustes"' not in client.get("/").text

    _login(client, "admin")
    datos = client.get("/api/v1/ajustes").json()
    assert datos["paso_descuento"] == 5
    assert datos["porcentajes_descuento"] == [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
    assert "letra_empresa" not in datos and "metodo_descuento" not in datos
    assert "ajustesSistema()" in client.get("/ajustes").text
    assert 'href="/ajustes"' in client.get("/").text


def test_patch_aplica_solo_lo_que_cambia_y_audita(client, db, autor, config):
    db.commit()
    _login(client, "admin")

    r = client.patch("/api/v1/ajustes", json={"dias_plazo_cambio": 15, "paso_descuento": 5})
    assert r.status_code == 200, r.text
    assert r.json()["dias_plazo_cambio"] == 15

    auditoria = db.execute(
        select(Auditoria).where(Auditoria.accion == "configuracion.ajustes")
    ).scalar_one()
    # El paso vino con el mismo valor: no figura como cambio.
    assert auditoria.estado_anterior == {"dias_plazo_cambio": 30}
    assert auditoria.estado_nuevo == {"dias_plazo_cambio": 15}


def test_el_paso_no_puede_superar_el_tope(client, db, autor, config):
    db.commit()
    _login(client, "admin")

    r = client.patch("/api/v1/ajustes", json={"tope_descuento_venta": 20, "paso_descuento": 25})
    assert r.status_code == 409
    assert "no puede superar" in r.json()["detail"]
    assert client.patch("/api/v1/ajustes", json={"pesos_por_punto": 0}).status_code == 422


# ── Los valores se usan ─────────────────────────────────────────────────────


def test_paso_y_tope_cambian_la_lista_y_el_control_de_descuentos(db, autor, config):
    servicio.actualizar_ajustes(db, autor.id, {"paso_descuento": 10, "tope_descuento_venta": 40})

    assert servicio.porcentajes_descuento(db) == [10, 20, 30, 40]
    assert servicio_descuentos.validar_porcentaje(db, 20) == Decimal("20")
    with pytest.raises(ReglaDeNegocio):
        servicio_descuentos.validar_porcentaje(db, 15)
    with pytest.raises(ReglaDeNegocio, match="40%"):
        servicio_descuentos.validar_tope(db, Decimal("30"), Decimal("20"))


def test_pesos_por_punto_y_plazo_de_cambio_salen_de_la_configuracion(db, autor, config):
    assert servicio_clientes.puntos_por_venta(db, Decimal("10000")) == 10

    servicio.actualizar_ajustes(db, autor.id, {"pesos_por_punto": Decimal("500"),
                                               "dias_plazo_cambio": 10})

    assert servicio_clientes.puntos_por_venta(db, Decimal("10000")) == 20
    assert servicio.dias_plazo_cambio(db) == 10
