"""
Tests del logotipo de la empresa.

Qué marca se muestra depende de `configuracion_sistema.letra_empresa`, y
aplica igual en el sidebar y en las pantallas de autenticación.
"""

import re

import pytest

from app.core.permisos import ROL_CUENTA_MAESTRA
from app.core.utils import ahora_db
from app.models.configuracion import ConfiguracionSistema
from app.services import configuracion as servicio_configuracion

LOGO_MALLORCA = 'aria-label="Mallorca"'
LOGO_SOLEIL = 'aria-label="Soleil Bijouterie"'


@pytest.fixture
def configurar_letra(db):
    """Crea (o actualiza) la fila única de configuración con una letra."""

    def _configurar(letra: str):
        config = servicio_configuracion.obtener_configuracion(db)
        if config is None:
            config = ConfiguracionSistema(
                redondeo=1000, descuento_maximo=30, metodo_descuento="encadenado",
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


def test_login_muestra_el_logo_de_soleil(client, configurar_letra):
    configurar_letra("S")

    resp = client.get("/login")

    assert resp.status_code == 200
    assert LOGO_SOLEIL in resp.text
    assert LOGO_MALLORCA not in resp.text


def test_el_logo_de_soleil_no_depende_de_currentcolor(client, configurar_letra):
    """
    El de Soleil es un logo de tres colores sobre su propio triángulo
    oscuro: si alguien lo "unificara" pasándolo a `currentColor` para que
    se parezca al de Mallorca, quedaría un triángulo monocromo ilegible
    sobre el dorado del sidebar.
    """
    configurar_letra("S")

    texto = client.get("/login").text
    logo = texto[texto.index(LOGO_SOLEIL) : texto.index("</svg>", texto.index(LOGO_SOLEIL))]

    assert "currentColor" not in logo
    for color in ("#CBA770", "#D1D3D4", "#231F20"):
        assert color in logo, f"el logo perdió el color {color}"


@pytest.mark.parametrize("letra", ["M", "S"])
def test_el_favicon_es_el_de_la_empresa(client, configurar_letra, letra):
    configurar_letra(letra)

    texto = client.get("/login").text

    assert f"/static/img/favicon-{letra}.svg" in texto
    assert f"/static/img/favicon-{letra}-32.png" in texto
    assert f"/static/img/apple-touch-icon-{letra}.png" in texto


@pytest.mark.parametrize("letra", ["M", "S"])
def test_los_archivos_del_favicon_se_sirven(client, configurar_letra, letra):
    """
    Un `<link rel="icon">` a un archivo que no existe no rompe la página:
    el navegador se queda con el icono en blanco y nadie se entera. Por eso
    se piden los tres archivos de verdad.
    """
    configurar_letra(letra)
    texto = client.get("/login").text

    enlaces = re.findall(r'rel="(?:icon|apple-touch-icon)"[^>]*href="([^"]+)"', texto)
    assert len(enlaces) == 3, f"se esperaban 3 iconos, hay {len(enlaces)}"

    for url in enlaces:
        resp = client.get(url)
        assert resp.status_code == 200, f"{url} devolvió {resp.status_code}"
        assert resp.content, f"{url} vino vacío"


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
