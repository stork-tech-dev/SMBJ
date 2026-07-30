"""
Tests de la lectura del User-Agent.

Las cadenas son reales, no inventadas: el formato del User-Agent es
irregular y los casos que importan son los que efectivamente mandan los
navegadores. Función pura, sin base ni fixtures.
"""

import pytest

from app.core.user_agent import interpretar

# (descripción, user agent, sistema esperado, navegador esperado, modelo esperado)
CASOS = [
    (
        "Windows 10/11 + Chrome",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Windows 10/11", "Chrome 120", None,
    ),
    (
        "Windows + Edge (se anuncia también como Chrome)",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.2210.91",
        "Windows 10/11", "Edge 120", None,
    ),
    (
        "Windows 7 + Firefox",
        "Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
        "Windows 7", "Firefox 115", None,
    ),
    (
        "macOS + Safari",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        "macOS 10.15.7", "Safari 17", None,
    ),
    (
        "Android + Chrome, con modelo",
        "Mozilla/5.0 (Linux; Android 13; SM-A536E) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Android 13", "Chrome 120", "SM-A536E",
    ),
    (
        "Android con Build/ en el modelo",
        "Mozilla/5.0 (Linux; Android 11; Pixel 5 Build/RQ3A.210805.001.A1) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Android 11", "Chrome 120", "Pixel 5",
    ),
    (
        "iPhone + Safari",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
        "iOS 17.1", "Safari 17", "iPhone",
    ),
    (
        "iPad",
        "Mozilla/5.0 (iPad; CPU OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "iOS 16.6", "Safari 16", "iPad",
    ),
    (
        "Samsung Internet (se anuncia también como Chrome)",
        "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 "
        "(KHTML, like Gecko) SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36",
        "Android 13", "Samsung Internet 23", "SM-S918B",
    ),
    (
        "Ubuntu + Firefox",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/118.0",
        "Ubuntu", "Firefox 118", None,
    ),
]


@pytest.mark.parametrize(
    "descripcion,ua,sistema,navegador,modelo",
    CASOS,
    ids=[c[0] for c in CASOS],
)
def test_interpreta_user_agents_reales(descripcion, ua, sistema, navegador, modelo):
    datos = interpretar(ua)
    assert datos["sistema_operativo"] == sistema
    assert datos["navegador"] == navegador
    assert datos["modelo"] == modelo


def test_el_orden_importa_edge_no_se_lee_como_chrome():
    """
    Edge, Opera y Samsung Internet incluyen "Chrome/" en su User-Agent. Si
    el orden de las reglas se invirtiera, los tres se informarían como
    Chrome y la columna perdería sentido.
    """
    edge = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.2210.91"
    )
    assert interpretar(edge)["navegador"].startswith("Edge")


def test_android_no_se_lee_como_linux():
    """El User-Agent de Android también dice 'Linux'."""
    ua = "Mozilla/5.0 (Linux; Android 13; SM-A536E) AppleWebKit/537.36 Chrome/120.0.0.0"
    assert interpretar(ua)["sistema_operativo"] == "Android 13"


def test_el_placeholder_de_chrome_no_se_toma_como_modelo():
    """
    Chrome reemplaza el modelo por "K" cuando reduce el User-Agent para no
    exponerlo. Guardarlo sería informar un modelo que no existe.
    """
    ua = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile"
    assert interpretar(ua)["modelo"] is None


@pytest.mark.parametrize("vacio", [None, "", "   "])
def test_sin_user_agent_devuelve_las_tres_claves_en_none(vacio):
    """Quien llama guarda el resultado sin preguntar: siempre las 3 claves."""
    assert interpretar(vacio) == {
        "sistema_operativo": None, "navegador": None, "modelo": None
    }


def test_un_user_agent_desconocido_no_rompe():
    """Un bot o un cliente raro devuelve None, no una excepción."""
    datos = interpretar("algo-que-no-es-un-navegador/1.0")
    assert datos == {"sistema_operativo": None, "navegador": None, "modelo": None}
