"""
Tests de las fotos de producto.

Es la primera entrada de archivos subidos por el usuario, así que la mitad
de los tests son de las validaciones que impiden que entre cualquier cosa.
"""

import io
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.permisos import ROL_CUENTA_MAESTRA, ROL_VENDEDOR
from app.models.producto_foto import MAX_FOTOS_POR_PRODUCTO, ProductoFoto
from app.services import categorias as servicio_categorias
from app.services import producto_fotos as servicio
from app.services import productos as servicio_productos
from app.services import proveedores as servicio_proveedores
from app.services.roles import NoEncontrado, ReglaDeNegocio

# Cabeceras reales de cada formato: es lo que mira `_detectar_formato`.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 64


@pytest.fixture
def autor(crear_usuario):
    return crear_usuario("admin", ROL_CUENTA_MAESTRA)


@pytest.fixture
def producto(db, autor):
    categoria = servicio_categorias.crear_categoria(db, autor, nombre="Calzado")
    proveedor = servicio_proveedores.crear_proveedor(
        db, autor, nombre="Distribuidora Norte", dolar_actual=Decimal("1000")
    )
    return servicio_productos.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"),
        descripcion="Producto de prueba",
)


@pytest.fixture(autouse=True)
def directorio_temporal(tmp_path, monkeypatch):
    """
    Los tests escriben en un directorio propio y descartable.

    La primera versión de este fixture vaciaba el directorio REAL de fotos
    al terminar cada test, y correr la suite borraba las fotos que había
    subido un usuario. Redirigirlo es la única forma segura: así los tests
    no pueden tocar datos reales, en lugar de tocarlos y después limpiar.
    """
    destino = tmp_path / "productos"
    destino.mkdir()
    monkeypatch.setattr(servicio, "_DIRECTORIO", destino)
    return destino


# ============================================================================
# VALIDACIONES DE LA SUBIDA
# ============================================================================


@pytest.mark.parametrize(
    "contenido,extension",
    [(PNG, "png"), (JPG, "jpg"), (GIF, "gif"), (WEBP, "webp")],
)
def test_acepta_los_formatos_de_imagen(db, autor, producto, contenido, extension):
    foto = servicio.subir_foto(db, autor, producto.id, contenido)
    assert foto.url.endswith(f".{extension}")


def test_rechaza_lo_que_no_es_imagen(db, autor, producto):
    """
    El caso que importa: un archivo con nombre de imagen pero contenido de
    otra cosa. La validación mira los bytes, no la extensión.
    """
    with pytest.raises(ReglaDeNegocio, match="no es una imagen válida"):
        servicio.subir_foto(db, autor, producto.id, b"#!/bin/sh\nrm -rf /\n")


def test_rechaza_un_archivo_vacio(db, autor, producto):
    with pytest.raises(ReglaDeNegocio, match="vacío"):
        servicio.subir_foto(db, autor, producto.id, b"")


def test_rechaza_una_imagen_demasiado_grande(db, autor, producto):
    gigante = PNG + b"\x00" * (servicio.TAMANO_MAXIMO + 1)
    with pytest.raises(ReglaDeNegocio, match="supera el máximo"):
        servicio.subir_foto(db, autor, producto.id, gigante)


def test_una_subida_rechazada_no_deja_archivos_en_disco(db, autor, producto):
    """Las validaciones corren ANTES de escribir: no queda basura."""
    antes = len(list(servicio._DIRECTORIO.iterdir())) if servicio._DIRECTORIO.exists() else 0

    with pytest.raises(ReglaDeNegocio):
        servicio.subir_foto(db, autor, producto.id, b"no soy una imagen")

    despues = len(list(servicio._DIRECTORIO.iterdir())) if servicio._DIRECTORIO.exists() else 0
    assert despues == antes


def test_el_nombre_del_archivo_lo_elige_el_sistema(db, autor, producto):
    """
    El nombre del cliente nunca se usa: podría traer '../' para escapar del
    directorio, o repetirse y pisar otra foto. El nombre sale del SKU más
    un identificador aleatorio.
    """
    a = servicio.subir_foto(db, autor, producto.id, PNG)
    b = servicio.subir_foto(db, autor, producto.id, PNG)

    assert a.url != b.url, "dos subidas iguales no pueden pisarse"
    for foto in (a, b):
        assert foto.url.startswith(f"/static/productos/{producto.sku}_")
        assert ".." not in foto.url


def test_el_tope_es_de_cinco_fotos(db, autor, producto):
    for _ in range(MAX_FOTOS_POR_PRODUCTO):
        servicio.subir_foto(db, autor, producto.id, PNG)

    with pytest.raises(ReglaDeNegocio, match="ya tiene 5 fotos"):
        servicio.subir_foto(db, autor, producto.id, PNG)


def test_un_producto_inexistente_da_404(db, autor):
    with pytest.raises(NoEncontrado):
        servicio.subir_foto(db, autor, 999999, PNG)


# ============================================================================
# PRINCIPAL
# ============================================================================


def test_la_primera_foto_queda_principal(db, autor, producto):
    """Un producto con fotos y ninguna principal no tendría qué mostrar."""
    foto = servicio.subir_foto(db, autor, producto.id, PNG)
    assert foto.es_principal is True


