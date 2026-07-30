"""
Tests del árbol de categorías.

Se concentran en las reglas que mantienen el árbol sano: el nivel derivado,
el tope de 5 niveles, los ciclos y las bajas bloqueadas. La estructura la
garantiza la base con constraints; acá se prueba que el service devuelva
errores entendibles antes de llegar a ellos.
"""

import pytest

from app.core.permisos import ROL_CUENTA_MAESTRA, ROL_VENDEDOR, Modulo
from app.models.categoria import NIVEL_MAXIMO
from app.services import categorias as servicio
from app.services.roles import NoEncontrado, ReglaDeNegocio


@pytest.fixture
def autor(crear_usuario):
    return crear_usuario("admin", ROL_CUENTA_MAESTRA)


@pytest.fixture
def rama(db, autor):
    """Una rama de 3 niveles: Calzado → Zapatillas → Running."""
    calzado = servicio.crear_categoria(db, autor, nombre="Calzado")
    zapatillas = servicio.crear_categoria(db, autor, nombre="Zapatillas", parent_id=calzado.id)
    running = servicio.crear_categoria(db, autor, nombre="Running", parent_id=zapatillas.id)
    return calzado, zapatillas, running


# ============================================================================
# NIVEL DERIVADO
# ============================================================================


def test_el_nivel_lo_deriva_el_padre(db, rama):
    calzado, zapatillas, running = rama
    assert (calzado.nivel, zapatillas.nivel, running.nivel) == (1, 2, 3)
    assert calzado.parent_id is None


def test_no_se_puede_pasar_del_nivel_maximo(db, autor):
    """Cinco niveles entran; el sexto no."""
    padre = None
    for n in range(1, NIVEL_MAXIMO + 1):
        actual = servicio.crear_categoria(db, autor, nombre=f"Nivel {n}", parent_id=padre)
        assert actual.nivel == n
        padre = actual.id

    with pytest.raises(ReglaDeNegocio, match="más de 5 niveles"):
        servicio.crear_categoria(db, autor, nombre="Nivel 6", parent_id=padre)


def test_padre_inexistente_da_404(db, autor):
    with pytest.raises(NoEncontrado):
        servicio.crear_categoria(db, autor, nombre="Huérfana", parent_id=999999)


# ============================================================================
# NOMBRES ENTRE HERMANOS
# ============================================================================


def test_dos_hermanos_no_pueden_llamarse_igual(db, autor, rama):
    calzado, _, _ = rama
    with pytest.raises(ReglaDeNegocio, match="Ya existe una categoría"):
        servicio.crear_categoria(db, autor, nombre="Zapatillas", parent_id=calzado.id)


def test_el_mismo_nombre_en_ramas_distintas_es_valido(db, autor, rama):
    """"Verano" puede existir bajo Calzado y bajo Ropa a la vez."""
    calzado, _, _ = rama
    ropa = servicio.crear_categoria(db, autor, nombre="Ropa")

    servicio.crear_categoria(db, autor, nombre="Verano", parent_id=calzado.id)
    otra = servicio.crear_categoria(db, autor, nombre="Verano", parent_id=ropa.id)

    assert otra.nombre == "Verano"


def test_dos_raices_no_pueden_llamarse_igual(db, autor, rama):
    """
    El caso que se escapa si el índice único no usa NULLS NOT DISTINCT:
    en las raíces parent_id es NULL y PostgreSQL trata cada NULL como
    distinto, así que dejaría pasar el duplicado.
    """
    with pytest.raises(ReglaDeNegocio):
        servicio.crear_categoria(db, autor, nombre="Calzado")


# ============================================================================
# MOVER RAMAS
# ============================================================================


def test_mover_arrastra_el_nivel_de_la_descendencia(db, autor, rama):
    calzado, zapatillas, running = rama
    ropa = servicio.crear_categoria(db, autor, nombre="Ropa")

    # Zapatillas (con Running colgando) pasa de Calzado a Ropa.
    servicio.mover_categoria(db, autor, zapatillas.id, nuevo_parent_id=ropa.id)

    assert zapatillas.parent_id == ropa.id
    assert zapatillas.nivel == 2
    assert running.nivel == 3  # se mantiene un nivel por debajo


def test_mover_a_la_raiz_recalcula_toda_la_rama(db, autor, rama):
    _, zapatillas, running = rama

    servicio.mover_categoria(db, autor, zapatillas.id, nuevo_parent_id=None)

    assert zapatillas.parent_id is None
    assert zapatillas.nivel == 1
    assert running.nivel == 2


def test_una_categoria_no_puede_ser_su_propio_padre(db, autor, rama):
    calzado, _, _ = rama
    with pytest.raises(ReglaDeNegocio, match="su propio padre"):
        servicio.mover_categoria(db, autor, calzado.id, nuevo_parent_id=calzado.id)


def test_no_se_puede_mover_una_rama_dentro_de_si_misma(db, autor, rama):
    """
    Colgar Calzado de Running crearía un ciclo: la rama quedaría fuera del
    árbol, inalcanzable desde cualquier raíz.
    """
    calzado, _, running = rama
    with pytest.raises(ReglaDeNegocio, match="su propia rama"):
        servicio.mover_categoria(db, autor, calzado.id, nuevo_parent_id=running.id)


