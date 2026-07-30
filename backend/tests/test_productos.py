"""
Tests de productos y variantes.

El foco está en el precio de venta: es un campo desnormalizado que se
deriva de `precio_usd` y del dólar del proveedor, así que lo que hay que
probar es que ningún camino lo deje desactualizado.
"""

from decimal import Decimal

import pytest

from app.core.permisos import ROL_CUENTA_MAESTRA, ROL_VENDEDOR
from app.models.configuracion import ConfiguracionSistema
from app.models.producto import Estacionalidad
from app.models.proveedor import EstadoProveedor
from app.services import categorias as servicio_categorias
from app.services import productos as servicio
from app.services import proveedores as servicio_proveedores
from app.services.roles import NoEncontrado, ReglaDeNegocio


@pytest.fixture
def autor(crear_usuario):
    return crear_usuario("admin", ROL_CUENTA_MAESTRA)


@pytest.fixture
def config(db, autor):
    """
    Configuración del sistema, con los MISMOS valores que produce el
    seed en una instalación nueva: los tests calculan sobre la misma
    base que el sistema real.
    """
    fila = ConfiguracionSistema(
        redondeo=Decimal("1000.00"),
        descuento_maximo=Decimal("30.00"),
        metodo_descuento="encadenado",
        letra_empresa="S",
        updated_by=autor.id,
    )
    db.add(fila)
    db.flush()
    return fila


@pytest.fixture
def categoria(db, autor):
    return servicio_categorias.crear_categoria(db, autor, nombre="Calzado")


@pytest.fixture
def proveedor(db, autor):
    return servicio_proveedores.crear_proveedor(
        db, autor, nombre="Distribuidora Norte", dolar_actual=Decimal("1000")
    )


@pytest.fixture
def producto(db, autor, config, categoria, proveedor):
    return servicio.crear_producto(
        db, autor,
        categoria_id=categoria.id,
        proveedor_id=proveedor.id,
        precio_usd=Decimal("10"),
        descripcion="Zapatilla running",
    )


# ============================================================================
# SKU
# ============================================================================


def test_el_sku_lo_genera_el_sistema(db, producto):
    assert len(producto.sku) == 5
    assert producto.sku[:2].isalpha() and producto.sku[2:].isdigit()


def test_los_sku_no_se_repiten(db, autor, config, categoria, proveedor):
    """La secuencia entrega un correlativo distinto a cada alta."""
    skus = {
        servicio.crear_producto(
            db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
            precio_usd=Decimal("10"),
        ).sku
        for _ in range(20)
    }
    assert len(skus) == 20


def test_el_sku_no_lo_puede_mandar_el_cliente(client, db, autor, config, categoria, proveedor, login):
    """
    Si `sku` estuviera en el schema, un cliente podría pisarlo y romper el
    correlativo de la secuencia.
    """
    db.commit()
    resp = client.post(
        "/api/v1/productos",
        json={
            "categoria_id": categoria.id, "proveedor_id": proveedor.id,
            "precio_usd": "10", "sku": "ZZ999",
        },
        headers=login("admin"),
    )
    assert resp.status_code == 201
    assert resp.json()["sku"] != "ZZ999"


# ============================================================================
# PRECIO DE VENTA
# ============================================================================


def test_el_precio_de_venta_sale_del_dolar_del_proveedor(db, producto):
    """10 USD × 1.000 = 10.000, que ya es múltiplo de 1.000: no se mueve."""
    assert producto.precio_venta == Decimal("10000.00")


def test_el_precio_redondea_hacia_arriba(db, autor, config, categoria, proveedor):
    """
    Es CEIL, no redondeo al más cercano: cualquier valor por encima del
    múltiplo salta al siguiente, sin importar por cuánto.

    Con el múltiplo de producción (1.000) el efecto es grande y conviene
    que quede a la vista: un peso de más sobre el múltiplo son mil pesos
    más en el precio de venta.
    """
    p = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10.001"),
    )
    # 10,001 × 1.000 = 10.001 → un peso arriba de 10.000, sube a 11.000.
    assert p.precio_venta == Decimal("11000")


