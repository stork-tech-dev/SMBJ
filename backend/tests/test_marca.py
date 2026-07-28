"""
Tests del logotipo de la empresa.

Qué marca se muestra depende de `configuracion_sistema.letra_empresa`, y
aplica igual en el sidebar y en las pantallas de autenticación.
"""

import pytest

from app.core.permisos import ROL_CUENTA_MAESTRA
from app.core.utils import ahora_db
from app.models.configuracion import ConfiguracionSistema
from app.services import configuracion as servicio_configuracion

LOGO_MALLORCA = 'aria-label="Mallorca"'


@pytest.fixture
def configurar_letra(db):
    """Crea (o actualiza) la fila única de configuración con una letra."""

    def _configurar(letra: str):
        config = servicio_configuracion.obtener_configuracion(db)
        if config is None:
            config = ConfiguracionSistema(
                redondeo=10, descuento_maximo=30, metodo_descuento="encadenado",
                letra_empresa=letra, updated_at=ahora_db(),
            )
            db.add(config)
        else:
            config.letra_empresa = letra
        db.flush()
        return config

    return _configurar


def test_letra_por_defecto_sin_configuracion(db):
    """Sin seed corrido, el layout no debe romperse."""
    assert servicio_configuracion.letra_empresa(db) == "S"


def test_login_muestra_el_logo_de_mallorca(client, configurar_letra):
    configurar_letra("M")

    resp = client.get("/login")

    assert resp.status_code == 200
    assert LOGO_MALLORCA in resp.text


def test_login_muestra_soleil_en_texto(client, configurar_letra):
    """Soleil todavía no tiene logo: va la palabra."""
    configurar_letra("S")

    resp = client.get("/login")

    assert resp.status_code == 200
    assert LOGO_MALLORCA not in resp.text
    assert "Soleil" in resp.text


def test_sidebar_usa_la_misma_marca(client, crear_usuario, configurar_letra):
    configurar_letra("M")
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    resp = client.get("/")

    assert resp.status_code == 200
    assert LOGO_MALLORCA in resp.text


def test_cambiar_la_letra_cambia_la_marca(client, crear_usuario, configurar_letra, db):
    """El cambio se refleja sin reiniciar: la letra se lee en cada request."""
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    configurar_letra("S")
    assert LOGO_MALLORCA not in client.get("/").text

    configurar_letra("M")
    assert LOGO_MALLORCA in client.get("/").text