def test_mover_valida_la_profundidad_de_toda_la_rama(db, autor, rama):
    """
    No alcanza con que entre la raíz de la rama: si Calzado (3 niveles) se
    cuelga de un nivel 4, su descendencia terminaría en el nivel 6.
    """
    calzado, _, _ = rama

    padre = None
    for n in range(1, 5):  # cadena de 4 niveles
        actual = servicio.crear_categoria(db, autor, nombre=f"Cadena {n}", parent_id=padre)
        padre = actual.id

    with pytest.raises(ReglaDeNegocio, match="no entra a partir del nivel"):
        servicio.mover_categoria(db, autor, calzado.id, nuevo_parent_id=padre)


# ============================================================================
# BAJAS
# ============================================================================


def test_no_se_elimina_una_categoria_con_hijos(db, autor, rama):
    calzado, _, _ = rama
    with pytest.raises(ReglaDeNegocio, match="subcategoría"):
        servicio.eliminar_categoria(db, autor, calzado.id)


def test_se_elimina_una_hoja(db, autor, rama):
    _, _, running = rama
    servicio.eliminar_categoria(db, autor, running.id)

    with pytest.raises(NoEncontrado):
        servicio.obtener_categoria(db, running.id)


# ============================================================================
# ÁRBOL Y LISTADO
# ============================================================================


def test_el_arbol_llega_anidado(db, autor, rama):
    servicio.crear_categoria(db, autor, nombre="Ropa")

    arbol = servicio.arbol(db)

    assert [r["nombre"] for r in arbol] == ["Calzado", "Ropa"]
    calzado = arbol[0]
    assert calzado["hijos"][0]["nombre"] == "Zapatillas"
    assert calzado["hijos"][0]["hijos"][0]["nombre"] == "Running"


def test_el_arbol_usa_una_sola_consulta(db, autor, rama):
    """
    Arma la jerarquía en memoria en vez de hacer lazy load por nodo: con
    5 niveles un N+1 se multiplica rápido.
    """
    from sqlalchemy import event

    consultas = []
    motor = db.get_bind()

    def contar(conn, cursor, statement, *a):
        if "categorias" in statement.lower():
            consultas.append(statement)

    event.listen(motor, "before_cursor_execute", contar)
    try:
        servicio.arbol(db)
    finally:
        event.remove(motor, "before_cursor_execute", contar)

    assert len(consultas) == 1, f"{len(consultas)} consultas: {consultas}"


def test_listado_filtra_en_el_backend(db, autor, rama):
    por_nivel = servicio.listar_categorias(db, nivel=2)
    assert [c.nombre for c in por_nivel] == ["Zapatillas"]

    # ILIKE: insensible a mayúsculas, como el resto de los filtros de texto.
    por_nombre = servicio.listar_categorias(db, nombre="calz")
    assert [c.nombre for c in por_nombre] == ["Calzado"]


# ============================================================================
# API Y PERMISOS
# ============================================================================


def test_el_arbol_no_se_confunde_con_un_id(client, db, autor, rama, login):
    """`/categorias/arbol` va antes que `/categorias/{id}` en el router."""
    db.commit()
    resp = client.get("/api/v1/categorias/arbol", headers=login("admin"))

    assert resp.status_code == 200
    assert resp.json()[0]["nombre"] == "Calzado"


def test_sin_permiso_de_productos_no_se_ve_el_arbol(client, crear_usuario, login):
    crear_usuario("juan", ROL_VENDEDOR)
    resp = client.get("/api/v1/categorias/arbol", headers=login("juan"))
    assert resp.status_code == 403


def test_el_alta_por_la_api_deriva_el_nivel(client, db, autor, rama, login):
    calzado, _, _ = rama
    db.commit()

    resp = client.post(
        "/api/v1/categorias",
        json={"nombre": "Botas", "parent_id": calzado.id},
        headers=login("admin"),
    )

    assert resp.status_code == 201
    assert resp.json()["nivel"] == 2


def test_el_alta_ignora_un_nivel_mandado_por_el_cliente(client, db, autor, rama, login):
    """
    `nivel` no está en el schema: mandarlo no puede alterar el árbol.
    Si el schema lo aceptara, se podría crear un nivel 5 bajo una raíz.
    """
    calzado, _, _ = rama
    db.commit()

    resp = client.post(
        "/api/v1/categorias",
        json={"nombre": "Sandalias", "parent_id": calzado.id, "nivel": 5},
        headers=login("admin"),
    )

    assert resp.status_code == 201
    assert resp.json()["nivel"] == 2


def test_el_conflicto_devuelve_409(client, db, autor, rama, login):
    calzado, _, _ = rama
    db.commit()

    resp = client.post(
        "/api/v1/categorias",
        json={"nombre": "Zapatillas", "parent_id": calzado.id},
        headers=login("admin"),
    )

    assert resp.status_code == 409
    assert "Ya existe" in resp.json()["detail"]


def test_la_baja_bloqueada_devuelve_409(client, db, autor, rama, login):
    calzado, _, _ = rama
    db.commit()

    resp = client.delete(f"/api/v1/categorias/{calzado.id}", headers=login("admin"))
    assert resp.status_code == 409


def test_el_alta_queda_auditada(db, autor):
    from sqlalchemy import select

    from app.models.auditoria import Auditoria

    categoria = servicio.crear_categoria(db, autor, nombre="Calzado")

    registro = db.execute(
        select(Auditoria).where(Auditoria.accion == "categoria.crear")
    ).scalars().one()
    assert registro.entidad == "categorias"
    assert registro.entidad_id == categoria.id
    assert registro.estado_nuevo["nombre"] == "Calzado"