def test_el_ejemplo_del_cliente(db, autor, config, categoria):
    """
    El caso que definió el valor del redondeo, tal como lo planteó el
    cliente: 5,33 USD con el dólar del proveedor a 1.400 se vende a 8.000.

    Queda como test para que un cambio en la fórmula o en la configuración
    del seed se note contra un número acordado, y no solo contra otros
    tests que se ajustarían junto con el código.
    """
    proveedor = servicio_proveedores.crear_proveedor(
        db, autor, nombre="Proveedor del ejemplo", dolar_actual=Decimal("1400")
    )

    p = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("5.33"),
    )

    # 5,33 × 1.400 = 7.462 → siguiente múltiplo de 1.000.
    assert p.precio_venta == Decimal("8000")


def test_cambiar_el_precio_usd_recalcula_el_de_venta(db, autor, producto):
    servicio.editar_producto(db, autor, producto.id, precio_usd=Decimal("20"))
    assert producto.precio_venta == Decimal("20000.00")


# ============================================================================
# LA CASCADA — lo más fácil de romper
# ============================================================================


def test_el_cambio_individual_de_dolar_actualiza_los_precios(db, autor, producto, proveedor):
    servicio_proveedores.cambiar_dolar(db, autor, proveedor.id, Decimal("1500"))
    assert producto.precio_venta == Decimal("15000.00")


def test_el_cambio_masivo_actualiza_los_precios(db, autor, producto, proveedor):
    """El masivo pasa por el mismo punto que el individual."""
    servicio_proveedores.cambio_masivo(
        db, autor, proveedor_ids=None, modalidad="valor", valor=Decimal("2000")
    )
    assert producto.precio_venta == Decimal("20000.00")


def test_el_cambio_masivo_por_porcentaje_actualiza_los_precios(db, autor, producto, proveedor):
    servicio_proveedores.cambio_masivo(
        db, autor, proveedor_ids=None, modalidad="porcentaje", valor=Decimal("10")
    )
    # 1000 + 10% = 1100 → 10 USD × 1100 = 11.000
    assert proveedor.dolar_actual == Decimal("1100.00")
    assert producto.precio_venta == Decimal("11000.00")


def test_la_cascada_solo_toca_los_productos_del_proveedor(db, autor, config, categoria, proveedor):
    """Cambiar el dólar de un proveedor no puede mover precios de otro."""
    otro = servicio_proveedores.crear_proveedor(
        db, autor, nombre="Mayorista Sur", dolar_actual=Decimal("1000")
    )
    mio = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"),
    )
    ajeno = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=otro.id,
        precio_usd=Decimal("10"),
    )

    servicio_proveedores.cambiar_dolar(db, autor, proveedor.id, Decimal("2000"))

    assert mio.precio_venta == Decimal("20000.00")
    assert ajeno.precio_venta == Decimal("10000.00")


def test_recalcular_devuelve_cuantos_toco(db, autor, producto, proveedor):
    assert servicio.recalcular_precios_de_proveedor(db, proveedor.id) == 1


def test_recalcular_un_proveedor_inexistente_no_falla(db):
    assert servicio.recalcular_precios_de_proveedor(db, 999999) == 0


# ============================================================================
# VARIANTES
# ============================================================================


def test_todo_producto_nace_con_una_variante_base(db, producto):
    assert len(producto.variantes) == 1
    base = producto.variantes[0]
    assert base.es_base is True
    assert base.sufijo is None
    assert producto.tiene_variantes is False


def test_el_codigo_de_la_base_es_letra_mas_sku(db, producto, config):
    base = producto.variantes[0]
    assert base.codigo_completo == f"S{producto.sku}"


def test_el_codigo_de_una_variante_incluye_el_sufijo(db, autor, producto, config):
    variante = servicio.agregar_variante(db, autor, producto.id, sufijo="R")
    assert variante.codigo_completo == f"S{producto.sku}R"
    assert variante.es_base is False


def test_la_primera_variante_real_reemplaza_la_base(db, autor, producto):
    servicio.agregar_variante(db, autor, producto.id, sufijo="R")

    db.refresh(producto)
    assert producto.tiene_variantes is True
    assert [v.sufijo for v in producto.variantes] == ["R"]
    assert not any(v.es_base for v in producto.variantes)


