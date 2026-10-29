"""
Tests de la primera pantalla del cambio en el celular: los productos del
ticket del código de cambio, para elegir ahí cuáles devuelve el cliente.
"""

from decimal import Decimal

import pytest

from app.models.cambio import TipoCambio
from app.services import cambios as servicio_cambios
from app.services import medios_pago as servicio_medios
from app.services import ventas as servicio_ventas
from app.services.roles import NoEncontrado, ReglaDeNegocio

# Los fixtures de venta de los tests de arqueo: local, dispositivo, catálogo
# con variantes y stock.
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
def venta(db, autor, dispositivo, crear_variante, con_stock, asegurar_turno):
    """Venta confirmada de dos productos distintos, con su código de cambio."""
    anillo = crear_variante("Anillo", "1000")
    aro = crear_variante("Aro", "500")
    for v in (anillo, aro):
        con_stock(v, 5)

    asegurar_turno(dispositivo.punto_de_venta_id, autor.id)
    venta = servicio_ventas.iniciar_venta(db, autor, dispositivo, LIBRE)
    for v in (anillo, aro):
        servicio_ventas.agregar_item(db, autor, venta, variante_id=v.id)
    efectivo = next(m for m in servicio_medios.listar_medios(db) if m.nombre == "Efectivo")
    servicio_ventas.registrar_pagos(
        db, autor, venta, [{"medio_de_pago_id": efectivo.id, "monto": venta.total}]
    )
    servicio_ventas.confirmar_venta(db, autor, venta, LIBRE)
    db.flush()
    return venta


def test_items_del_ticket_trae_cada_producto_de_la_venta(db, venta):
    ticket = servicio_cambios.items_del_ticket(db, venta.codigo_cambio.lower())

    assert ticket["origen"] == "venta"
    assert [i["descripcion"] for i in ticket["items"]] == ["Anillo", "Aro"]
    assert all(i["disponible"] for i in ticket["items"])
    primero = ticket["items"][0]
    item_venta = min(venta.items, key=lambda i: i.id)
    assert primero["venta_item_id"] == item_venta.id
    # El código como está en la etiqueta: con el dígito verificador.
    variante = item_venta.variante
    assert primero["codigo"] == variante.codigo_completo + variante.verificador
    assert primero["precio"] == item_venta.precio_unitario
    assert "foto_url" in primero


def test_items_del_ticket_valida_el_codigo(db, venta):
    with pytest.raises(NoEncontrado):
        servicio_cambios.items_del_ticket(db, "ZZZZ9999")

    venta.codigo_cambio_activo = False
    db.flush()
    with pytest.raises(ReglaDeNegocio, match="ya fue utilizado"):
        servicio_cambios.items_del_ticket(db, venta.codigo_cambio)


def test_api_ticket(client, db, venta):
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    resp = client.get("/api/v1/cambios/ticket", params={"codigo": venta.codigo_cambio})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 2
    assert client.get("/api/v1/cambios/ticket", params={"codigo": "ZZZZ9999"}).status_code == 404


def test_la_primera_pantalla_ofrece_elegir_del_ticket(client, db, autor, dispositivo):
    db.commit()
    client.cookies.set("device_uuid", str(dispositivo.uuid))
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    html = client.get("/cambios/nuevo").text
    assert "buscarTicket()" in html
    assert "¿Qué devuelve el cliente?" in html


# ── Solo el cambio confirmado se lleva los ítems ────────────────────────────


def _cambio_con(db, autor, local, venta, item):
    """Cambio común que devuelve `item` del ticket y se lleva lo mismo (diferencia 0)."""
    cambio, _ = servicio_cambios.iniciar_cambio(
        db, autor, tipo=TipoCambio.COMUN, punto_de_venta_id=local.id,
        codigos_cambio=[venta.codigo_cambio],
    )
    servicio_cambios.agregar_item_devuelto(db, cambio, item["variante_id"], item["venta_item_id"])
    servicio_cambios.agregar_item_nuevo(db, cambio, item["variante_id"])
    db.flush()
    db.refresh(cambio)
    return cambio


def _disponibles(db, venta):
    return {
        i["descripcion"]: i["disponible"]
        for i in servicio_cambios.items_del_ticket(db, venta.codigo_cambio)["items"]
    }


def test_un_cambio_sin_confirmar_no_se_lleva_los_items(db, autor, local, venta):
    anillo = servicio_cambios.items_del_ticket(db, venta.codigo_cambio)["items"][0]
    _cambio_con(db, autor, local, venta, anillo)  # queda sin realizar

    # Sigue siendo de la venta original: se ofrece y otro cambio lo puede tomar.
    assert _disponibles(db, venta)["Anillo"] is True
    otro = _cambio_con(db, autor, local, venta, anillo)
    servicio_cambios.confirmar_cambio(db, autor, otro)
    db.flush()

    assert _disponibles(db, venta)["Anillo"] is False


