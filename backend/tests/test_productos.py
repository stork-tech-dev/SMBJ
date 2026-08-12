"""
Tests de productos y variantes.

El foco está en el precio de venta: es un campo desnormalizado que se
deriva de `precio_usd` y del dólar del proveedor, así que lo que hay que
probar es que ningún camino lo deje desactualizado.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.permisos import ROL_CUENTA_MAESTRA, ROL_VENDEDOR
from app.models.configuracion import ConfiguracionSistema
from app.models.producto import Temporada
from app.models.proveedor import EstadoProveedor
from app.schemas.productos import ProductoCrear
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
            descripcion="Producto de prueba",
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
            "precio_usd": "10", "sku": "ZZ999", "descripcion": "Producto de prueba",
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
        descripcion="Producto de prueba",
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
        descripcion="Producto de prueba",
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
        descripcion="Producto de prueba",
)
    ajeno = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=otro.id,
        precio_usd=Decimal("10"),
        descripcion="Producto de prueba",
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
    variante = servicio.agregar_variante(db, autor, producto.id, sufijo="R", descripcion_sufijo="Color R")
    assert variante.codigo_completo == f"S{producto.sku}R"
    assert variante.es_base is False


def test_la_primera_variante_real_reemplaza_la_base(db, autor, producto):
    servicio.agregar_variante(db, autor, producto.id, sufijo="R", descripcion_sufijo="Color R")

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
        servicio.agregar_variante(db, autor, producto.id, sufijo="R", descripcion_sufijo="Color R")


def test_no_hay_dos_variantes_con_el_mismo_sufijo(db, autor, producto):
    servicio.agregar_variante(db, autor, producto.id, sufijo="R", descripcion_sufijo="Color R")
    with pytest.raises(ReglaDeNegocio, match="Ya existe una variante"):
        servicio.agregar_variante(db, autor, producto.id, sufijo="R", descripcion_sufijo="Color R")


def test_la_variante_guarda_ubicacion_y_stock_minimo(db, autor, producto):
    """
    Los dos campos existen en `VarianteCrear` desde siempre, pero la pantalla
    los perdía: el alta se hacía con un `window.prompt()` que solo mandaba el
    sufijo, así que entraban en NULL y 0 sin que nadie lo notara. Ahora que hay
    formulario, este test cuida que lleguen hasta la base.
    """
    variante = servicio.agregar_variante(
        db, autor, producto.id, sufijo="R", descripcion_sufijo="Color R",
        ubicacion_deposito="Estante 3 - Fila B", stock_minimo=7,
    )

    db.refresh(variante)
    assert variante.ubicacion_deposito == "Estante 3 - Fila B"
    assert variante.stock_minimo == 7


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
            descripcion="Producto de prueba",
        )


def test_el_descuento_dentro_del_tope_se_acepta(db, autor, config, categoria, proveedor):
    p = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descuento_producto=Decimal("25"),
        descripcion="Producto de prueba",
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
            descripcion="Producto de prueba",
        )


def test_la_categoria_debe_existir(db, autor, config, proveedor):
    with pytest.raises(ReglaDeNegocio, match="categoría no existe"):
        servicio.crear_producto(
            db, autor, categoria_id=999999, proveedor_id=proveedor.id,
            precio_usd=Decimal("10"),
            descripcion="Producto de prueba",
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
        json={"categoria_id": categoria.id, "proveedor_id": proveedor.id,
              "precio_usd": "10", "descripcion": "Producto de prueba"},
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
            "precio_usd": "10.001", "descripcion": "Producto de prueba",
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


# ============================================================================
# LISTADO A NIVEL VARIANTE
# ============================================================================


@pytest.fixture
def catalogo(db, autor, config, categoria, proveedor):
    """
    Dos productos: uno sin variantes (solo su BASE) y otro dividido en tres.
    Son 4 filas de listado en total.
    """
    liso = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="Zapatilla lisa",
    )
    luces = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("20"), descripcion="Zapatilla con luces",
    )
    for sufijo in ("R", "N", "V"):
        servicio.agregar_variante(db, autor, luces.id, sufijo=sufijo, descripcion_sufijo=f"Color {sufijo}")
    db.flush()
    return liso, luces


def test_un_producto_con_variantes_ocupa_una_fila_por_cada_una(db, catalogo):
    """
    Es el punto del cambio: la fila es la unidad que tiene stock y etiqueta,
    no el producto. Dos productos —uno con BASE y otro con tres variantes—
    son cuatro filas, no dos.
    """
    filas, total = servicio.listar_variantes(db)

    assert total == 4
    assert len(filas) == 4


def test_buscar_por_el_codigo_de_la_etiqueta_trae_una_sola_fila(db, catalogo):
    """
    El caso del lector: entrega el código CON dígito verificador, y la
    columna guarda el cuerpo sin él. Tiene que resolver a una única fila,
    porque es lo que permite descontar stock sin preguntar nada más.
    """
    _, luces = catalogo
    objetivo = next(v for v in luces.variantes if v.sufijo == "R")

    filas, total = servicio.listar_variantes(db, busqueda=objetivo.codigo_con_verificador)

    assert total == 1
    assert filas[0].id == objetivo.id


def test_buscar_el_codigo_sin_el_digito_verificador_tambien_funciona(db, catalogo):
    """Quien lo tipea mirando la pantalla puede omitir el último carácter."""
    _, luces = catalogo
    objetivo = next(v for v in luces.variantes if v.sufijo == "R")

    filas, total = servicio.listar_variantes(db, busqueda=objetivo.codigo_completo)

    assert total == 1
    assert filas[0].id == objetivo.id


def test_un_codigo_con_el_digito_equivocado_no_cae_en_otra_variante(db, catalogo):
    """
    Esto es PARA LO QUE EXISTE el dígito verificador. Un carácter mal
    tipeado no puede resolver por accidente a otro artículo: sería
    descontarle stock al equivocado sin que nadie se entere.
    """
    _, luces = catalogo
    objetivo = next(v for v in luces.variantes if v.sufijo == "R")
    otro = "0" if objetivo.verificador != "0" else "1"

    filas, total = servicio.listar_variantes(db, busqueda=objetivo.codigo_completo + otro)

    assert total == 0, [f.codigo_completo for f in filas]


def test_buscar_por_sku_trae_todas_las_variantes_del_producto(db, catalogo):
    """El SKU identifica al producto, así que trae sus tres filas."""
    _, luces = catalogo

    filas, total = servicio.listar_variantes(db, busqueda=luces.sku)

    assert total == 3
    assert {f.sufijo for f in filas} == {"R", "N", "V"}


def test_buscar_por_descripcion_sigue_funcionando(db, catalogo):
    filas, total = servicio.listar_variantes(db, busqueda="luces")

    assert total == 3
    assert all(f.producto.descripcion == "Zapatilla con luces" for f in filas)


def test_el_paginado_cuenta_variantes_y_no_productos(db, catalogo):
    """
    `total` es lo que la pantalla muestra como "N códigos encontrados": si
    contara productos, el número no coincidiría con las filas visibles.
    """
    _, luces = catalogo

    filas, total = servicio.listar_variantes(db, busqueda=luces.sku, tamano=2)

    assert total == 3
    assert len(filas) == 2


def test_el_listado_de_variantes_por_la_api(client, db, catalogo, login):
    """La fila trae lo que la tabla necesita sin pedir el producto aparte."""
    db.commit()

    resp = client.get("/api/v1/productos/variantes", headers=login("admin"))

    assert resp.status_code == 200
    datos = resp.json()
    assert datos["total"] == 4

    fila = datos["resultados"][0]
    assert {"codigo_completo", "verificador", "stock_actual", "producto"} <= set(fila)
    # El producto va resumido: sin `variantes` ni `fotos`, que en una fila
    # que YA es una variante solo agregarían peso.
    assert "variantes" not in fila["producto"]
    assert "fotos" not in fila["producto"]


def test_el_listado_va_alfabetico_por_descripcion(db, autor, config, categoria, proveedor):
    """
    La tabla se lee por la columna Descripción, así que ese es el orden.

    Los dos casos que lo pueden romper:
      - Mayúsculas: "alfajor" tiene que ir antes que "Alpargata", no después.
        Sin `lower()` el orden depende de la mayúscula inicial.
      - Variantes hermanas: comparten descripción, y sin un desempate
        quedarían en orden arbitrario — con paginado eso repite o saltea filas.

    Se usan nombres sin acentos ni ñ a propósito. Dónde va la "ñ" lo decide
    la colación de PostgreSQL —después de la n, como corresponde en
    castellano— y no este código; compararlo contra el `sorted()` de Python,
    que ordena por punto de código y la manda al final de todo, probaría una
    diferencia entre dos algoritmos ajenos en vez de nuestro ORDER BY.

    Las minúsculas se fuerzan sobre el modelo porque `crear_producto` ahora
    capitaliza la inicial. Es el estado real de las filas creadas antes de la
    migración 0015 y de cualquier escritura que no pase por el servicio: el
    `lower()` del ORDER BY las tiene que seguir ordenando bien.
    """
    for nombre in ["zapato", "Alpargata", "alfajor", "Mocasin"]:
        creado = servicio.crear_producto(
            db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
            precio_usd=Decimal("10"), descripcion=nombre,
        )
        creado.descripcion = nombre
    multi = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="Mocasín",
    )
    for sufijo in ("V", "R", "N"):
        servicio.agregar_variante(db, autor, multi.id, sufijo=sufijo, descripcion_sufijo=f"Color {sufijo}")
    db.flush()

    filas, _ = servicio.listar_variantes(db)
    visible = [f.producto.descripcion for f in filas]

    # Lo que se ve en la columna, ordenado sin distinguir mayúsculas.
    assert visible == sorted(visible, key=str.lower)

    # Y "alfajor" antes que "Alpargata": es el caso que delata la falta de lower().
    assert visible.index("alfajor") < visible.index("Alpargata")

    # Las tres hermanas quedan juntas y en orden estable por su código.
    codigos = [f.codigo_completo for f in filas if f.producto_id == multi.id]
    assert codigos == sorted(codigos)


def test_la_descripcion_es_obligatoria(db, autor, config, categoria, proveedor):
    """
    Sin descripción la fila solo se identifica por su SKU, que no dice qué
    es. Y es la columna por la que se ordena el catálogo.
    """
    with pytest.raises(ReglaDeNegocio, match="descripción"):
        servicio.crear_producto(
            db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
            precio_usd=Decimal("10"), descripcion="   ",
        )


def test_no_se_puede_dejar_sin_descripcion_al_editar(db, autor, producto):
    """
    La edición es parcial —no mandarla es "no la cambies"— pero mandarla
    vacía dejaría el producto sin identificación.
    """
    with pytest.raises(ReglaDeNegocio, match="descripción"):
        servicio.editar_producto(db, autor, producto.id, descripcion="  ")

    db.refresh(producto)
    assert producto.descripcion == "Zapatilla running"


# ============================================================================
# CAPITALIZACIÓN DE LA DESCRIPCIÓN
# ============================================================================


def test_la_descripcion_se_guarda_con_la_inicial_en_mayuscula(
    db, autor, config, categoria, proveedor
):
    """
    Se normaliza al GUARDAR y no al mostrar, así queda igual en el listado,
    en la ficha, en la edición y en cualquier pantalla que se agregue después,
    sin que ninguna tenga que acordarse de formatearla.
    """
    creado = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="anillo de plata",
    )

    assert creado.descripcion == "Anillo de plata"


def test_la_capitalizacion_no_toca_el_resto_del_texto(
    db, autor, config, categoria, proveedor
):
    """
    El error fácil acá es usar `.capitalize()` o `.title()`, que bajan todo
    lo que sigue: "PLATA" y "18K" son parte del dato y tienen que sobrevivir.
    """
    creado = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="anillo de PLATA 18K",
    )

    assert creado.descripcion == "Anillo de PLATA 18K"


def test_una_descripcion_que_arranca_con_numero_queda_igual(
    db, autor, config, categoria, proveedor
):
    """`upper()` sobre un dígito no hace nada: no hay nada que romper."""
    creado = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="925 plata cadena",
    )

    assert creado.descripcion == "925 plata cadena"


def test_la_edicion_tambien_capitaliza(db, autor, producto):
    """
    Si solo lo hiciera el alta, la primera edición desharía en un producto lo
    que la migración 0015 arregló en todos.
    """
    servicio.editar_producto(db, autor, producto.id, descripcion="zapatilla nueva")

    db.refresh(producto)
    assert producto.descripcion == "Zapatilla nueva"


def test_capitalizar_no_rompe_la_busqueda_en_minuscula(
    db, autor, config, categoria, proveedor
):
    """
    Se busca tipeando en minúscula. El filtro usa `ilike`, así que la
    mayúscula guardada no lo puede afectar — pero es lo primero que notaría
    un vendedor si se rompiera.
    """
    servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="anillo de plata",
    )
    db.flush()

    filas, total = servicio.listar_variantes(db, busqueda="anillo")

    assert total == 1
    assert filas[0].producto.descripcion == "Anillo de plata"


def test_existe_el_indice_del_orden_alfabetico(db):
    """
    El listado ordena por `lower(descripcion)`. Con varios miles de
    productos, sin un índice sobre esa MISMA expresión cada página obliga a
    ordenar el catálogo entero para quedarse con 50 filas.

    Se comprueba contra la base y no contra el archivo de migración: lo que
    importa es que el índice exista donde se consulta.
    """
    from sqlalchemy import text

    fila = db.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"),
        {"n": "ix_productos_descripcion_lower"},
    ).scalar_one_or_none()

    assert fila is not None, "falta el índice del orden alfabético"
    assert "lower(descripcion)" in fila.lower()


# ============================================================================
# NOMBRE DE LA VARIANTE
# ============================================================================


def test_el_nombre_de_la_variante_es_obligatorio(db, autor, producto):
    """
    Es lo que reemplaza al "variante R" que no dice nada: dejarlo vacío
    anula el propósito.
    """
    with pytest.raises(ReglaDeNegocio, match="nombre de la variante"):
        servicio.agregar_variante(
            db, autor, producto.id, sufijo="R", descripcion_sufijo="   "
        )


def test_la_base_no_lleva_nombre_de_variante(db, producto):
    """La BASE no es variante de nada, así que no tiene qué nombrar."""
    base = producto.variantes[0]
    assert base.es_base is True
    assert base.descripcion_sufijo is None


def test_no_se_le_puede_poner_nombre_a_la_base(db, autor, producto):
    base = producto.variantes[0]

    with pytest.raises(ReglaDeNegocio, match="BASE"):
        servicio.editar_variante(db, autor, base.id, descripcion_sufijo="Rojo")


def test_editar_una_variante_cambia_lo_editable(db, autor, producto):
    variante = servicio.agregar_variante(
        db, autor, producto.id, sufijo="R", descripcion_sufijo="Color R"
    )

    servicio.editar_variante(
        db, autor, variante.id,
        descripcion_sufijo="Rojo furioso",
        ubicacion_deposito="Estante 3",
        stock_minimo=7,
    )

    db.refresh(variante)
    assert variante.descripcion_sufijo == "Rojo furioso"
    assert variante.ubicacion_deposito == "Estante 3"
    assert variante.stock_minimo == 7


def test_editar_una_variante_no_toca_su_codigo(db, autor, producto):
    """
    El código se congela al crearse: la etiqueta ya está impresa y pegada a
    la mercadería. Cambiarlo dejaría sin producto a lo que hay en depósito.
    """
    variante = servicio.agregar_variante(
        db, autor, producto.id, sufijo="R", descripcion_sufijo="Color R"
    )
    codigo, verificador = variante.codigo_completo, variante.verificador

    servicio.editar_variante(db, autor, variante.id, descripcion_sufijo="Rojo")

    db.refresh(variante)
    assert variante.codigo_completo == codigo
    assert variante.verificador == verificador
    assert variante.sufijo == "R"


def test_editar_una_variante_queda_auditado(db, autor, producto):
    from app.models.auditoria import Auditoria
    from sqlalchemy import select as sa_select

    variante = servicio.agregar_variante(
        db, autor, producto.id, sufijo="R", descripcion_sufijo="Color R"
    )
    servicio.editar_variante(db, autor, variante.id, descripcion_sufijo="Rojo")

    acciones = db.execute(
        sa_select(Auditoria.accion).where(Auditoria.entidad == "variantes")
    ).scalars().all()
    assert "variante.editar" in acciones


def test_el_listado_devuelve_el_nombre_de_la_variante(db, autor, producto):
    servicio.agregar_variante(
        db, autor, producto.id, sufijo="R", descripcion_sufijo="Rojo"
    )

    filas, _ = servicio.listar_variantes(db)

    assert [f.descripcion_sufijo for f in filas] == ["Rojo"]


# ============================================================================
# PRECIO PROPIO POR VARIANTE
# ============================================================================


@pytest.fixture
def variante_con_precio(db, autor, producto):
    """Una variante con precio propio (7 USD) sobre un producto de 10 USD."""
    v = servicio.agregar_variante(
        db, autor, producto.id, sufijo="R", descripcion_sufijo="Rojo"
    )
    servicio.editar_variante(db, autor, v.id, precio_usd=Decimal("7"), editar_precio=True)
    db.flush()
    return v


def test_el_precio_propio_manda_sobre_el_del_producto(db, producto, variante_con_precio):
    """El dólar del proveedor es 1.000: 7 USD → 7.000."""
    assert producto.precio_usd == Decimal("10")
    assert variante_con_precio.precio_usd == Decimal("7")
    assert variante_con_precio.precio_venta == Decimal("7000")
    assert variante_con_precio.precio_usd_efectivo == Decimal("7")
    assert variante_con_precio.tiene_precio_propio is True


def test_una_variante_sin_precio_propio_usa_el_del_producto(db, autor, producto):
    v = servicio.agregar_variante(
        db, autor, producto.id, sufijo="N", descripcion_sufijo="Negro"
    )

    assert v.precio_usd is None
    assert v.tiene_precio_propio is False
    assert v.precio_usd_efectivo == producto.precio_usd
    assert v.precio_venta_efectivo == producto.precio_venta


def test_cambiar_el_precio_del_producto_no_pisa_el_de_la_variante(
    db, autor, producto, variante_con_precio
):
    """Eso es lo que significa "prevalencia"."""
    servicio.editar_producto(db, autor, producto.id, precio_usd=Decimal("20"))

    db.refresh(variante_con_precio)
    assert variante_con_precio.precio_usd == Decimal("7")
    assert variante_con_precio.precio_venta == Decimal("7000")


def test_limpiar_el_precio_devuelve_la_variante_al_del_producto(
    db, autor, producto, variante_con_precio
):
    servicio.editar_variante(db, autor, variante_con_precio.id, editar_precio=True)

    db.refresh(variante_con_precio)
    assert variante_con_precio.precio_usd is None
    assert variante_con_precio.precio_venta is None
    assert variante_con_precio.precio_venta_efectivo == producto.precio_venta


# --- LA CASCADA: lo más fácil de romper ------------------------------------


def test_el_cambio_individual_de_dolar_recalcula_el_precio_propio(
    db, autor, proveedor, variante_con_precio
):
    """
    Una variante con precio propio NO deriva del producto, así que si la
    cascada solo tocara productos, su precio en pesos quedaría congelado al
    dólar viejo y se desfasaría en silencio.
    """
    servicio_proveedores.cambiar_dolar(db, autor, proveedor.id, Decimal("2000"))

    db.refresh(variante_con_precio)
    assert variante_con_precio.precio_venta == Decimal("14000")


def test_el_cambio_masivo_por_valor_recalcula_el_precio_propio(
    db, autor, proveedor, variante_con_precio
):
    servicio_proveedores.cambio_masivo(
        db, autor, proveedor_ids=None, modalidad="valor", valor=Decimal("3000")
    )

    db.refresh(variante_con_precio)
    assert variante_con_precio.precio_venta == Decimal("21000")


def test_el_cambio_masivo_por_porcentaje_recalcula_el_precio_propio(
    db, autor, proveedor, variante_con_precio
):
    servicio_proveedores.cambio_masivo(
        db, autor, proveedor_ids=None, modalidad="porcentaje", valor=Decimal("100")
    )

    # 1000 + 100% = 2000 → 7 USD × 2000 = 14.000
    db.refresh(variante_con_precio)
    assert variante_con_precio.precio_venta == Decimal("14000")


def test_la_cascada_cuenta_productos_y_variantes(db, proveedor, variante_con_precio):
    """Un producto más una variante con precio propio: dos filas tocadas."""
    assert servicio.recalcular_precios_de_proveedor(db, proveedor.id) == 2


def test_el_filtro_de_precio_usa_el_efectivo(db, producto, variante_con_precio):
    """
    Filtrar por `Producto.precio_venta` dejaría afuera justamente a las
    variantes con precio propio, que son las que más motivo hay para buscar
    por precio.

    El producto vale 10.000 y la variante 7.000: un rango de 6.000 a 8.000
    tiene que encontrar la variante y no la BASE.
    """
    filas, total = servicio.listar_variantes(
        db, precio_desde=Decimal("6000"), precio_hasta=Decimal("8000")
    )

    assert total == 1
    assert filas[0].id == variante_con_precio.id


def test_no_se_puede_dejar_un_precio_en_pesos_sin_su_origen(db, variante_con_precio):
    """
    Lo impide un CHECK: un precio en pesos sin el USD del que sale es un
    número que nadie puede recalcular cuando cambie la cotización.
    """
    from sqlalchemy.exc import IntegrityError

    variante_con_precio.precio_usd = None
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# ============================================================================
# TEMPORADA
# ============================================================================


def test_el_producto_arranca_atemporal(db, producto):
    """
    La mayoría del catálogo de una bijouterie no es de temporada, así que el
    alta no tiene por qué obligar a elegir una. El default lo pone el modelo
    y también la columna (`server_default`): una fila insertada por fuera del
    service tampoco puede quedar sin temporada.
    """
    assert producto.temporada is Temporada.ATEMPORAL


def test_la_temporada_son_tres_y_no_las_cuatro_estaciones():
    """
    El rubro compra por temporada, no por estación: repone en Otoño-Invierno
    y en Primavera-Verano. Antes eran cinco valores sueltos, que obligaban a
    elegir entre dos que significan lo mismo —¿un buzo es de otoño o de
    invierno?— y a filtrar dos veces para ver una temporada entera.

    Las estaciones viejas ya no existen: las rechazan las dos puertas, el
    enum del modelo y el `pattern` del schema, así que ni el service ni la
    API las dejan entrar.
    """
    assert [t.value for t in Temporada] == [
        "atemporal", "otoño_invierno", "primavera_verano",
    ]

    for estacion_vieja in ("permanente", "verano", "invierno", "otoño", "primavera"):
        with pytest.raises(ValueError):
            Temporada(estacion_vieja)
        with pytest.raises(ValidationError):
            ProductoCrear(
                categoria_id=1, proveedor_id=1, precio_usd=Decimal("10"),
                descripcion="Producto de prueba", temporada=estacion_vieja,
            )


def test_el_filtro_por_temporada_no_mezcla(db, autor, config, categoria, proveedor):
    """
    Es el filtro del listado: elegir una temporada tiene que devolver solo
    esa, y no arrastrar lo atemporal por ser el valor por defecto.
    """
    de_invierno = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="Buzo de frisa",
        temporada="otoño_invierno",
    )
    servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="Anillo de plata",
    )

    filas, total = servicio.listar_productos(db, temporada="otoño_invierno")

    assert total == 1
    assert filas[0].id == de_invierno.id
