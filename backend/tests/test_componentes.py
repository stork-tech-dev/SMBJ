"""
Tests de los macros del design system.

Existen porque la home dejó de usarlos. Antes era una página de
demostración que los renderizaba todos, y eso oficiaba de red: cuando un
comentario `{# #}` anidado rompió `table.html`, el error apareció al pedir
la home. Vaciada la home, esos macros no los ejercita nadie hasta que un
módulo futuro los use, y un error quedaría dormido hasta entonces.

No prueban el diseño, sino que cada macro renderice sin explotar y emita
lo mínimo que promete.
"""

import pytest
from jinja2 import Environment, FileSystemLoader
from pathlib import Path

PLANTILLAS = Path(__file__).parent.parent / "app" / "templates"


@pytest.fixture(scope="module")
def env():
    entorno = Environment(loader=FileSystemLoader(str(PLANTILLAS)))
    entorno.globals["url_for"] = lambda *a, **k: "#"
    entorno.globals["estatico"] = lambda ruta: ruta
    return entorno


def render(env, fuente, **contexto):
    return env.from_string(fuente).render(**contexto)


# ============================================================================
# TABLA Y BARRA DE FILTROS
# ============================================================================


def test_la_barra_de_filtros_renderiza(env):
    html = render(env, """
        {% from "components/table.html" import barra_filtros %}
        {% call barra_filtros(url_crear='/x/nuevo', total=7,
                              singular='producto', plural='productos') %}
            <input id="f">
        {% endcall %}
    """)
    assert "Limpiar filtros" in html
    assert "7 productos" in html
    assert "+ Crear nuevo" in html


def test_la_barra_pluraliza(env):
    # Marcador y replace() en vez de formateo con %: la plantilla trae
    # llaves {% %} que Python interpretaría como especificadores.
    fuente = """
        {% from "components/table.html" import barra_filtros %}
        {% call barra_filtros(total=TOTAL, singular='producto', plural='productos') %}{% endcall %}
    """
    uno = " ".join(render(env, fuente.replace("TOTAL", "1")).split())
    dos = " ".join(render(env, fuente.replace("TOTAL", "2")).split())

    assert "1 producto encontrado" in uno
    assert "2 productos encontrados" in dos


def test_la_tabla_renderiza_filas_y_acciones(env):
    html = render(env, """
        {% from "components/table.html" import tabla %}
        {{ tabla(columnas=[{'key': 'nombre', 'label': 'Nombre'}],
                 filas=[{'id': 1, 'nombre': 'Uno'}],
                 acciones=['ver', 'editar', 'borrar'],
                 url_base='/x') }}
    """)
    assert "Nombre" in html and "Uno" in html
    assert "/x/1" in html
    assert "Acciones" in html


def test_la_tabla_vacia_muestra_su_mensaje(env):
    html = render(env, """
        {% from "components/table.html" import tabla %}
        {{ tabla(columnas=[{'key': 'a', 'label': 'A'}], filas=[], vacio='Nada por acá.') }}
    """)
    assert "Nada por acá." in html


def test_la_paginacion_se_oculta_con_una_sola_pagina(env):
    fuente = """
        {% from "components/table.html" import paginacion %}
        {{ paginacion(pagina=1, total_paginas=TOTAL) }}
    """
    assert "Siguiente" not in render(env, fuente.replace("TOTAL", "1"))
    assert "Siguiente" in render(env, fuente.replace("TOTAL", "3"))


# ============================================================================
# CAMPOS DE FORMULARIO
# ============================================================================


def test_los_campos_de_formulario_renderizan(env):
    html = render(env, """
        {% from "components/form_field.html" import campo, campo_select, campo_rango,
                                                    campo_booleano, boton %}
        {{ campo('busqueda', 'Nombre', placeholder='Buscar…') }}
        {{ campo_select('estado', 'Estado',
                        opciones=[{'value': 'a', 'label': 'Activo'}]) }}
        {{ campo_booleano('activo', 'Activo') }}
        {{ campo_rango('fecha', 'Fecha', tipo='date') }}
        {{ boton('Guardar', variante='primario') }}
    """)
    for esperado in ("Nombre", "Buscar…", "Estado", "Activo", "Fecha", "Guardar"):
        assert esperado in html, esperado


# ============================================================================
# BADGES Y MODAL
# ============================================================================


