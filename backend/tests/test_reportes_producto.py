"""
Tests del reporte "Historial del Producto": toda la vida de un producto en
un informe — carga, movimientos de stock, ventas, fallas y precios — cada
parte de lo más reciente a lo más viejo.
"""

from decimal import Decimal
from html.parser import HTMLParser

import pytest

from app.core.permisos import ROL_DUENO, ROL_VENDEDOR
from app.models.cambio import TipoCambio
from app.models.punto_de_venta import TipoPuntoVenta
from app.models.stock import TipoMovimiento
from app.schemas import reportes_producto as esquemas
from app.services import bajas_stock as servicio_bajas
from app.services import cambios as servicio_cambios
from app.services import medios_pago as servicio_medios
from app.services import productos as servicio_productos
from app.services import proveedores as servicio_proveedores
from app.services import remitos as servicio_remitos
from app.services import reportes_producto as servicio
from app.services import stock as servicio_stock
from app.services import ventas as servicio_ventas
from app.services.roles import NoEncontrado

from tests.test_arqueo import (  # noqa: F401
    LIBRE,
    autor,
    catalogo,
    con_stock,
    config,
    crear_variante,
    dispositivo,
    local,
)


@pytest.fixture
def cd(crear_punto_de_venta):
    return crear_punto_de_venta("CD", "Centro de Distribución", TipoPuntoVenta.CD)


def _vender(db, autor, dispositivo, variante):
    venta = servicio_ventas.iniciar_venta(db, autor, dispositivo, LIBRE)
    servicio_ventas.agregar_item(db, autor, venta, variante_id=variante.id)
    efectivo = next(m for m in servicio_medios.listar_medios(db) if m.nombre == "Efectivo")
    servicio_ventas.registrar_pagos(
        db, autor, venta, [{"medio_de_pago_id": efectivo.id, "monto": venta.total}]
    )
    servicio_ventas.confirmar_venta(db, autor, venta, LIBRE)
    return venta


@pytest.fixture
def historia(db, autor, local, cd, dispositivo, catalogo, crear_variante, con_stock,
             crear_usuario, asegurar_turno):
    """Un anillo que pasó por todo lo que el reporte tiene que contar."""
    _, proveedor = catalogo
    anillo = crear_variante("Anillo solitario", "1000")
    producto = anillo.producto

    # Carga: ingreso al CD y envío a un local.
    servicio_stock.aplicar_movimiento(
        db, autor, tipo=TipoMovimiento.INGRESO_PROVEEDOR,
        variante_id=anillo.id, cantidad=10, punto_venta_destino_id=cd.id,
    )
    servicio_remitos.crear_remito(
        db, autor, LIBRE, punto_venta_origen_id=cd.id, punto_venta_destino_id=local.id,
        items=[{"variante_id": anillo.id, "cantidad": 4}],
    )
    con_stock(anillo, 5)

    # Ventas: una confirmada y una anulada.
    asegurar_turno(local.id, autor.id)
    vendida = _vender(db, autor, dispositivo, anillo)
    anulada = _vender(db, autor, dispositivo, anillo)
    servicio_ventas.anular_venta(db, autor, anulada, motivo="prueba")

    # Fallas: una baja por rotura y un cambio por falla.
    rotura = servicio_bajas.crear_motivo(db, autor, "Rotura")
    servicio_bajas.registrar_baja(
        db, autor, LIBRE, variante_id=anillo.id, punto_de_venta_id=local.id,
        cantidad=1, motivo_baja_id=rotura.id,
    )
    autoriza = crear_usuario("auto", ROL_DUENO, nombre="Autoriza", es_autorizador=True)
    cambio, _ = servicio_cambios.iniciar_cambio(
        db, autor, tipo=TipoCambio.FALLA, punto_de_venta_id=local.id,
        autorizador_id=autoriza.id,
    )
    servicio_cambios.agregar_item_devuelto(db, cambio, anillo.id)
    servicio_cambios.agregar_item_nuevo(db, cambio, anillo.id)
    servicio_cambios.confirmar_cambio(db, autor, cambio)

    # Precios: una edición de precio, una que no toca precios y el dólar.
    servicio_productos.editar_producto(db, autor, producto.id, precio_usd=Decimal("1200"))
    servicio_productos.editar_producto(db, autor, producto.id, descripcion="Anillo solitario oro")
    servicio_proveedores.cambiar_dolar(db, autor, proveedor.id, Decimal("2"))
    db.flush()

    return {"producto": producto, "anillo": anillo, "vendida": vendida, "local": local}


def test_la_ficha_y_la_carga(db, historia):
    datos = servicio.historial_producto(db, historia["producto"].id)

    assert datos["ficha"]["descripcion"] == "Anillo solitario oro"
    tipos = [c["tipo"] for c in datos["carga"]]
    assert "alta" in tipos
    ingresos = [c for c in datos["carga"] if c["tipo"] == "ingreso"]
    assert sorted(c["cantidad"] for c in ingresos) == [5, 10]


