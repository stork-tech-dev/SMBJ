"""
Tests de señas: el alta desde el local y las reglas que cuestan plata.

  1. La seña entra a la caja: exige turno abierto y un medio que no sea seña.
  2. Una a la vez: con una vigente no se deja otra.
  3. Se usa entera, y anular la venta la devuelve entera (incluida la parte
     que se había perdido).
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.auditoria import Auditoria
from app.models.cliente import Cliente
from app.services import clientes as servicio_clientes
from app.services import senas as servicio_senas
from app.services import ventas as servicio_ventas
from app.services.roles import ReglaDeNegocio

# Los fixtures de ventas: local, dispositivo, catálogo, medios y la fábrica
# de señas con turno.
from tests.test_ventas import (  # noqa: F401
    LIBRE,
    autor,
    catalogo,
    cliente,
    con_stock,
    config,
    crear_variante,
    dejar_sena,
    dispositivo,
    efectivo,
    local,
    medio_sena,
    otro_local,
    venta,
)


def test_sin_turno_abierto_no_se_recibe_una_sena(db, autor, local, efectivo, cliente):
    with pytest.raises(ReglaDeNegocio, match="turno"):
        servicio_senas.registrar_sena(
            db, autor, cliente_id=cliente.id, monto=Decimal("1000"),
            punto_de_venta_id=local.id, medio_de_pago_id=efectivo.id,
        )


def test_alta_fija_vencimiento_caja_y_queda_auditada(db, autor, cliente, config, dejar_sena):
    sena = dejar_sena(cliente, "5000")

    assert sena.saldo == sena.monto == Decimal("5000")
    assert sena.turno_id is not None and sena.medio_de_pago_id is not None
    dias = (sena.vence_el - servicio_senas.hoy()).days
    assert dias == config.dias_vigencia_sena
    assert db.execute(
        select(Auditoria).where(Auditoria.accion == "sena.crear", Auditoria.entidad_id == sena.id)
    ).scalar_one_or_none() is not None


def test_no_se_paga_una_sena_con_otra_sena(db, autor, local, cliente, medio_sena, dejar_sena):
    otro = servicio_clientes.crear_cliente(db, autor, nombre="Otra", dni="11222333")
    dejar_sena(otro, "100")  # abre el turno

    with pytest.raises(ReglaDeNegocio, match="otra seña"):
        servicio_senas.registrar_sena(
            db, autor, cliente_id=cliente.id, monto=Decimal("1000"),
            punto_de_venta_id=local.id, medio_de_pago_id=medio_sena.id,
        )


def test_con_una_vigente_no_se_deja_otra(db, cliente, dejar_sena):
    dejar_sena(cliente, "5000")
    with pytest.raises(ReglaDeNegocio, match="ya tiene una seña"):
        dejar_sena(cliente, "2000")


def test_alta_con_cliente_nuevo_lo_crea_en_la_misma_operacion(
    db, autor, local, efectivo, cliente, dejar_sena
):
    dejar_sena(cliente, "100")  # abre el turno

    sena = servicio_senas.registrar_sena(
        db, autor, cliente_nuevo={"nombre": "Marta Gómez", "dni": "28111222", "telefono": None},
        monto=Decimal("3000"), punto_de_venta_id=local.id, medio_de_pago_id=efectivo.id,
    )

    nuevo = db.get(Cliente, sena.cliente_id)
    assert (nuevo.nombre, nuevo.dni) == ("Marta Gómez", "28111222")


def test_cliente_existente_o_nuevo_nunca_los_dos(db, autor, local, efectivo, cliente):
    with pytest.raises(ReglaDeNegocio, match="cliente existente"):
        servicio_senas.registrar_sena(
            db, autor, cliente_id=cliente.id, cliente_nuevo={"nombre": "X"},
            monto=Decimal("1"), punto_de_venta_id=local.id, medio_de_pago_id=efectivo.id,
        )


def test_anular_devuelve_la_sena_entera_aunque_se_haya_perdido_una_parte(
    db, autor, venta, crear_variante, con_stock, cliente, dejar_sena
):
    sena = dejar_sena(cliente, "10000")
    variante = crear_variante("Anillo", "8000")
    con_stock(variante, 5)
    servicio_ventas.agregar_item(db, autor, venta, variante_id=variante.id)
    servicio_ventas.asociar_cliente(db, autor, venta, cliente.id)
    servicio_ventas.registrar_pagos(db, autor, venta, [], usar_sena=True)
    servicio_ventas.confirmar_venta(db, autor, venta, LIBRE)
    assert Decimal(sena.saldo) == Decimal("0")

    servicio_ventas.anular_venta(db, autor, venta, motivo="Se arrepintió")

    assert Decimal(sena.saldo) == Decimal("10000")
    assert servicio_senas.senas_disponibles(db, cliente.id) == [sena]


def test_alta_por_api_desde_el_celular(client, db, autor, dispositivo, efectivo, cliente, dejar_sena):
    """El local sale del dispositivo, no del pedido; el cliente nuevo se crea en el mismo POST."""
    otro = servicio_clientes.crear_cliente(db, autor, nombre="Otra", dni="11222333")
    dejar_sena(otro, "100")  # abre el turno del local del dispositivo
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})
    client.cookies.set("device_uuid", str(dispositivo.uuid))

    medios = client.get("/api/v1/senas/medios-de-pago").json()
    assert all(m["nombre"] != "Seña" for m in medios)

    r = client.post("/api/v1/senas", json={
        "cliente_nuevo": {"nombre": "Marta Gómez", "dni": "28111222"},
        "medio_de_pago_id": efectivo.id, "monto": "3000",
    })
    assert r.status_code == 201, r.text
    assert r.json()["cliente"]["nombre"] == "Marta Gómez"

    r = client.post("/api/v1/senas", json={
        "cliente_id": cliente.id, "cliente_nuevo": {"nombre": "X"},
        "medio_de_pago_id": efectivo.id, "monto": "1",
    })
    assert r.status_code == 422


def test_el_home_ofrece_senas_y_la_pantalla_carga(client, db, autor, dispositivo, config):
    db.commit()
    client.cookies.set("device_uuid", str(dispositivo.uuid))
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    home = client.get("/ventas").text
    assert 'href="/senas"' in home
    assert home.count('class="acceso-rapido ') == 6

    pantalla = client.get("/senas").text
    assert "senaNueva()" in pantalla
    assert f"{config.dias_vigencia_sena} días" in pantalla


# ── Comprobante en PDF ─────────────────────────────────────────────────────


def test_el_comprobante_trae_los_datos_de_la_sena(db, cliente, dejar_sena):
    """Lo que el cliente se lleva: quién, cuánto, hasta cuándo y la nota."""
    from app.core.templates import templates
    from app.core.utils import ahora_db

    sena = dejar_sena(cliente, "12345.5")
    sena.descripcion = "Anillo talle 14, lo retira el sábado"
    db.flush()
    db.refresh(sena)

    html = templates.get_template("reports/sena.html").render(
        sena=sena, letra_empresa="S", emitido=ahora_db()
    )

    assert "Comprobante de seña" in html
    assert "Leandra Carballo" in html
    assert "39059158" in html
    assert "$ 12.345,50" in html
    assert sena.vence_el.strftime("%d/%m/%Y") in html
    assert "Anillo talle 14, lo retira el sábado" in html
    assert "Efectivo" in html
    assert "Patio Olmos" in html
    assert "no válido como factura" in html


def test_api_comprobante_devuelve_el_pdf(client, db, autor, dispositivo, cliente, dejar_sena):
    sena = dejar_sena(cliente, "3000")
    db.commit()
    client.cookies.set("device_uuid", str(dispositivo.uuid))
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    r = client.get(f"/api/v1/senas/{sena.id}/comprobante")

    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert f'filename="sena-{sena.id}.pdf"' in r.headers["content-disposition"]
    assert r.content.startswith(b"%PDF")

    assert client.get("/api/v1/senas/999999/comprobante").status_code == 404


def test_no_se_baja_el_comprobante_de_una_sena_de_otro_local(
    client, db, cliente, dejar_sena, otro_local, crear_usuario, dar_permiso, roles,
):
    """Cambiar el id en la URL no alcanza para ver la seña de otro local."""
    from app.core.permisos import ROL_VENDEDOR, Modulo
    from app.models.dispositivo import Dispositivo

    sena = dejar_sena(cliente, "3000")  # en "Patio Olmos"
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.VENTAS, ver=True, crear=True)
    crear_usuario("vende", ROL_VENDEDOR)
    equipo = Dispositivo(punto_de_venta_id=otro_local.id, activo=True, descripcion="Celu 2")
    db.add(equipo)
    db.commit()
    client.cookies.set("device_uuid", str(equipo.uuid))
    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})

    assert client.get(f"/api/v1/senas/{sena.id}/comprobante").status_code == 403