def test_no_se_divide_en_variantes_un_producto_con_stock(db, autor, producto):
    """
    El stock de la BASE quedaría huérfano al dividir el producto: no hay
    forma de saber a qué variante corresponde.
    """
    producto.variantes[0].stock_actual = 5
    db.flush()

    with pytest.raises(ReglaDeNegocio, match="stock cargado"):
        servicio.agregar_variante(db, autor, producto.id, sufijo="R")


def test_no_hay_dos_variantes_con_el_mismo_sufijo(db, autor, producto):
    servicio.agregar_variante(db, autor, producto.id, sufijo="R")
    with pytest.raises(ReglaDeNegocio, match="Ya existe una variante"):
        servicio.agregar_variante(db, autor, producto.id, sufijo="R")


def test_el_verificador_se_guarda_con_la_variante(db, producto):
    from app.core.codigos import digito_verificador

    base = producto.variantes[0]
    assert base.verificador == digito_verificador(base.codigo_completo)
    assert base.codigo_con_verificador == base.codigo_completo + base.verificador


# ============================================================================
# VALIDACIONES
# ============================================================================


def test_el_descuento_no_puede_superar_el_tope_configurado(db, autor, config, categoria, proveedor):
    """El tope vive en configuracion_sistema, no en el CHECK de la tabla."""
    with pytest.raises(ReglaDeNegocio, match="máximo configurado"):
        servicio.crear_producto(
            db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
            precio_usd=Decimal("10"), descuento_producto=Decimal("50"),
        )


def test_el_descuento_dentro_del_tope_se_acepta(db, autor, config, categoria, proveedor):
    p = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descuento_producto=Decimal("25"),
    )
    assert p.descuento_producto == Decimal("25")


def test_no_se_carga_un_producto_de_un_proveedor_inactivo(db, autor, config, categoria, proveedor):
    servicio_proveedores.cambiar_estado(
        db, autor, proveedor.id, nuevo_estado=EstadoProveedor.DESACTIVADO
    )

    with pytest.raises(ReglaDeNegocio, match="proveedor inactivo"):
        servicio.crear_producto(
            db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
            precio_usd=Decimal("10"),
        )


def test_la_categoria_debe_existir(db, autor, config, proveedor):
    with pytest.raises(ReglaDeNegocio, match="categoría no existe"):
        servicio.crear_producto(
            db, autor, categoria_id=999999, proveedor_id=proveedor.id,
            precio_usd=Decimal("10"),
        )


def test_no_se_elimina_una_categoria_con_productos(db, autor, producto, categoria):
    """La regla de la fase 1 que solo se puede probar ahora."""
    with pytest.raises(ReglaDeNegocio, match="productos asociados"):
        servicio_categorias.eliminar_categoria(db, autor, categoria.id)


def test_la_baja_es_logica(db, autor, producto):
    servicio.cambiar_estado_producto(db, autor, producto.id, activo=False)
    assert producto.activo is False
    # Sigue existiendo: queda referenciado en ventas y movimientos.
    assert servicio.obtener_producto(db, producto.id) is producto


# ============================================================================
# LISTADO
# ============================================================================


def test_el_listado_filtra_en_el_backend(db, autor, config, categoria, proveedor, producto):
    otra = servicio_categorias.crear_categoria(db, autor, nombre="Ropa")
    servicio.crear_producto(
        db, autor, categoria_id=otra.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("5"), descripcion="Remera",
    )

    por_categoria, total = servicio.listar_productos(db, categoria_id=categoria.id)
    assert total == 1
    assert por_categoria[0].descripcion == "Zapatilla running"

    por_texto, total = servicio.listar_productos(db, descripcion="reme")
    assert total == 1

    por_precio, total = servicio.listar_productos(db, precio_desde=Decimal("9000"))
    assert total == 1


# ============================================================================
# API
# ============================================================================


def test_el_alta_por_la_api_devuelve_la_variante_base(client, db, autor, config, categoria, proveedor, login):
    db.commit()
    resp = client.post(
        "/api/v1/productos",
        json={"categoria_id": categoria.id, "proveedor_id": proveedor.id, "precio_usd": "10"},
        headers=login("admin"),
    )

    assert resp.status_code == 201
    cuerpo = resp.json()
    assert len(cuerpo["variantes"]) == 1
    assert cuerpo["variantes"][0]["es_base"] is True
    assert cuerpo["precio_venta"] == "10000.00"