def test_al_confirmar_se_controla_que_no_se_haya_devuelto_en_otro(db, autor, local, venta):
    anillo = servicio_cambios.items_del_ticket(db, venta.codigo_cambio)["items"][0]
    primero = _cambio_con(db, autor, local, venta, anillo)
    segundo = _cambio_con(db, autor, local, venta, anillo)

    servicio_cambios.confirmar_cambio(db, autor, primero)
    db.flush()
    with pytest.raises(ReglaDeNegocio, match="ya se devolvió en otro cambio confirmado"):
        servicio_cambios.confirmar_cambio(db, autor, segundo)


def test_no_se_devuelve_dos_veces_lo_mismo_en_un_cambio(db, autor, local, venta):
    anillo = servicio_cambios.items_del_ticket(db, venta.codigo_cambio)["items"][0]
    cambio, _ = servicio_cambios.iniciar_cambio(
        db, autor, tipo=TipoCambio.COMUN, punto_de_venta_id=local.id,
        codigos_cambio=[venta.codigo_cambio],
    )
    servicio_cambios.agregar_item_devuelto(db, cambio, anillo["variante_id"], anillo["venta_item_id"])
    db.flush()
    db.refresh(cambio)
    with pytest.raises(ReglaDeNegocio, match="ya está entre los devueltos"):
        servicio_cambios.agregar_item_devuelto(
            db, cambio, anillo["variante_id"], anillo["venta_item_id"]
        )


def test_items_nuevos_muestra_la_diferencia_y_finalizar_cambio(client, db, autor, dispositivo):
    """La diferencia se ve al sumar lo nuevo, con el mismo bloque que Confirmar."""
    db.commit()
    client.cookies.set("device_uuid", str(dispositivo.uuid))
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    nuevos = client.get("/cambios/nuevo/nuevos?id=1").text
    assert "Finalizar Cambio" in nuevos
    assert "Ver diferencia" not in nuevos
    assert "pesos(diferencia.total_devuelto)" in nuevos
    assert "El cliente paga" in nuevos

    confirmar = client.get("/cambios/nuevo/confirmar?id=1").text
    assert "pesos(diferencia.total_devuelto)" in confirmar


def test_la_vendedora_ve_los_medios_para_pagar_la_diferencia_y_confirma(
    client, db, autor, local, dispositivo, venta, crear_usuario, dar_permiso, roles,
):
    """
    Bug real: Confirmar pedía los medios al catálogo de Configuración, que
    la vendedora no puede ver — el combo quedaba vacío y el cambio con
    diferencia a pagar no se podía terminar. Ahora los da el propio cambio,
    con el permiso de Ventas: los activos, sin la seña.
    """
    from app.core.permisos import ROL_VENDEDOR, Modulo
    from app.models.medio_pago import MedioDePago

    inactivo = servicio_medios.crear_medio(db, autor, nombre="Cheque")
    inactivo.activo = False

    # Devuelve el aro ($500) y se lleva otro anillo ($1000): paga la diferencia.
    items = {i["descripcion"]: i for i in servicio_cambios.items_del_ticket(db, venta.codigo_cambio)["items"]}
    aro = next(v for k, v in items.items() if k.startswith("Aro"))
    anillo = next(v for k, v in items.items() if k.startswith("Anillo"))
    cambio, _ = servicio_cambios.iniciar_cambio(
        db, autor, tipo=TipoCambio.COMUN, punto_de_venta_id=local.id,
        codigos_cambio=[venta.codigo_cambio],
    )
    servicio_cambios.agregar_item_devuelto(db, cambio, aro["variante_id"], aro["venta_item_id"])
    servicio_cambios.agregar_item_nuevo(db, cambio, anillo["variante_id"])

    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.VENTAS, ver=True, crear=True)
    crear_usuario("vende", ROL_VENDEDOR)
    db.commit()
    client.cookies.set("device_uuid", str(dispositivo.uuid))
    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})

    # El catálogo de Configuración le sigue cerrado: no es el camino.
    assert client.get("/api/v1/configuracion/medios-de-pago").status_code == 403

    resp = client.get(f"/api/v1/cambios/{cambio.id}/medios-de-pago")
    assert resp.status_code == 200, resp.text
    nombres = {m["nombre"] for m in resp.json()}
    assert "Efectivo" in nombres
    assert "Cheque" not in nombres
    sena = db.query(MedioDePago).filter(MedioDePago.es_sena.is_(True)).first()
    assert sena is None or sena.nombre not in nombres

    efectivo = next(m for m in resp.json() if m["nombre"] == "Efectivo")
    resp = client.post(f"/api/v1/cambios/{cambio.id}/confirmar", json={
        "medio_pago_diferencia_id": efectivo["id"],
        "plan_cuotas_diferencia_id": None,
        "notas": None,
    })
    assert resp.status_code == 200, resp.text


