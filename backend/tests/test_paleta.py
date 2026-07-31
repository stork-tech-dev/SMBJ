"""
Tests de la paleta de colores por empresa.

El sistema se instala para Soleil o para Mallorca, y cada una tiene su gama
de colores además de su logo. El mecanismo es un atributo `data-empresa` en
`<html>` que activa un bloque de variables CSS.

Estos tests cuidan las dos mitades del mecanismo: que el atributo llegue al
HTML, y que ningún color quede escrito a mano fuera de la paleta —que es
exactamente lo que haría que una pantalla conservara los colores de la otra
empresa.
"""

import re
from pathlib import Path

import pytest

from app.core.permisos import ROL_CUENTA_MAESTRA
from app.core.utils import ahora_db
from app.models.configuracion import ConfiguracionSistema
from app.services import configuracion as servicio_configuracion

RAIZ = Path(__file__).resolve().parents[1] / "app"
PLANTILLAS = RAIZ / "templates"
CSS = RAIZ / "static" / "css" / "custom.css"

# Colores de marca: los que cambian de una empresa a la otra. Los grises,
# el rojo de error y el verde de éxito se comparten a propósito.
VARIABLES_DE_MARCA = [
    "--color-primary",
    "--color-primary-hover",
    "--color-accent",
    "--color-welcome",
    "--color-sidebar-bg",
]


@pytest.fixture
def configurar_letra(db):
    """Crea (o actualiza) la fila única de configuración con una letra."""

    def _configurar(letra: str):
        config = servicio_configuracion.obtener_configuracion(db)
        if config is None:
            config = ConfiguracionSistema(
                redondeo=1000,
                descuento_maximo=30,
                metodo_descuento="encadenado",
                letra_empresa=letra,
                updated_at=ahora_db(),
            )
            db.add(config)
        else:
            config.letra_empresa = letra
        db.flush()
        return config

    return _configurar


def _bloque(selector: str, css: str) -> str:
    """
    Devuelve el cuerpo de la regla CSS de un selector, o "" si no está.

    El selector va anclado al principio de línea a propósito: sin eso,
    buscar `[data-empresa="S"]` también encontraría `.dark[data-empresa="S"]`
    y `:root` encontraría el de adentro del `@media`, según cuál apareciera
    primero en el archivo.
    """
    coincidencia = re.search(
        r"^" + re.escape(selector) + r"\s*\{([^}]*)\}", css, flags=re.MULTILINE
    )
    return coincidencia.group(1) if coincidencia else ""


# ---------------------------------------------------------------------------
# El atributo llega al HTML
# ---------------------------------------------------------------------------


def test_login_lleva_la_empresa_configurada(client, configurar_letra):
    configurar_letra("M")

    resp = client.get("/login")

    assert resp.status_code == 200
    assert 'data-empresa="M"' in resp.text


def test_sidebar_lleva_la_empresa_configurada(client, crear_usuario, configurar_letra):
    configurar_letra("M")
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    resp = client.get("/")

    assert resp.status_code == 200
    assert 'data-empresa="M"' in resp.text


def test_cambiar_la_letra_cambia_la_paleta(client, crear_usuario, configurar_letra):
    """
    Igual que el logo: la letra se lee en cada request, así que cambiarla en
    la configuración alcanza —no hace falta reiniciar ni recompilar nada.
    """
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    configurar_letra("S")
    assert 'data-empresa="S"' in client.get("/").text

    configurar_letra("M")
    assert 'data-empresa="M"' in client.get("/").text


# ---------------------------------------------------------------------------
# La paleta está completa
# ---------------------------------------------------------------------------


def test_soleil_redefine_todos_los_colores_de_marca():
    """
    Una variable de marca que Soleil se olvide de redefinir se queda con el
    azul de Mallorca. No rompe nada visible en los tests, así que tiene que
    haber una comprobación explícita.
    """
    css = CSS.read_text()
    soleil = _bloque('[data-empresa="S"]', css)

    assert soleil, "falta el bloque de paleta de Soleil"
    faltantes = [v for v in VARIABLES_DE_MARCA if v not in soleil]
    assert not faltantes, f"Soleil no redefine: {faltantes}"


def test_soleil_tiene_paleta_para_modo_oscuro():
    """Sin esto, prender el tema oscuro en Soleil devuelve los azules."""
    css = CSS.read_text()
    oscuro = _bloque('.dark[data-empresa="S"]', css)

    assert oscuro, "falta la paleta oscura de Soleil"
    faltantes = [v for v in VARIABLES_DE_MARCA if v not in oscuro]
    assert not faltantes, f"el oscuro de Soleil no redefine: {faltantes}"