def test_los_movimientos_son_todos_y_van_del_mas_nuevo_al_mas_viejo(db, historia):
    movimientos = servicio.historial_producto(db, historia["producto"].id)["movimientos"]

    tipos = {m["tipo"] for m in movimientos}
    assert {"ingreso_proveedor", "envio_cd_local", "venta", "baja"} <= tipos
    fechas = [m["fecha"] for m in movimientos]
    assert fechas == sorted(fechas, reverse=True)


def test_las_ventas_son_solo_las_confirmadas_con_resumen_por_local(db, historia):
    ventas = servicio.historial_producto(db, historia["producto"].id)["ventas"]

    assert [v["venta_id"] for v in ventas["detalle"]] == [historia["vendida"].id]
    assert ventas["unidades"] == 1
    assert ventas["importe"] == historia["vendida"].total
    (fila,) = ventas["por_local"]
    assert fila["punto_de_venta"] == historia["local"].nombre
    assert fila["unidades"] == 1


def test_las_fallas_son_el_cambio_por_falla_y_la_baja(db, historia):
    fallas = servicio.historial_producto(db, historia["producto"].id)["fallas"]

    assert sorted(f["tipo"] for f in fallas) == ["baja", "cambio_falla"]
    baja = next(f for f in fallas if f["tipo"] == "baja")
    assert baja["detalle"] == "Rotura"
    cambio = next(f for f in fallas if f["tipo"] == "cambio_falla")
    assert cambio["detalle"] == "Autoriza"


def test_los_precios_traen_la_edicion_y_el_dolar_del_proveedor(db, historia):
    precios = servicio.historial_producto(db, historia["producto"].id)["precios"]

    usd = next(p for p in precios if p["campo"] == "precio_usd")
    assert (Decimal(usd["anterior"]), Decimal(usd["nuevo"])) == (Decimal("1000"), Decimal("1200"))
    dolar = next(p for p in precios if p["campo"] == "dolar_proveedor")
    assert (Decimal(dolar["anterior"]), Decimal(dolar["nuevo"])) == (Decimal("1"), Decimal("2"))
    # La edición de la descripción no es un cambio de precio.
    assert {p["campo"] for p in precios} <= {
        "precio_usd", "precio_venta", "descuento_producto", "dolar_proveedor",
    }


def test_un_producto_inexistente(db):
    with pytest.raises(NoEncontrado):
        servicio.historial_producto(db, 999999)


# ── API, hub y permisos ─────────────────────────────────────────────────────


def test_api_busca_trae_el_historial_y_el_pdf(client, db, historia):
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})
    producto, anillo = historia["producto"], historia["anillo"]
    base = "/api/v1/reportes/historial-producto"

    for texto in (producto.sku, "solitario", anillo.codigo_completo + anillo.verificador):
        encontrados = client.get(f"{base}/buscar", params={"busqueda": texto}).json()
        assert any(p["id"] == producto.id for p in encontrados), texto

    resp = client.get(f"{base}/{producto.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["ficha"]["sku"] == producto.sku
    assert client.get(f"{base}/999999").status_code == 404

    pdf = client.get(f"{base}/{producto.id}/pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")


def test_el_buscador_trae_la_foto_principal(db, historia):
    from app.models.producto_foto import ProductoFoto

    producto = historia["producto"]
    assert servicio.buscar_productos(db, producto.sku)[0].foto_principal_url is None

    db.add(ProductoFoto(producto_id=producto.id, url="/media/productos/h.jpg", es_principal=True))
    db.flush()
    db.expire_all()

    encontrado = esquemas.ProductoEncontrado.model_validate(
        servicio.buscar_productos(db, producto.sku)[0]
    )
    assert encontrado.foto_url == "/media/productos/h.jpg"


def test_la_tarjeta_esta_en_reportes_de_producto(client, db, autor):
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    assert 'href="/reportes/historial-producto"' in client.get("/reportes/productos").text
    assert client.get("/reportes/historial-producto").status_code == 200


def test_la_pagina_le_pasa_el_componente_entero_a_alpine(client, db, autor):
    """
    Los nombres viajan como JSON dentro de `x-data`: si el atributo usa
    comillas dobles, las del JSON lo cortan y Alpine no arranca (el buscador
    queda muerto). Se lee el atributo como lo lee el navegador.
    """
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    class _XData(HTMLParser):
        valores: list[str] = []

        def handle_starttag(self, tag, attrs):
            self.valores += [v for k, v in attrs if k == "x-data" and "historialProducto" in v]

    lector = _XData()
    lector.feed(client.get("/reportes/historial-producto?producto_id=7").text)
    assert len(lector.valores) == 1
    x_data = lector.valores[0]
    assert x_data.startswith("historialProducto(7, {") and x_data.endswith("})")
    assert '"tipos_movimiento"' in x_data


def test_sin_permiso_de_reportes_no_se_ve(client, db, crear_usuario):
    crear_usuario("vende", ROL_VENDEDOR)
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})

    assert client.get("/api/v1/reportes/historial-producto/buscar?busqueda=a").status_code == 403