def test_las_siguientes_no_son_principales(db, autor, producto):
    servicio.subir_foto(db, autor, producto.id, PNG)
    segunda = servicio.subir_foto(db, autor, producto.id, PNG)
    assert segunda.es_principal is False


def test_marcar_una_desmarca_la_anterior(db, autor, producto):
    primera = servicio.subir_foto(db, autor, producto.id, PNG)
    segunda = servicio.subir_foto(db, autor, producto.id, PNG)

    servicio.marcar_principal(db, autor, segunda.id)

    assert segunda.es_principal is True
    assert primera.es_principal is False


def test_nunca_hay_dos_principales(db, autor, producto):
    """
    Lo garantiza un índice único parcial en la base, además del service:
    si el desmarcado fallara, el INSERT/UPDATE sería rechazado.
    """
    from sqlalchemy import func, select

    fotos = [servicio.subir_foto(db, autor, producto.id, PNG) for _ in range(3)]
    for f in fotos:
        servicio.marcar_principal(db, autor, f.id)

    principales = db.execute(
        select(func.count(ProductoFoto.id)).where(
            ProductoFoto.producto_id == producto.id,
            ProductoFoto.es_principal.is_(True),
        )
    ).scalar_one()
    assert principales == 1


def test_el_indice_parcial_permite_varias_secundarias(db, autor, producto):
    """
    El índice es parcial a propósito: si no lo fuera, un producto no podría
    tener dos fotos comunes (las dos con es_principal = false).
    """
    fotos = [servicio.subir_foto(db, autor, producto.id, PNG) for _ in range(4)]
    assert sum(1 for f in fotos if not f.es_principal) == 3


# ============================================================================
# BORRADO
# ============================================================================


def test_borrar_elimina_la_fila_y_el_archivo(db, autor, producto):
    foto = servicio.subir_foto(db, autor, producto.id, PNG)
    ruta = servicio._DIRECTORIO / Path(foto.url).name
    assert ruta.exists()

    servicio.eliminar_foto(db, autor, foto.id)

    assert not ruta.exists()
    with pytest.raises(NoEncontrado):
        servicio.obtener_foto(db, foto.id)


def test_borrar_la_principal_promueve_la_siguiente(db, autor, producto):
    """El producto no puede quedar con fotos y ninguna principal."""
    primera = servicio.subir_foto(db, autor, producto.id, PNG)
    segunda = servicio.subir_foto(db, autor, producto.id, PNG)

    servicio.eliminar_foto(db, autor, primera.id)

    db.refresh(segunda)
    assert segunda.es_principal is True


def test_borrar_la_ultima_no_falla(db, autor, producto):
    foto = servicio.subir_foto(db, autor, producto.id, PNG)
    servicio.eliminar_foto(db, autor, foto.id)
    assert producto.fotos == []


# ============================================================================
# API
# ============================================================================


def test_la_subida_por_la_api(client, db, autor, producto, login):
    db.commit()
    resp = client.post(
        f"/api/v1/productos/{producto.id}/fotos",
        files={"archivo": ("foto.png", io.BytesIO(PNG), "image/png")},
        headers=login("admin"),
    )

    assert resp.status_code == 201
    cuerpo = resp.json()
    assert cuerpo["es_principal"] is True
    assert cuerpo["url"].startswith("/static/productos/")


def test_la_api_ignora_el_content_type_mentiroso(client, db, autor, producto, login):
    """
    Un script disfrazado de PNG: el cliente dice image/png y le pone .png,
    pero los bytes lo delatan.
    """
    db.commit()
    resp = client.post(
        f"/api/v1/productos/{producto.id}/fotos",
        files={"archivo": ("inocente.png", io.BytesIO(b"<?php echo 1; ?>"), "image/png")},
        headers=login("admin"),
    )

    assert resp.status_code == 409
    assert "no es una imagen" in resp.json()["detail"]


def test_las_fotos_viajan_en_la_respuesta_del_producto(client, db, autor, producto, login):
    servicio.subir_foto(db, autor, producto.id, PNG)
    db.commit()

    resp = client.get(f"/api/v1/productos/{producto.id}", headers=login("admin"))

    assert resp.status_code == 200
    fotos = resp.json()["fotos"]
    assert len(fotos) == 1
    assert set(fotos[0]) == {"id", "url", "es_principal", "orden"}


def test_sin_permiso_de_editar_no_se_suben_fotos(client, db, crear_usuario, producto, login):
    crear_usuario("juan", ROL_VENDEDOR)
    db.commit()

    resp = client.post(
        f"/api/v1/productos/{producto.id}/fotos",
        files={"archivo": ("foto.png", io.BytesIO(PNG), "image/png")},
        headers=login("juan"),
    )
    assert resp.status_code == 403


def test_los_tests_no_escriben_en_el_directorio_real(directorio_temporal):
    """
    Regresión: el fixture original vaciaba el directorio real de fotos al
    terminar cada test, y correr la suite borraba fotos de usuarios.
    """
    real = Path(__file__).parent.parent / "app" / "static" / "productos"
    assert servicio._DIRECTORIO != real
    assert servicio._DIRECTORIO == directorio_temporal