def _luminancia(hexa: str) -> float:
    """Luminancia relativa de un color, según la fórmula de WCAG 2."""
    hexa = hexa.lstrip("#")
    canales = [int(hexa[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    canales = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in canales]
    return 0.2126 * canales[0] + 0.7152 * canales[1] + 0.0722 * canales[2]


def _contraste(a: str, b: str) -> float:
    la, lb = _luminancia(a), _luminancia(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def test_el_logo_de_soleil_se_lee_sobre_su_sidebar():
    """
    El logo de Soleil es un triángulo oscuro de color fijo: al revés que el
    de Mallorca, no se adapta al fondo. Si alguien "arregla" el modo oscuro
    llevando el sidebar de Soleil a un casi-negro como el de Mallorca, el
    logo desaparece —y no hay test funcional que lo note, porque el HTML
    sigue estando ahí.
    """
    triangulo = "#231F20"  # el fill del logo, en components/logo_soleil.svg
    css = CSS.read_text()

    for selector in ('[data-empresa="S"]', '.dark[data-empresa="S"]'):
        bloque = _bloque(selector, css)
        fondo = re.search(r"--color-sidebar-bg:\s*(#[0-9a-fA-F]{6})", bloque).group(1)
        ratio = _contraste(triangulo, fondo)
        assert ratio >= 4.5, (
            f"{selector}: el sidebar {fondo} deja el logo con contraste {ratio:.2f}"
        )


def test_las_variables_de_marca_existen_en_root():
    """`:root` es la instalación de Mallorca: el resto solo la sobrescribe."""
    raiz = _bloque(":root", CSS.read_text())

    faltantes = [v for v in VARIABLES_DE_MARCA if v not in raiz]
    assert not faltantes, f"faltan en :root: {faltantes}"


# ---------------------------------------------------------------------------
# Ningún color escrito a mano en las plantillas
# ---------------------------------------------------------------------------

# Negros y blancos transparentes: son sombras y velos de modal, no colores
# de marca. Se ven igual con cualquier identidad, así que no hace falta que
# salgan de una variable.
NEUTRALES = re.compile(r"rgba?\(\s*(0\s*,\s*0\s*,\s*0|255\s*,\s*255\s*,\s*255)\s*,")

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
RGB = re.compile(r"rgba?\([^)]*\)")


def _plantillas():
    return sorted(PLANTILLAS.rglob("*.html"))


def test_ninguna_plantilla_escribe_un_color_hexadecimal():
    """
    Un hexadecimal en una plantilla es un color que se escapó de la paleta:
    al instalar la otra empresa se queda con el valor viejo. Los colores van
    por las clases de Tailwind mapeadas a variables, o por una clase de
    custom.css.
    """
    culpables = [
        f"{p.relative_to(PLANTILLAS)}: {m}"
        for p in _plantillas()
        for m in HEX.findall(p.read_text())
    ]

    assert not culpables, "colores hexadecimales fuera de la paleta:\n" + "\n".join(culpables)


def test_ninguna_plantilla_escribe_un_color_rgb_de_marca():
    """
    El mismo problema, disfrazado: `rgba(85,126,170,0.35)` es el accent de
    Mallorca escrito en decimal, y el test de hexadecimales no lo veía.
    Solo se permiten negro y blanco con transparencia.
    """
    culpables = [
        f"{p.relative_to(PLANTILLAS)}: {m}"
        for p in _plantillas()
        for m in RGB.findall(p.read_text())
        if not NEUTRALES.match(m)
    ]

    assert not culpables, "colores rgb() fuera de la paleta:\n" + "\n".join(culpables)


def test_la_sombra_de_las_tarjetas_sale_de_la_paleta():
    """
    La sombra de las tablas estaba copiada en diez plantillas con el color
    escrito a mano. Ahora es una clase; este test cuida que siga saliendo de
    la variable y que nadie la vuelva a copiar.
    """
    css = CSS.read_text()

    assert "var(--color-accent)" in _bloque(".tarjeta", css)
    assert "var(--color-accent)" in _bloque(".tarjeta-enlace", css)

    en_clase = re.compile(r'class="[^"]*\btarjeta\b')
    usan = [p.name for p in _plantillas() if en_clase.search(p.read_text())]
    assert len(usan) >= 8, f"solo {len(usan)} plantillas usan la clase: {usan}"