def test_los_badges_renderizan(env):
    html = render(env, """
        {% from "components/badge.html" import badge, estado_texto %}
        {{ badge('Activo', 'activo') }}
        {{ badge('Pendiente', 'pendiente') }}
        {{ estado_texto('Autorizado', 'exito') }}
    """)
    assert "Activo" in html and "Pendiente" in html and "Autorizado" in html


def test_el_modal_de_confirmacion_renderiza(env):
    html = render(env, """
        {% from "components/modal.html" import modal_confirmacion %}
        {{ modal_confirmacion() }}
    """)
    assert "Cancelar" in html
    assert 'role="dialog"' in html


# ============================================================================
# TODOS LOS MACROS, DE UNA
# ============================================================================


def test_todos_los_componentes_se_importan_sin_error(env):
    """
    Un `{# #}` anidado dentro de otro comentario cierra el bloque antes de
    tiempo y convierte el resto del archivo en código vivo. Importar cada
    componente lo detecta; parsearlo, no.
    """
    errores = {}
    for archivo in sorted((PLANTILLAS / "components").glob("*.html")):
        # Los que empiezan con guion bajo son includes, no módulos de
        # macros: esperan variables del contexto de quien los incluye
        # (`_sidebar_item.html` necesita `item`), así que no se pueden
        # importar sueltos.
        if archivo.name.startswith("_"):
            continue
        nombre = f"components/{archivo.name}"
        try:
            env.get_template(nombre).make_module()
        except Exception as exc:  # noqa: BLE001
            errores[nombre] = f"{type(exc).__name__}: {exc}"

    assert not errores, errores


# ============================================================================
# REGLAS QUE VALEN PARA TODAS LAS PLANTILLAS
# ============================================================================


def test_ningun_modal_se_cierra_al_clickear_el_velo():
    """
    Los modales se cierran con la X, con Cancelar o con Escape. NUNCA con un
    clic en el fondo oscuro.

    El velo cerraba el diálogo con `@click.self`, así que un clic de más al
    costado de un alta de producto o de usuario se llevaba puesto el
    formulario entero: sin aviso, sin confirmación y sin forma de recuperar
    lo cargado. Las tres salidas que quedan son gestos deliberados; el
    resbalón del mouse no.

    El test barre las plantillas y no una lista de archivos porque la regla
    tiene que valer también para los modales que todavía no existen: es la
    única forma de que el próximo no lo reintroduzca por copiar y pegar uno
    viejo.

    No confundir con dos usos legítimos que quedan afuera:
      - `components/combobox.html` cierra su lista con `@click.outside`, que
        es otra directiva y otro problema: ahí no se pierde nada.
      - `base.html` cierra el cajón de navegación con `@click` (sin `.self`)
        en su velo. Es un menú, no un formulario: tocar el fondo para
        cerrarlo es lo que espera cualquiera en un teléfono.
    """
    culpables = [
        str(archivo.relative_to(PLANTILLAS))
        for archivo in sorted(PLANTILLAS.rglob("*.html"))
        if "@click.self" in archivo.read_text(encoding="utf-8")
    ]

    assert not culpables, (
        f"el velo de estos modales vuelve a cerrar al clickearlo: {culpables}"
    )


def test_todos_los_modales_se_cierran_con_escape():
    """
    Escape es la contraparte de haber sacado el clic en el velo: es la salida
    de teclado, la que espera cualquiera frente a un diálogo, y la única que
    no obliga a apuntar el mouse a la X.

    Tres modales no la tenían —el detalle de usuario, el form de roles y la
    confirmación de baja de categorías— y se notaba justamente porque todos
    los demás sí. Se cuenta un `@keydown.escape.window` por cada velo del
    archivo: `pages/productos/listado.html` tiene cuatro modales y necesita
    los cuatro.

    `base.html` queda afuera solo: su velo es `z-40` porque es el cajón de
    navegación y no un modal, y su Escape vive en el contenedor de más
    arriba.
    """
    velo = 'class="fixed inset-0 z-50'
    faltantes = {}
    for archivo in sorted(PLANTILLAS.rglob("*.html")):
        texto = archivo.read_text(encoding="utf-8")
        velos = texto.count(velo)
        escapes = texto.count("@keydown.escape.window")
        if velos > escapes:
            faltantes[str(archivo.relative_to(PLANTILLAS))] = f"{velos} velos, {escapes} escapes"

    assert not faltantes, f"modales que no se cierran con Escape: {faltantes}"