def test_el_codigo_nuevo_de_un_cambio_tiene_4_caracteres_como_el_de_la_venta(
    db, autor, local, venta,
):
    """
    Los códigos de cambio pasaron a 4 caracteres, pero el cambio seguía
    dando uno de 8 con su propio generador. Ahora sale del mismo que las
    ventas: mismo largo, mismo alfabeto, misma unicidad.
    """
    item = servicio_cambios.items_del_ticket(db, venta.codigo_cambio)["items"][0]
    cambio = _cambio_con(db, autor, local, venta, item)

    servicio_cambios.confirmar_cambio(db, autor, cambio)

    nuevo = cambio.codigo_cambio_nuevo
    assert len(nuevo) == servicio_ventas.LARGO_CODIGO_CAMBIO == 4
    assert set(nuevo) <= set(servicio_ventas._ALFABETO_CAMBIO)


def test_un_codigo_viejo_de_8_caracteres_se_sigue_encontrando(db, venta):
    """Las ventas anteriores al cambio a 4 caracteres tienen códigos de 8."""
    venta.codigo_cambio = "ABCD2345"
    db.flush()

    assert servicio_cambios.items_del_ticket(db, "ABCD2345")["items"]


# ── Varios tickets en un mismo cambio ───────────────────────────────────────


@pytest.fixture
def hacer_venta(db, autor, dispositivo, crear_variante, con_stock, asegurar_turno):
    """Fábrica de ventas confirmadas de UN producto, opcionalmente con cliente."""
    asegurar_turno(dispositivo.punto_de_venta_id, autor.id)
    efectivo = next(m for m in servicio_medios.listar_medios(db) if m.nombre == "Efectivo")

    def _hacer(descripcion, precio, cliente=None):
        variante = crear_variante(descripcion, precio)
        con_stock(variante, 5)
        venta = servicio_ventas.iniciar_venta(db, autor, dispositivo, LIBRE)
        servicio_ventas.agregar_item(db, autor, venta, variante_id=variante.id)
        if cliente is not None:
            servicio_ventas.asociar_cliente(db, autor, venta, cliente.id)
        servicio_ventas.registrar_pagos(
            db, autor, venta, [{"medio_de_pago_id": efectivo.id, "monto": venta.total}]
        )
        servicio_ventas.confirmar_venta(db, autor, venta, LIBRE)
        db.flush()
        return venta

    return _hacer


def _cliente(db, autor, apellido, dni):
    from app.services import clientes as servicio_clientes

    return servicio_clientes.crear_cliente(
        db, autor, apellido=apellido, nombre="Ana", email=f"{dni}@prueba.com", dni=dni
    )


def _devolver_todo(db, cambio, venta):
    for i in servicio_cambios.items_del_ticket(db, venta.codigo_cambio)["items"]:
        servicio_cambios.agregar_item_devuelto(db, cambio, i["variante_id"], i["venta_item_id"])


def test_dos_tickets_suman_lo_devuelto_para_llevar_algo_de_mas_valor(
    db, autor, local, hacer_venta, crear_variante, con_stock,
):
    """
    Dos tickets de $1000 y $500 se juntan: el cliente se lleva algo de
    $2000 y paga solo la diferencia contra los dos ($500).
    """
    from sqlalchemy import select

    from app.models.stock import MovimientoStock, TipoMovimiento

    t1 = hacer_venta("Anillo", "1000")
    t2 = hacer_venta("Aro", "500")
    caro = crear_variante("Collar", "2000")
    con_stock(caro, 3)

    cambio, _ = servicio_cambios.iniciar_cambio(
        db, autor, tipo=TipoCambio.COMUN, punto_de_venta_id=local.id,
        codigos_cambio=[t1.codigo_cambio, t2.codigo_cambio.lower()],
    )
    _devolver_todo(db, cambio, t1)
    _devolver_todo(db, cambio, t2)
    servicio_cambios.agregar_item_nuevo(db, cambio, caro.id)

    calculo = servicio_cambios.calcular_diferencia(db, cambio)
    assert calculo["total_devuelto"] == Decimal("1500")
    assert calculo["diferencia"] == Decimal("500")

    efectivo = next(m for m in servicio_medios.listar_medios(db) if m.nombre == "Efectivo")
    servicio_cambios.confirmar_cambio(db, autor, cambio, medio_pago_diferencia_id=efectivo.id)
    db.flush()

    assert {o.codigo for o in cambio.origenes} == {t1.codigo_cambio, t2.codigo_cambio}
    # Cada devolución de stock queda referida a la venta de la que salió.
    referencias = set(db.execute(
        select(MovimientoStock.referencia_venta_id).where(
            MovimientoStock.tipo == TipoMovimiento.DEVOLUCION_VENTA,
            MovimientoStock.notas.like(f"Cambio #{cambio.id}%"),
        )
    ).scalars())
    assert referencias == {t1.id, t2.id}