def test_la_respuesta_no_expone_el_dolar_del_proveedor(client, db, producto, login):
    """
    El listado de productos solo necesita identificar al proveedor. Su
    cotización es un dato del módulo de proveedores.
    """
    db.commit()
    resp = client.get("/api/v1/productos", headers=login("admin"))

    assert resp.status_code == 200
    proveedor = resp.json()["resultados"][0]["proveedor"]
    assert set(proveedor) == {"id", "nombre"}


def test_el_barcode_devuelve_un_svg(client, db, producto, login):
    db.commit()
    variante = producto.variantes[0]

    resp = client.get(f"/api/v1/productos/variantes/{variante.id}/barcode", headers=login("admin"))

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in resp.text


def test_sin_permiso_de_productos_no_se_listan(client, crear_usuario, login):
    crear_usuario("juan", ROL_VENDEDOR)
    resp = client.get("/api/v1/productos", headers=login("juan"))
    assert resp.status_code == 403


# ============================================================================
# VISTA PREVIA DEL PRECIO
# ============================================================================


def test_el_preview_devuelve_dolar_y_precio(client, db, autor, config, categoria, proveedor, login):
    db.commit()

    resp = client.get(
        f"/api/v1/productos/precio-preview?proveedor_id={proveedor.id}&precio_usd=10",
        headers=login("admin"),
    )

    assert resp.status_code == 200
    cuerpo = resp.json()
    assert Decimal(cuerpo["dolar_proveedor"]) == Decimal("1000")
    assert Decimal(cuerpo["precio_venta"]) == Decimal("10000")


def test_el_preview_coincide_con_lo_que_se_guarda(client, db, autor, config, categoria, proveedor, login):
    """
    La razón de ser del endpoint: si el frontend replicara la fórmula, la
    vista previa y el valor guardado podrían divergir.
    """
    db.commit()
    headers = login("admin")

    previo = client.get(
        f"/api/v1/productos/precio-preview?proveedor_id={proveedor.id}&precio_usd=10.001",
        headers=headers,
    ).json()

    creado = client.post(
        "/api/v1/productos",
        json={
            "categoria_id": categoria.id, "proveedor_id": proveedor.id,
            "precio_usd": "10.001",
        },
        headers=headers,
    ).json()

    assert Decimal(previo["precio_venta"]) == Decimal(creado["precio_venta"])


def test_el_preview_aplica_el_redondeo_configurado(client, db, autor, config, proveedor, login):
    """
    La vista previa pasa por el mismo CEIL que el alta: 10,001 × 1.000 son
    10.001, un peso arriba del múltiplo, así que sube a 11.000.
    """
    db.commit()

    resp = client.get(
        f"/api/v1/productos/precio-preview?proveedor_id={proveedor.id}&precio_usd=10.001",
        headers=login("admin"),
    )
    assert Decimal(resp.json()["precio_venta"]) == Decimal("11000")


def test_el_preview_no_se_confunde_con_un_id(client, db, autor, config, proveedor, login):
    """`/precio-preview` va antes que `/{producto_id}` en el router."""
    db.commit()
    resp = client.get(
        f"/api/v1/productos/precio-preview?proveedor_id={proveedor.id}&precio_usd=1",
        headers=login("admin"),
    )
    assert resp.status_code == 200


def test_el_preview_no_crea_nada(client, db, autor, config, proveedor, login):
    """Es informativo: consultarlo no puede dar de alta un producto."""
    from sqlalchemy import func, select

    from app.models.producto import Producto

    db.commit()
    antes = db.execute(select(func.count(Producto.id))).scalar_one()

    client.get(
        f"/api/v1/productos/precio-preview?proveedor_id={proveedor.id}&precio_usd=10",
        headers=login("admin"),
    )

    assert db.execute(select(func.count(Producto.id))).scalar_one() == antes


def test_el_preview_con_proveedor_inexistente_da_404(client, db, autor, config, login):
    db.commit()
    resp = client.get(
        "/api/v1/productos/precio-preview?proveedor_id=999999&precio_usd=10",
        headers=login("admin"),
    )
    assert resp.status_code == 404


def test_el_preview_rechaza_un_precio_no_positivo(client, db, autor, config, proveedor, login):
    db.commit()
    resp = client.get(
        f"/api/v1/productos/precio-preview?proveedor_id={proveedor.id}&precio_usd=0",
        headers=login("admin"),
    )
    assert resp.status_code == 422


