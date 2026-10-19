"""
Tests de los Reportes de Productividad: cuánto hizo cada usuario en un
período.

  1. Centro de Distribución: variantes vendibles que dio de alta (un
     producto con 3 talles cuenta 3, no 4: la BASE se borra al agregar la
     primera variante) y remitos que mandó desde el CD, con sus unidades.
  2. Vendedores: ventas confirmadas (cantidad, unidades, importe), señas
     (cantidad, importe) y cambios confirmados. Ni anuladas ni en curso.
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.permisos import ROL_DUENO, ROL_VENDEDOR
from app.core.utils import ahora_db
from app.models.punto_de_venta import TipoPuntoVenta
from app.models.stock import TipoMovimiento
from app.services import cambios as servicio_cambios
from app.services import clientes as servicio_clientes
from app.services import medios_pago as servicio_medios
from app.services import productos as servicio_productos
from app.services import remitos as servicio_remitos
from app.services import reportes_productividad as servicio
from app.services import senas as servicio_senas
from app.services import stock as servicio_stock
from app.services import ventas as servicio_ventas

# Los fixtures de venta (local, dispositivo, catálogo, variantes con stock) y
# la venta confirmada de dos productos de los tests de cambios.
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
from tests.test_cambios import _cambio_con, venta  # noqa: F401


def _hoy():
    return ahora_db().date()


def _fila(datos, usuario):
    return next((f for f in datos["filas"] if f["usuario_id"] == usuario.id), None)


@pytest.fixture
def cd(crear_punto_de_venta):
    return crear_punto_de_venta("CD", "Centro de Distribución", TipoPuntoVenta.CD)


@pytest.fixture
def otro_local(crear_punto_de_venta):
    return crear_punto_de_venta("MPJ", "Paseo del Jockey", TipoPuntoVenta.LOCAL)


@pytest.fixture
def deposito(crear_usuario):
    """Quien trabaja en el CD: carga productos y arma los envíos."""
    return crear_usuario("deposito", ROL_DUENO, nombre="Dante Depósito")


def _ingresar(db, autor, variante, punto, cantidad):
    servicio_stock.aplicar_movimiento(
        db, autor, tipo=TipoMovimiento.INGRESO_PROVEEDOR,
        variante_id=variante.id, cantidad=cantidad, punto_venta_destino_id=punto.id,
    )


# ── Centro de Distribución ──────────────────────────────────────────────────


def test_un_producto_sin_variantes_cuenta_uno(db, autor, crear_variante):
    crear_variante("Anillo", "100")

    fila = _fila(servicio.centro_distribucion(db, _hoy(), _hoy()), autor)

    assert fila["productos"] == 1


def test_un_producto_con_tres_variantes_cuenta_tres_no_cuatro(db, deposito, catalogo):
    """La BASE se borra al agregar la primera variante: no suma."""
    categoria, proveedor = catalogo
    producto = servicio_productos.crear_producto(
        db, deposito, categoria_id=categoria.id, proveedor_id=proveedor.id,
        precio_usd=Decimal("100"), descripcion="Remera lisa",
    )
    for sufijo, nombre in (("S", "Chica"), ("M", "Mediana"), ("L", "Grande")):
        servicio_productos.agregar_variante(
            db, deposito, producto.id, sufijo=sufijo, descripcion_sufijo=nombre,
        )
    db.flush()

    datos = servicio.centro_distribucion(db, _hoy(), _hoy())

    assert _fila(datos, deposito)["productos"] == 3
    assert datos["totales"]["productos"] == 3


def test_los_remitos_desde_el_cd_suman_remitos_y_unidades(
    db, autor, deposito, crear_variante, cd, local, otro_local,
):
    anillo = crear_variante("Anillo", "100")
    _ingresar(db, autor, anillo, cd, 20)
    _ingresar(db, autor, anillo, local, 10)

    for cantidad in (5, 3):
        servicio_remitos.crear_remito(
            db, deposito, LIBRE, punto_venta_origen_id=cd.id,
            punto_venta_destino_id=local.id,
            items=[{"variante_id": anillo.id, "cantidad": cantidad}],
        )
    # Entre locales no es trabajo del CD.
    servicio_remitos.crear_remito(
        db, deposito, LIBRE, punto_venta_origen_id=local.id,
        punto_venta_destino_id=otro_local.id,
        items=[{"variante_id": anillo.id, "cantidad": 4}],
    )
    db.flush()

    fila = _fila(servicio.centro_distribucion(db, _hoy(), _hoy()), deposito)

    assert fila["remitos"] == 2
    assert fila["unidades_remitidas"] == 8
    assert fila["productos"] == 0


def test_cd_fuera_del_rango_no_aparece(db, autor, crear_variante):
    crear_variante("Anillo", "100")
    manana = _hoy() + timedelta(days=1)

    assert servicio.centro_distribucion(db, manana, manana)["filas"] == []


# ── Vendedores ──────────────────────────────────────────────────────────────


def test_vendedores_cuenta_ventas_confirmadas_unidades_e_importe(
    db, autor, dispositivo, venta, crear_variante, con_stock,
):
    """La venta del fixture tiene 2 productos. Anulada y en curso no cuentan."""
    collar = crear_variante("Collar", "300")
    con_stock(collar, 5)

    anulada = servicio_ventas.iniciar_venta(db, autor, dispositivo, LIBRE)
    servicio_ventas.agregar_item(db, autor, anulada, variante_id=collar.id)
    efectivo = next(m for m in servicio_medios.listar_medios(db) if m.nombre == "Efectivo")
    servicio_ventas.registrar_pagos(
        db, autor, anulada, [{"medio_de_pago_id": efectivo.id, "monto": anulada.total}]
    )
    servicio_ventas.confirmar_venta(db, autor, anulada, LIBRE)
    servicio_ventas.anular_venta(db, autor, anulada, motivo="prueba")

    en_curso = servicio_ventas.iniciar_venta(db, autor, dispositivo, LIBRE)
    servicio_ventas.agregar_item(db, autor, en_curso, variante_id=collar.id)
    db.flush()

    fila = _fila(servicio.vendedores(db, _hoy(), _hoy()), autor)

    assert fila["ventas"] == 1
    assert fila["unidades"] == 2
    assert fila["importe"] == venta.total


def test_vendedores_cuenta_senas_y_cambios_confirmados(
    db, autor, local, venta, asegurar_turno,
):
    asegurar_turno(local.id, autor.id)
    efectivo = next(m for m in servicio_medios.listar_medios(db) if m.nombre == "Efectivo")
    cliente = servicio_clientes.crear_cliente(db, autor, nombre="Marta", dni="20111222")
    servicio_senas.registrar_sena(
        db, autor, cliente_id=cliente.id, monto=Decimal("1500"),
        punto_de_venta_id=local.id, medio_de_pago_id=efectivo.id,
    )

    items = servicio_cambios.items_del_ticket(db, venta.codigo_cambio)["items"]
    confirmado = _cambio_con(db, autor, local, venta, items[0])
    servicio_cambios.confirmar_cambio(db, autor, confirmado)
    _cambio_con(db, autor, local, venta, items[1])  # queda pendiente
    db.flush()

    fila = _fila(servicio.vendedores(db, _hoy(), _hoy()), autor)

    assert fila["senas"] == 1
    assert fila["importe_senas"] == Decimal("1500")
    assert fila["cambios"] == 1


def test_vendedores_filtra_por_local(db, autor, local, otro_local, venta):
    assert _fila(servicio.vendedores(db, _hoy(), _hoy(), local.id), autor)["ventas"] == 1
    assert servicio.vendedores(db, _hoy(), _hoy(), otro_local.id)["filas"] == []


# ── API, hub y permisos ─────────────────────────────────────────────────────


@pytest.mark.parametrize("slug", ["centro-distribucion", "vendedores"])
def test_api_por_defecto_va_del_inicio_del_mes_a_hoy_y_exporta(client, db, autor, slug):
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})
    hoy = _hoy()
    url = f"/api/v1/reportes/productividad/{slug}"

    datos = client.get(url).json()
    assert datos["fecha_desde"] == hoy.replace(day=1).isoformat()
    assert datos["fecha_hasta"] == hoy.isoformat()

    resp = client.get(url, params={
        "fecha_desde": hoy.isoformat(), "fecha_hasta": (hoy - timedelta(days=1)).isoformat(),
    })
    assert resp.status_code == 422

    excel = client.get(f"{url}/exportar")
    assert excel.status_code == 200
    assert excel.content[:2] == b"PK"


def test_el_hub_tiene_productividad_con_sus_dos_reportes(client, db, autor):
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    hub = client.get("/reportes").text
    assert 'href="/reportes/productividad"' in hub
    assert "Reportes de Productividad" in hub

    grupo = client.get("/reportes/productividad").text
    for slug in ("centro-distribucion", "vendedores"):
        assert f'href="/reportes/productividad/{slug}"' in grupo
        pagina = client.get(f"/reportes/productividad/{slug}")
        assert pagina.status_code == 200
        assert 'id="f-fecha-desde"' in pagina.text


def test_sin_permiso_de_reportes_no_se_ve(client, db, crear_usuario):
    crear_usuario("vende", ROL_VENDEDOR)
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})

    assert 'href="/reportes/productividad"' not in client.get("/reportes").text
    assert client.get("/api/v1/reportes/productividad/vendedores").status_code == 403
