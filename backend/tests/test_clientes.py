"""
Tests del alta de clientes: apellido, nombre y email obligatorios en el alta
(no al editar), fecha de nacimiento, "Apellido, Nombre" y el alta rápida al
cobrar una venta.
"""

from datetime import date

import pytest
from sqlalchemy import select

from app.models.auditoria import Auditoria
from app.models.cliente import Cliente
from app.services import clientes as servicio_clientes
from app.services import ventas as servicio_ventas
from app.services.roles import ReglaDeNegocio

# Fixtures de ventas: autor (Cuenta Maestra), local, dispositivo y una venta
# en curso con turno abierto.
from tests.test_ventas import (  # noqa: F401
    LIBRE,
    autor,
    config,
    dispositivo,
    local,
    venta,
)

DATOS = {"apellido": "Gómez", "nombre": "Ana", "email": "ana@prueba.com"}


@pytest.mark.parametrize("falta", ["apellido", "nombre", "email"])
def test_el_alta_exige_apellido_nombre_y_email(db, autor, falta):
    datos = {**DATOS, falta: "  "}
    with pytest.raises(ReglaDeNegocio, match=falta):
        servicio_clientes.crear_cliente(db, autor, **datos)


def test_el_alta_guarda_la_fecha_de_nacimiento_y_arma_el_nombre(db, autor):
    cliente = servicio_clientes.crear_cliente(
        db, autor, **DATOS, fecha_nacimiento=date(1990, 5, 17)
    )

    assert cliente.fecha_nacimiento == date(1990, 5, 17)
    assert cliente.nombre_completo == "Gómez, Ana"


def test_un_cliente_viejo_sin_apellido_se_nombra_por_su_nombre(db):
    viejo = Cliente(nombre="Ana")
    assert viejo.nombre_completo == "Ana"


def test_editar_un_cliente_viejo_no_exige_apellido_ni_email(db, autor):
    viejo = Cliente(nombre="Ana")
    db.add(viejo)
    db.flush()

    editado = servicio_clientes.editar_cliente(db, autor, viejo.id, telefono="351555")

    assert editado.telefono == "351555"
    assert editado.apellido is None and editado.email is None


@pytest.mark.parametrize("texto", ["gomez ana", "ana gómez", "GOM"])
def test_la_busqueda_encuentra_por_apellido_y_nombre_en_cualquier_orden(db, autor, texto):
    cliente = servicio_clientes.crear_cliente(db, autor, **DATOS)

    assert cliente in servicio_clientes.buscar(db, texto)


def test_api_alta_sin_email_o_con_email_invalido_da_422(client, autor):
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    sin_email = {k: v for k, v in DATOS.items() if k != "email"}
    assert client.post("/api/v1/clientes", json=sin_email).status_code == 422
    assert client.post("/api/v1/clientes", json={**DATOS, "email": "no-es-mail"}).status_code == 422

    r = client.post("/api/v1/clientes", json=DATOS)
    assert r.status_code == 201, r.text
    assert r.json()["nombre_completo"] == "Gómez, Ana"


def test_al_cobrar_se_da_de_alta_el_cliente_y_queda_asociado(db, autor, venta):
    servicio_ventas.asociar_cliente(db, autor, venta, None, cliente_nuevo={**DATOS, "dni": "30111222"})

    assert venta.cliente is not None
    assert venta.cliente.nombre_completo == "Gómez, Ana"
    assert venta.cliente.dni == "30111222"
    alta = db.execute(
        select(Auditoria).where(
            Auditoria.accion == "cliente.crear", Auditoria.entidad_id == venta.cliente.id
        )
    ).scalar_one_or_none()
    assert alta is not None


def test_api_al_cobrar_no_se_mandan_existente_y_nuevo_juntos(
    client, db, autor, venta, dispositivo
):
    db.commit()
    client.cookies.set("device_uuid", str(dispositivo.uuid))
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    r = client.post(
        f"/api/v1/ventas/{venta.id}/cliente",
        json={"cliente_id": 1, "cliente_nuevo": DATOS},
    )
    assert r.status_code == 422

    r = client.post(f"/api/v1/ventas/{venta.id}/cliente", json={"cliente_nuevo": DATOS})
    assert r.status_code == 200, r.text
    assert r.json()["cliente"]["nombre_completo"] == "Gómez, Ana"