# ============================================================================
# FILTRO POR CATEGORÍA: INCLUYE LA DESCENDENCIA
# ============================================================================


@pytest.fixture
def arbol(db, autor):
    """Calzado (N1) → Zapatillas (N2) → Deportivas (N3) y Urbanas (N3)."""
    calzado = servicio_categorias.crear_categoria(db, autor, nombre="Calzado")
    zapatillas = servicio_categorias.crear_categoria(
        db, autor, nombre="Zapatillas", parent_id=calzado.id
    )
    deportivas = servicio_categorias.crear_categoria(
        db, autor, nombre="Deportivas", parent_id=zapatillas.id
    )
    urbanas = servicio_categorias.crear_categoria(
        db, autor, nombre="Urbanas", parent_id=zapatillas.id
    )
    botas = servicio_categorias.crear_categoria(db, autor, nombre="Botas", parent_id=calzado.id)
    return calzado, zapatillas, deportivas, urbanas, botas


def test_filtrar_por_un_nodo_intermedio_trae_su_descendencia(
    db, autor, config, proveedor, arbol
):
    """
    El caso que motiva el cambio: los productos cuelgan de las hojas, así
    que un filtro exacto por "Zapatillas" no devolvía nada.
    """
    calzado, zapatillas, deportivas, urbanas, botas = arbol

    def producto(categoria, desc):
        return servicio.crear_producto(
            db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
            precio_usd=Decimal("10"), descripcion=desc,
        )

    producto(deportivas, "Running")
    producto(urbanas, "Urbana")
    producto(botas, "Bota")

    _, total = servicio.listar_productos(db, categoria_id=zapatillas.id)
    assert total == 2, "Zapatillas debe traer Deportivas y Urbanas"

    _, total = servicio.listar_productos(db, categoria_id=calzado.id)
    assert total == 3, "la raíz trae todo lo que cuelga de ella"


def test_filtrar_por_una_hoja_trae_solo_lo_suyo(db, autor, config, proveedor, arbol):
    _, _, deportivas, urbanas, _ = arbol

    servicio.crear_producto(
        db, autor, categoria_id=deportivas.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="Running",
    )
    servicio.crear_producto(
        db, autor, categoria_id=urbanas.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="Urbana",
    )

    filas, total = servicio.listar_productos(db, categoria_id=deportivas.id)
    assert total == 1
    assert filas[0].descripcion == "Running"


def test_el_filtro_no_se_lleva_ramas_hermanas(db, autor, config, proveedor, arbol):
    """Filtrar por Zapatillas no puede traer lo de Botas."""
    _, zapatillas, deportivas, _, botas = arbol

    servicio.crear_producto(
        db, autor, categoria_id=deportivas.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="Running",
    )
    servicio.crear_producto(
        db, autor, categoria_id=botas.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="Bota",
    )

    filas, _ = servicio.listar_productos(db, categoria_id=zapatillas.id)
    assert [p.descripcion for p in filas] == ["Running"]


def test_rama_de_ids_incluye_al_nodo_y_su_descendencia(db, arbol):
    from app.services.categorias import rama_de_ids

    calzado, zapatillas, deportivas, urbanas, botas = arbol

    assert set(rama_de_ids(db, zapatillas.id)) == {zapatillas.id, deportivas.id, urbanas.id}
    assert set(rama_de_ids(db, deportivas.id)) == {deportivas.id}
    assert set(rama_de_ids(db, calzado.id)) == {
        calzado.id, zapatillas.id, deportivas.id, urbanas.id, botas.id
    }


def test_rama_de_una_categoria_inexistente_no_trae_de_mas(db):
    """Un id inválido filtra por sí mismo y devuelve cero, no todo."""
    from app.services.categorias import rama_de_ids

    assert rama_de_ids(db, 999999) == [999999]


def test_el_filtro_por_rama_funciona_desde_la_api(client, db, autor, config, proveedor, arbol, login):
    _, zapatillas, deportivas, _, _ = arbol
    servicio.crear_producto(
        db, autor, categoria_id=deportivas.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="Running",
    )
    db.commit()

    resp = client.get(
        f"/api/v1/productos?categoria_id={zapatillas.id}", headers=login("admin")
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
