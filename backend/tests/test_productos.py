"""
Tests de productos y variantes.

El foco está en el precio de venta: es un campo desnormalizado que se
deriva de `precio_usd` y del dólar del proveedor, así que lo que hay que
probar es que ningún camino lo deje desactualizado.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.permisos import ROL_CUENTA_MAESTRA, ROL_VENDEDOR, Modulo
from app.models.configuracion import ConfiguracionSistema
from app.models.producto import Temporada, Variante
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
    # Cada uno con su descripción: dos productos del mismo proveedor y
    # categoría no pueden llamarse igual.
    skus = {
        servicio.crear_producto(
            db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
            precio_usd=Decimal("10"),
            descripcion=f"Producto de prueba {n}",
        ).sku
        for n in range(20)
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


def test_no_se_divide_en_variantes_un_producto_con_stock(db, autor, producto, punto_de_venta):
    """
    El stock de la BASE quedaría huérfano al dividir el producto: no hay
    forma de saber a qué variante corresponde.

    Desde la 0022 el stock está en `stock`, repartido por ubicación: la
    guarda tiene que mirar ahí, y con que UNA ubicación tenga mercadería
    alcanza para frenar la división.
    """
    from app.models.stock import Stock

    db.add(Stock(
        variante_id=producto.variantes[0].id,
        punto_de_venta_id=punto_de_venta.id,
        cantidad=5,
    ))
    db.flush()

    with pytest.raises(ReglaDeNegocio, match="stock cargado"):
        servicio.agregar_variante(db, autor, producto.id, sufijo="R", descripcion_sufijo="Color R")


def test_no_hay_dos_variantes_con_el_mismo_sufijo(db, autor, producto):
    servicio.agregar_variante(db, autor, producto.id, sufijo="R", descripcion_sufijo="Color R")
    with pytest.raises(ReglaDeNegocio, match="Ya existe una variante"):
        servicio.agregar_variante(db, autor, producto.id, sufijo="R", descripcion_sufijo="Color R")


def test_la_variante_guarda_su_ubicacion_en_el_deposito(db, autor, producto):
    """
    El campo existe en `VarianteCrear` desde siempre, pero la pantalla lo
    perdía: el alta se hacía con un `window.prompt()` que solo mandaba el
    sufijo, así que entraba en NULL sin que nadie lo notara. Ahora que hay
    formulario, este test cuida que llegue hasta la base.

    El stock mínimo ya no está acá: desde la 0022 es por ubicación
    (`stock.stock_minimo_cd` / `stock_minimo_local`), porque el mismo
    artículo necesita un colchón distinto en el CD que en un local.
    """
    variante = servicio.agregar_variante(
        db, autor, producto.id, sufijo="R", descripcion_sufijo="Color R",
        ubicacion_deposito="Estante 3 - Fila B",
    )

    db.refresh(variante)
    assert variante.ubicacion_deposito == "Estante 3 - Fila B"


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


def test_un_sku_que_el_validador_lee_como_codigo_igual_encuentra_el_producto(
    db, autor, config, categoria, proveedor
):
    """
    El SKU y el código de etiqueta comparten alfabeto, así que un SKU puede
    pasar la validación del dígito verificador por casualidad: le pasa a 18
    de cada 199 (`AA009`, `AA017`, `AA025`…).

    Cuando el código y el texto eran excluyentes, esos SKU se leían como
    etiqueta: se les sacaba el último carácter y se comparaba contra un
    código que no existe. Tipear `AA009` no devolvía NADA, y nada explicaba
    por qué — el de al lado, `AA010`, funcionaba bien.
    """
    from app.core.codigos import armar_codigo_completo, codigo_es_valido, digito_verificador

    p = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="Anillo de plata",
    )

    # El SKU sale de una secuencia, así que se fuerza uno de los que caen en
    # la trampa. El código de su BASE se rearma con los mismos helpers que
    # usa el servicio, para que la fila quede coherente y no fabricada.
    p.sku = "AA009"
    base = p.variantes[0]
    base.codigo_completo = armar_codigo_completo("S", p.sku, None)
    base.verificador = digito_verificador(base.codigo_completo)
    db.flush()

    assert codigo_es_valido("AA009"), "el SKU elegido ya no cae en la trampa"

    filas, total = servicio.listar_variantes(db, busqueda="AA009")

    assert total == 1, "el SKU tiene que encontrar su producto igual"
    assert filas[0].producto.sku == "AA009"


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
    assert {"codigo_completo", "verificador", "stock_total", "producto"} <= set(fila)
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
    # Sin acentos y distinta de las cuatro de arriba: dos productos del
    # mismo proveedor y categoría no pueden llamarse igual, y la
    # comparación que lo controla ignora las tildes ("Mocasin" y "Mocasín"
    # son el mismo nombre escrito de dos formas).
    multi = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="Sandalia",
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
# DESCRIPCIÓN ÚNICA POR CATEGORÍA Y PROVEEDOR
# ============================================================================


def _crear(db, autor, categoria, proveedor, descripcion):
    return servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion=descripcion,
    )


def test_no_se_repite_la_descripcion_en_el_mismo_proveedor_y_categoria(
    db, autor, config, categoria, proveedor
):
    """
    Mirando el catálogo serían la misma fila cargada dos veces: no queda
    ningún dato en pantalla para distinguirlas. Lo que corresponde cuando el
    artículo viene en colores o talles es una variante del que ya existe.
    """
    _crear(db, autor, categoria, proveedor, "Zapatilla running")

    with pytest.raises(ReglaDeNegocio, match="Ya existe un producto"):
        _crear(db, autor, categoria, proveedor, "Zapatilla running")


def test_el_choque_de_descripcion_nombra_el_producto_con_el_que_choca(
    db, autor, config, categoria, proveedor
):
    """
    Sin el SKU en el mensaje hay que salir a buscar cuál es el que ya
    estaba, y el formulario acaba de decir que no se puede guardar.
    """
    ya_estaba = _crear(db, autor, categoria, proveedor, "Zapatilla running")

    with pytest.raises(ReglaDeNegocio, match=ya_estaba.sku):
        _crear(db, autor, categoria, proveedor, "Zapatilla running")


def test_la_descripcion_repetida_se_detecta_sin_tildes_ni_mayusculas(
    db, autor, config, categoria, proveedor
):
    """
    "Camión rojo" y "camion ROJO" no se distinguen mirando la tabla: son el
    mismo duplicado escrito de dos formas.
    """
    _crear(db, autor, categoria, proveedor, "Camión rojo")

    with pytest.raises(ReglaDeNegocio, match="Ya existe un producto"):
        _crear(db, autor, categoria, proveedor, "camion ROJO")


def test_la_misma_descripcion_en_otra_categoria_se_permite(
    db, autor, config, proveedor, arbol
):
    """
    El choque es dentro del mismo par categoría/proveedor. Dos categorías
    distintas pueden tener cada una su "Clásico"; ahí lo que distingue es
    justamente dónde está colgado.
    """
    _, _, deportivas, urbanas, _ = arbol

    _crear(db, autor, deportivas, proveedor, "Modelo clásico")
    otro = _crear(db, autor, urbanas, proveedor, "Modelo clásico")

    assert otro.id


def test_la_misma_descripcion_en_otro_proveedor_se_permite(
    db, autor, config, categoria, proveedor
):
    """
    Dos proveedores pueden vender el mismo artículo, y cada uno tiene su
    precio en dólares y su cotización: son dos productos distintos.
    """
    otro_proveedor = servicio_proveedores.crear_proveedor(
        db, autor, nombre="Distribuidora Sur", dolar_actual=Decimal("1200")
    )

    _crear(db, autor, categoria, proveedor, "Zapatilla running")
    otro = _crear(db, autor, categoria, otro_proveedor, "Zapatilla running")

    assert otro.id


def test_la_categoria_del_choque_es_exacta_y_no_la_rama(
    db, autor, config, proveedor, arbol
):
    """
    A diferencia del FILTRO del listado, que sí incluye la descendencia: dos
    productos iguales en categorías padre e hija son un problema de
    clasificación, no una fila duplicada. El índice único de la base compara
    `categoria_id` a secas, así que el service tiene que hacer lo mismo o
    rechazaría cosas que la base acepta.
    """
    _, zapatillas, deportivas, _, _ = arbol

    _crear(db, autor, zapatillas, proveedor, "Modelo clásico")
    otro = _crear(db, autor, deportivas, proveedor, "Modelo clásico")

    assert otro.id


def test_un_producto_inactivo_sigue_ocupando_su_descripcion(
    db, autor, config, categoria, proveedor
):
    """
    La baja es lógica: el producto no se borra y se puede volver a activar.
    Si mientras tanto se reusara el nombre, al reactivarlo quedarían las dos
    filas idénticas.
    """
    viejo = _crear(db, autor, categoria, proveedor, "Zapatilla running")
    servicio.cambiar_estado_producto(db, autor, viejo.id, activo=False)

    with pytest.raises(ReglaDeNegocio, match="inactivo"):
        _crear(db, autor, categoria, proveedor, "Zapatilla running")


def test_editar_un_producto_no_choca_consigo_mismo(db, autor, producto):
    """
    Guardar el formulario sin tocar la descripción manda la misma que ya
    tiene: si se comparara contra todo el catálogo sin excluirse, ninguna
    edición se podría guardar.
    """
    servicio.editar_producto(db, autor, producto.id, descripcion="Zapatilla running")

    db.refresh(producto)
    assert producto.descripcion == "Zapatilla running"


def test_renombrar_a_una_descripcion_ya_usada_se_rechaza(
    db, autor, config, categoria, proveedor, producto
):
    """La edición no puede colarse por donde el alta no deja pasar."""
    otro = _crear(db, autor, categoria, proveedor, "Zapatilla urbana")

    with pytest.raises(ReglaDeNegocio, match="Ya existe un producto"):
        servicio.editar_producto(db, autor, otro.id, descripcion="Zapatilla running")

    db.refresh(otro)
    assert otro.descripcion == "Zapatilla urbana"


def test_mover_de_categoria_hasta_chocar_se_rechaza(db, autor, config, proveedor, arbol):
    """
    El choque puede aparecer sin tocar la descripción: alcanza con mover el
    producto a la categoría donde ya hay uno que se llama igual. Por eso la
    validación mira cómo va a quedar y no cómo está.
    """
    _, _, deportivas, urbanas, _ = arbol

    _crear(db, autor, deportivas, proveedor, "Modelo clásico")
    mudo = _crear(db, autor, urbanas, proveedor, "Modelo clásico")

    with pytest.raises(ReglaDeNegocio, match="Ya existe un producto"):
        servicio.editar_producto(db, autor, mudo.id, categoria_id=deportivas.id)

    db.refresh(mudo)
    assert mudo.categoria_id == urbanas.id


def test_el_alta_duplicada_por_la_api_devuelve_409(
    client, db, autor, config, categoria, proveedor, login
):
    """
    El formulario muestra el `detail` tal cual en un toast: tiene que decir
    qué pasó, no un error de integridad de Postgres.
    """
    headers = login("admin")
    cuerpo = {
        "categoria_id": categoria.id,
        "proveedor_id": proveedor.id,
        "precio_usd": "10",
        "descripcion": "Zapatilla running",
    }

    assert client.post("/api/v1/productos", json=cuerpo, headers=headers).status_code == 201

    resp = client.post("/api/v1/productos", json=cuerpo, headers=headers)
    assert resp.status_code == 409
    assert "Ya existe un producto" in resp.json()["detail"]


def test_la_base_tambien_impide_el_duplicado(db, autor, config, categoria, proveedor):
    """
    El índice único es la garantía; el control del service existe para dar
    un mensaje entendible. Si solo estuviera el service, cualquier camino que
    no pase por él —una carga masiva, un script— metería el duplicado.
    """
    from sqlalchemy import text as sa_text

    _crear(db, autor, categoria, proveedor, "Zapatilla running")
    db.flush()

    indices = db.execute(
        sa_text("SELECT indexdef FROM pg_indexes WHERE tablename = 'productos'")
    ).scalars().all()

    unico = [i for i in indices if "uq_productos_descripcion_por_categoria_y_proveedor" in i]
    assert unico, "falta el índice único de la migración 0020"
    # La MISMA expresión que compara el service: si dejaran de coincidir, la
    # base aceptaría lo que el service rechaza (o al revés).
    assert "lower(translate" in unico[0]
    assert "categoria_id" in unico[0] and "proveedor_id" in unico[0]


# ============================================================================
# DESCRIPCIONES PARECIDAS (buscador del formulario de alta)
# ============================================================================


def test_los_parecidos_necesitan_diez_caracteres(db, autor, config, categoria, proveedor):
    """
    Con menos, cualquier texto corto coincide con medio catálogo y el
    desplegable es ruido justo cuando todavía no se terminó de escribir.
    """
    _crear(db, autor, categoria, proveedor, "Zapatilla running negra")
    db.flush()

    assert servicio.buscar_similares(db, descripcion="Zapatilla") == []
    assert servicio.buscar_similares(db, descripcion="Zapatilla r")


def test_los_parecidos_encuentran_por_palabras_y_no_por_la_frase_entera(
    db, autor, config, categoria, proveedor
):
    """
    Es el punto del buscador: mientras se escribe, lo tipeado casi nunca es
    un fragmento literal de lo ya cargado. Un ILIKE sobre la frase completa
    —lo que hace el filtro del listado— no encontraría nada.
    """
    _crear(db, autor, categoria, proveedor, "Zapatilla Nike Air Max 90")
    db.flush()

    # Las mismas palabras, en otro orden y sin ser subcadena de la guardada.
    assert len(servicio.buscar_similares(db, descripcion="nike zapatilla air")) == 1


def test_los_parecidos_exigen_todas_las_palabras(
    db, autor, config, categoria, proveedor
):
    """
    Con que alcanzara una sola, escribir "Nike" traería toda la marca y la
    lista dejaría de decir nada.
    """
    _crear(db, autor, categoria, proveedor, "Zapatilla Nike Air Max 90")
    _crear(db, autor, categoria, proveedor, "Campera Nike cortaviento")
    db.flush()

    encontrados = servicio.buscar_similares(db, descripcion="zapatilla nike")
    assert [p.descripcion for p in encontrados] == ["Zapatilla Nike Air Max 90"]


def test_los_parecidos_ignoran_las_palabras_de_menos_de_tres_letras(
    db, autor, config, categoria, proveedor
):
    """Palabras como "de", "y" o "18k" aparecen en cualquier lado."""
    _crear(db, autor, categoria, proveedor, "Cadena plata 925 eslabón")
    db.flush()

    assert servicio.buscar_similares(db, descripcion="cadena de plata")


def test_los_parecidos_ignoran_las_tildes(db, autor, config, categoria, proveedor):
    """Se tipea rápido y sin tildes; el catálogo está cargado con ellas."""
    _crear(db, autor, categoria, proveedor, "Camión de bomberos rojo")
    db.flush()

    assert servicio.buscar_similares(db, descripcion="camion bomberos")


def test_los_parecidos_se_acotan_al_proveedor_y_la_categoria(
    db, autor, config, proveedor, arbol
):
    """
    Es lo que hace que la lista sirva: son los productos con los que el que
    se está cargando podría chocar, no todos los que se llaman parecido.
    """
    _, _, deportivas, urbanas, _ = arbol
    otro_proveedor = servicio_proveedores.crear_proveedor(
        db, autor, nombre="Distribuidora Sur", dolar_actual=Decimal("1200")
    )

    _crear(db, autor, deportivas, proveedor, "Zapatilla running negra")
    _crear(db, autor, urbanas, proveedor, "Zapatilla running blanca")
    _crear(db, autor, deportivas, otro_proveedor, "Zapatilla running gris")
    db.flush()

    encontrados = servicio.buscar_similares(
        db, descripcion="zapatilla running",
        categoria_id=deportivas.id, proveedor_id=proveedor.id,
    )
    assert [p.descripcion for p in encontrados] == ["Zapatilla running negra"]


def test_los_parecidos_incluyen_la_descendencia_de_la_categoria(
    db, autor, config, proveedor, arbol
):
    """
    Los productos cuelgan de las hojas: elegir "Zapatillas" en el formulario
    tiene que ofrecer lo que está en "Deportivas", igual que el filtro del
    listado.
    """
    _, zapatillas, deportivas, _, _ = arbol

    _crear(db, autor, deportivas, proveedor, "Zapatilla running negra")
    db.flush()

    assert servicio.buscar_similares(
        db, descripcion="zapatilla running", categoria_id=zapatillas.id
    )


def test_los_parecidos_incluyen_los_inactivos(db, autor, config, categoria, proveedor):
    """
    Un producto dado de baja sigue ocupando su descripción, así que sigue
    siendo un duplicado. La pantalla lo muestra marcado como inactivo.
    """
    viejo = _crear(db, autor, categoria, proveedor, "Zapatilla running negra")
    servicio.cambiar_estado_producto(db, autor, viejo.id, activo=False)
    db.flush()

    encontrados = servicio.buscar_similares(db, descripcion="zapatilla running")
    assert [p.id for p in encontrados] == [viejo.id]


def test_los_parecidos_por_la_api_no_se_confunden_con_un_id(
    client, db, autor, config, categoria, proveedor, login
):
    """
    `/similares` tiene que estar declarado ANTES de `/{producto_id}`: si no,
    FastAPI lee "similares" como un id y devuelve 422.
    """
    headers = login("admin")
    _crear(db, autor, categoria, proveedor, "Zapatilla running negra")
    db.flush()

    resp = client.get(
        "/api/v1/productos/similares",
        params={"descripcion": "zapatilla running", "proveedor_id": proveedor.id},
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    assert [p["descripcion"] for p in resp.json()] == ["Zapatilla running negra"]
    # Lo mínimo para reconocerlo: sin variantes, fotos ni precios.
    assert set(resp.json()[0]) == {"id", "sku", "descripcion", "activo"}


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
    )

    db.refresh(variante)
    assert variante.descripcion_sufijo == "Rojo furioso"
    assert variante.ubicacion_deposito == "Estante 3"


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
        sa_select(Auditoria.accion).where(Auditoria.entidad == "producto_variantes")
    ).scalars().all()
    assert "variante.editar" in acciones


def test_el_listado_devuelve_el_nombre_de_la_variante(db, autor, producto):
    servicio.agregar_variante(
        db, autor, producto.id, sufijo="R", descripcion_sufijo="Rojo"
    )

    filas, _ = servicio.listar_variantes(db)

    assert [f.descripcion_sufijo for f in filas] == ["Rojo"]


# ============================================================================
# SKU DEL PROVEEDOR POR VARIANTE
# ============================================================================
#
# Misma regla que el precio: el propio manda sobre el del producto. Existe
# porque el proveedor no numera por producto sino por color y por talle.


@pytest.fixture
def producto_con_sku_prov(db, autor, config, categoria, proveedor):
    """Producto cuyo proveedor lo identifica como 'NK-AM90'."""
    return servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="Zapatilla Nike Air Max 90",
        sku_proveedor="NK-AM90",
    )


def test_el_sku_del_proveedor_propio_manda_sobre_el_del_producto(
    db, autor, producto_con_sku_prov
):
    v = servicio.agregar_variante(
        db, autor, producto_con_sku_prov.id, sufijo="R", descripcion_sufijo="Rojo",
        sku_proveedor="NK-AM90-RJ",
    )

    assert v.sku_proveedor == "NK-AM90-RJ"
    assert v.tiene_sku_proveedor_propio is True
    assert v.sku_proveedor_efectivo == "NK-AM90-RJ"
    # El del producto queda intacto: la variante no lo pisa, lo tapa.
    assert producto_con_sku_prov.sku_proveedor == "NK-AM90"


def test_una_variante_sin_sku_propio_usa_el_del_producto(db, autor, producto_con_sku_prov):
    v = servicio.agregar_variante(
        db, autor, producto_con_sku_prov.id, sufijo="N", descripcion_sufijo="Negro"
    )

    assert v.sku_proveedor is None
    assert v.tiene_sku_proveedor_propio is False
    assert v.sku_proveedor_efectivo == "NK-AM90"


def test_sin_sku_en_ninguno_de_los_dos_queda_en_nada(db, autor, producto):
    """
    El campo es opcional en los dos niveles: hay proveedores que no dan
    código. La pantalla no muestra la línea en ese caso.
    """
    v = servicio.agregar_variante(
        db, autor, producto.id, sufijo="U", descripcion_sufijo="Único"
    )

    assert producto.sku_proveedor is None
    assert v.sku_proveedor_efectivo is None


def test_el_sku_de_la_variante_se_normaliza(db, autor, producto_con_sku_prov):
    """
    Espacios de más al pegar de una planilla; vacío no es un código, es
    "usa el del producto".
    """
    con_espacios = servicio.agregar_variante(
        db, autor, producto_con_sku_prov.id, sufijo="A", descripcion_sufijo="Azul",
        sku_proveedor="  NK-AM90-AZ  ",
    )
    vacio = servicio.agregar_variante(
        db, autor, producto_con_sku_prov.id, sufijo="B", descripcion_sufijo="Blanco",
        sku_proveedor="   ",
    )

    assert con_espacios.sku_proveedor == "NK-AM90-AZ"
    assert vacio.sku_proveedor is None
    assert vacio.sku_proveedor_efectivo == "NK-AM90"


def test_vaciar_el_sku_devuelve_la_variante_al_del_producto(db, autor, producto_con_sku_prov):
    """
    NULL explícito significa algo concreto —volver al del producto— y por eso
    hace falta la bandera: sin ella no se distingue de "no lo mandes".
    """
    v = servicio.agregar_variante(
        db, autor, producto_con_sku_prov.id, sufijo="R", descripcion_sufijo="Rojo",
        sku_proveedor="NK-AM90-RJ",
    )

    servicio.editar_variante(db, autor, v.id, editar_sku_proveedor=True)

    db.refresh(v)
    assert v.sku_proveedor is None
    assert v.sku_proveedor_efectivo == "NK-AM90"


def test_no_mandar_el_sku_no_lo_toca(db, autor, producto_con_sku_prov):
    """Editar la ubicación no puede borrar el código del proveedor."""
    v = servicio.agregar_variante(
        db, autor, producto_con_sku_prov.id, sufijo="R", descripcion_sufijo="Rojo",
        sku_proveedor="NK-AM90-RJ",
    )

    servicio.editar_variante(db, autor, v.id, ubicacion_deposito="Estante 3")

    db.refresh(v)
    assert v.sku_proveedor == "NK-AM90-RJ"


def test_el_sku_de_la_variante_viaja_por_la_api(
    client, db, autor, login, producto_con_sku_prov
):
    """
    Cuál de los dos manda lo resuelve el backend: es una regla de negocio, no
    formato de pantalla (Principio 1).
    """
    headers = login("admin")
    db.flush()

    resp = client.post(
        f"/api/v1/productos/{producto_con_sku_prov.id}/variantes",
        json={"sufijo": "R", "descripcion_sufijo": "Rojo",
              "sku_proveedor": "NK-AM90-RJ"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    propia = resp.json()
    assert propia["sku_proveedor"] == "NK-AM90-RJ"
    assert propia["sku_proveedor_efectivo"] == "NK-AM90-RJ"
    assert propia["tiene_sku_proveedor_propio"] is True

    resp = client.post(
        f"/api/v1/productos/{producto_con_sku_prov.id}/variantes",
        json={"sufijo": "N", "descripcion_sufijo": "Negro"},
        headers=headers,
    )
    heredada = resp.json()
    assert heredada["sku_proveedor"] is None
    assert heredada["sku_proveedor_efectivo"] == "NK-AM90"
    assert heredada["tiene_sku_proveedor_propio"] is False

    # Y el listado, que es el que dibuja la tabla, dice lo mismo.
    #
    # Se busca por la descripción y no por el código del proveedor: el
    # buscador cubre código de etiqueta, SKU y descripción, y el del
    # proveedor queda fuera a propósito.
    filas = client.get(
        "/api/v1/productos/variantes",
        params={"busqueda": "Zapatilla Nike"},
        headers=headers,
    )
    por_codigo = {f["sufijo"]: f for f in filas.json()["resultados"]}
    assert por_codigo["R"]["sku_proveedor_efectivo"] == "NK-AM90-RJ"
    assert por_codigo["N"]["sku_proveedor_efectivo"] == "NK-AM90"

    # Vaciarlo desde la API la devuelve al del producto.
    resp = client.patch(
        f"/api/v1/productos/variantes/{propia['id']}",
        json={"sku_proveedor": None}, headers=headers,
    )
    assert resp.json()["sku_proveedor_efectivo"] == "NK-AM90"


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


# ============================================================================
# STOCK INFINITO — solo Cuenta Maestra
# ============================================================================


def test_un_vendedor_no_puede_prender_el_stock_infinito(db, autor, config, categoria,
                                                        proveedor, crear_usuario):
    """
    Es el interruptor que hace que el producto NO descuente stock al vender:
    prendido por error, el sistema deja de saber cuánto hay de ese artículo y
    nada avisa. Lo decide la Cuenta Maestra.

    La regla vive en el service y no en la pantalla: esconder el checkbox no
    impide llamar a la API sin la pantalla (Principio 1).
    """
    vendedor = crear_usuario("vende", ROL_VENDEDOR)

    with pytest.raises(servicio.SinPermiso):
        servicio.crear_producto(
            db, vendedor, categoria_id=categoria.id, proveedor_id=proveedor.id,
            precio_usd=Decimal("10"), descripcion="Producto de prueba",
            stock_infinito=True,
        )


def test_un_vendedor_puede_dar_de_alta_sin_stock_infinito(db, config, categoria,
                                                          proveedor, crear_usuario):
    """
    Lo que se rechaza es PRENDERLO, no que el campo viaje: el formulario
    manda el producto entero en cada guardado, y `stock_infinito=False` en un
    alta no cambia nada respecto del valor por defecto.
    """
    vendedor = crear_usuario("vende", ROL_VENDEDOR)

    p = servicio.crear_producto(
        db, vendedor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="Producto de prueba",
        stock_infinito=False,
    )

    assert p.stock_infinito is False


def test_un_vendedor_edita_un_producto_con_stock_infinito_sin_apagarlo(
    db, autor, config, categoria, proveedor, crear_usuario
):
    """
    El caso que hace falta que funcione: el formulario reenvía
    `stock_infinito` tal como vino aunque el checkbox no esté en pantalla.
    Rechazar la mera presencia del campo dejaría a un vendedor sin poder
    guardar NINGUNA edición de un producto con stock infinito.
    """
    p = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="Producto de prueba",
        stock_infinito=True,
    )
    vendedor = crear_usuario("vende", ROL_VENDEDOR)

    servicio.editar_producto(
        db, vendedor, p.id, descripcion="Otra descripción", stock_infinito=True
    )

    assert p.descripcion == "Otra descripción"
    assert p.stock_infinito is True


def test_un_vendedor_tampoco_puede_apagar_el_stock_infinito(db, autor, config, categoria,
                                                            proveedor, crear_usuario):
    """Apagarlo también es decidir sobre el descuento de stock."""
    p = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="Producto de prueba",
        stock_infinito=True,
    )
    vendedor = crear_usuario("vende", ROL_VENDEDOR)

    with pytest.raises(servicio.SinPermiso):
        servicio.editar_producto(db, vendedor, p.id, stock_infinito=False)

    assert p.stock_infinito is True


def test_la_cuenta_maestra_si_prende_el_stock_infinito(db, autor, config, categoria,
                                                       proveedor):
    p = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="Producto de prueba",
        stock_infinito=True,
    )
    assert p.stock_infinito is True

    servicio.editar_producto(db, autor, p.id, stock_infinito=False)
    assert p.stock_infinito is False


def test_la_api_responde_403_y_no_deja_la_edicion_a_medias(
    client, db, autor, config, categoria, proveedor, crear_usuario, roles,
    dar_permiso, login
):
    """
    403 y no un descarte silencioso: quien lo intenta se entera. Y la
    validación corre ANTES de tocar el producto, así que el resto de los
    campos del mismo pedido tampoco se guardan.

    El vendedor del test tiene `productos.editar`: lo que se prueba es que el
    permiso de editar productos no alcanza para este campo, y no que le falte
    el permiso de entrada —eso lo frenaría antes y el test no diría nada—.
    """
    p = servicio.crear_producto(
        db, autor, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("10"), descripcion="Producto de prueba",
    )
    crear_usuario("vende", ROL_VENDEDOR)
    dar_permiso(
        rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.PRODUCTOS, ver=True, editar=True
    )
    db.commit()

    resp = client.put(
        f"/api/v1/productos/{p.id}",
        json={"descripcion": "Cambiada", "stock_infinito": True},
        headers=login("vende"),
    )

    assert resp.status_code == 403
    assert "Cuenta Maestra" in resp.json()["detail"]

    db.refresh(p)
    assert p.stock_infinito is False
    assert p.descripcion == "Producto de prueba", "la edición se guardó a medias"


# ============================================================================
# NOMBRE DE LA TABLA
# ============================================================================


def test_la_tabla_de_variantes_se_llama_producto_variantes(db, producto):
    """
    `variantes` a secas no decía de qué. El prefijo la agrupa con su
    producto, igual que `producto_fotos`, y en plural como las otras 17
    tablas del esquema.

    Se verifica contra la base y no solo contra el `__tablename__`: si la
    migración renombrara algo distinto de lo que dice el modelo, la clase
    apuntaría a una tabla que no existe y esto lo agarra.

    La clase Python sigue siendo `Variante` y la ruta `/productos/variantes`
    tampoco cambia: lo que se renombró es la tabla, no el contrato de la API
    ni el vocabulario del código.
    """
    from sqlalchemy import text

    assert Variante.__tablename__ == "producto_variantes"

    fila = db.execute(
        text("SELECT count(*) FROM producto_variantes WHERE producto_id = :p"),
        {"p": producto.id},
    ).scalar()
    assert fila == 1, "la variante BASE del producto tiene que estar en la tabla nueva"


def test_los_indices_y_restricciones_llevan_el_nombre_nuevo(db):
    """
    Postgres NO renombra los índices ni las restricciones al renombrar la
    tabla: sin el ALTER explícito quedaría un `ix_variantes_*` colgando de
    `producto_variantes`, y la próxima migración que los busque por nombre
    no los encontraría.
    """
    from sqlalchemy import text

    def lleva_el_nombre_nuevo(nombre: str) -> bool:
        return any(
            nombre.startswith(p)
            for p in ("ck_producto_variantes", "ix_producto_variantes",
                      "uq_producto_variantes", "producto_variantes_")
        )

    restricciones = db.execute(
        text(
            "SELECT conname FROM pg_constraint"
            " WHERE conrelid = 'producto_variantes'::regclass"
        )
    ).scalars().all()
    assert restricciones, "no hay restricciones sobre la tabla"
    viejas = [c for c in restricciones if not lleva_el_nombre_nuevo(c)]
    assert not viejas, f"restricciones con el nombre viejo: {viejas}"

    indices = db.execute(
        text("SELECT indexname FROM pg_indexes WHERE tablename = 'producto_variantes'")
    ).scalars().all()
    assert indices, "no hay índices sobre la tabla"
    viejos = [i for i in indices if not lleva_el_nombre_nuevo(i)]
    assert not viejos, f"índices con el nombre viejo: {viejos}"


def test_la_auditoria_de_variantes_usa_el_nombre_nuevo(db, autor, producto):
    """
    Las 12 entidades auditadas usan el nombre de su tabla; dejar "variantes"
    rompería esa regla.

    Lo que ya está escrito NO cambia: `auditoria` es append-only por trigger
    (migración 0001) y no admite UPDATE ni desde una migración. El historial
    anterior a este cambio sigue bajo "variantes", así que una consulta del
    historial completo tiene que buscar por los dos nombres.
    """
    from app.models.auditoria import Auditoria
    from sqlalchemy import select as sa_select

    servicio.agregar_variante(
        db, autor, producto.id, sufijo="R", descripcion_sufijo="Rojo"
    )

    entidades = db.execute(
        sa_select(Auditoria.entidad).where(Auditoria.accion == "variante.crear")
    ).scalars().all()

    assert entidades and set(entidades) == {"producto_variantes"}