def test_no_se_devuelve_algo_que_no_es_de_ningun_ticket(db, autor, local, hacer_venta):
    t1 = hacer_venta("Anillo", "1000")
    otra = hacer_venta("Pulsera", "800")
    cambio, _ = servicio_cambios.iniciar_cambio(
        db, autor, tipo=TipoCambio.COMUN, punto_de_venta_id=local.id,
        codigos_cambio=[t1.codigo_cambio],
    )
    item = servicio_cambios.items_del_ticket(db, otra.codigo_cambio)["items"][0]

    with pytest.raises(ReglaDeNegocio, match="ninguno de los tickets"):
        servicio_cambios.agregar_item_devuelto(
            db, cambio, item["variante_id"], item["venta_item_id"]
        )


def test_el_mismo_ticket_no_entra_dos_veces(db, autor, local, hacer_venta):
    t1 = hacer_venta("Anillo", "1000")

    with pytest.raises(ReglaDeNegocio, match="repetido"):
        servicio_cambios.iniciar_cambio(
            db, autor, tipo=TipoCambio.COMUN, punto_de_venta_id=local.id,
            codigos_cambio=[t1.codigo_cambio, t1.codigo_cambio.lower()],
        )

    cambio, _ = servicio_cambios.iniciar_cambio(
        db, autor, tipo=TipoCambio.COMUN, punto_de_venta_id=local.id,
        codigos_cambio=[t1.codigo_cambio],
    )
    with pytest.raises(ReglaDeNegocio, match="ya está en este cambio"):
        servicio_cambios.agregar_origen(db, autor, cambio, t1.codigo_cambio)


def test_tickets_de_clientes_distintos_no_se_juntan(db, autor, local, hacer_venta):
    ana = _cliente(db, autor, "Gómez", "30111222")
    eva = _cliente(db, autor, "Pérez", "30111333")
    de_ana = hacer_venta("Anillo", "1000", cliente=ana)
    de_eva = hacer_venta("Aro", "500", cliente=eva)
    sin_cliente = hacer_venta("Collar", "700")

    with pytest.raises(ReglaDeNegocio, match="clientes distintos"):
        servicio_cambios.iniciar_cambio(
            db, autor, tipo=TipoCambio.COMUN, punto_de_venta_id=local.id,
            codigos_cambio=[de_ana.codigo_cambio, de_eva.codigo_cambio],
        )

    # Uno con cliente y uno sin cliente sí.
    cambio, _ = servicio_cambios.iniciar_cambio(
        db, autor, tipo=TipoCambio.COMUN, punto_de_venta_id=local.id,
        codigos_cambio=[de_ana.codigo_cambio, sin_cliente.codigo_cambio],
    )
    assert len(cambio.origenes) == 2


def test_api_suma_otro_ticket_solo_a_un_cambio_pendiente(
    client, db, autor, local, hacer_venta,
):
    t1 = hacer_venta("Anillo", "1000")
    t2 = hacer_venta("Aro", "500")
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    r = client.post("/api/v1/cambios", json={
        "tipo": "comun", "codigos_cambio": [t1.codigo_cambio], "punto_de_venta_id": local.id,
    })
    assert r.status_code == 201, r.text
    cambio_id = r.json()["id"]

    r = client.post(f"/api/v1/cambios/{cambio_id}/origenes", json={"codigo_cambio": t2.codigo_cambio})
    assert r.status_code == 200, r.text
    assert [o["codigo"] for o in r.json()["origenes"]] == [t1.codigo_cambio, t2.codigo_cambio]

    client.patch(f"/api/v1/cambios/{cambio_id}/cancelar")
    otro = hacer_venta("Collar", "700")
    db.commit()
    r = client.post(f"/api/v1/cambios/{cambio_id}/origenes", json={"codigo_cambio": otro.codigo_cambio})
    assert r.status_code == 409
