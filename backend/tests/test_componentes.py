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
