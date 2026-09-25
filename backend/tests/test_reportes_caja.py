"""
Tests de Reportes de Caja: el grupo en el hub de Reportes, los siete
reportes (filtrados por día y local) y su exportación a Excel.
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.permisos import ROL_DUENO, ROL_VENDEDOR
from app.core.utils import ahora_db
from app.models.punto_de_venta import TipoPuntoVenta
from app.services import arqueo as servicio_arqueo
from app.services import clientes as servicio_clientes
from app.services import cobros_joyero as servicio_joyero
from app.services import configuracion as servicio_configuracion
from app.services import medios_pago as servicio_medios
from app.services import novedades_caja as servicio_novedades
from app.services import reportes_caja as servicio
from app.services import retiros as servicio_retiros
from app.services import retiros_mercaderia as servicio_mercaderia
from app.services import senas as servicio_senas
from app.services import turnos as servicio_turnos

# Reusa los fixtures de la sesión 09 (autor, config, local, turno, dueno,
# variante, motivo_empleada): los reportes leen exactamente esos datos.
from tests.test_operaciones_caja import (  # noqa: F401
    autor,
    config,
    dueno,
    local,
    motivo_empleada,
    turno,
    variante,
)


def _hoy():
    return ahora_db().date()


def _medio(db, nombre):
    return next(m for m in servicio_medios.listar_medios(db) if m.nombre == nombre)


@pytest.fixture
def otro_local(crear_punto_de_venta):
    return crear_punto_de_venta("MPJ", "Paseo del Jockey", TipoPuntoVenta.LOCAL)


@pytest.fixture
def autorizador(crear_usuario):
    return crear_usuario("auto", ROL_DUENO, nombre="Autoriza", es_autorizador=True)


def _novedad(db, autor, local, concepto, monto, autorizador):
    return servicio_novedades.registrar_novedad(
        db, autor, punto_de_venta_id=local.id, concepto_id=concepto.id,
        monto=Decimal(monto), autorizador_id=autorizador.id,
    )


# ── Hub ─────────────────────────────────────────────────────────────────────


def test_el_hub_tiene_el_grupo_de_caja_con_sus_siete_reportes(client, db, autor):
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    hub = client.get("/reportes").text
    assert 'href="/reportes/caja"' in hub
    assert "Reportes de Caja" in hub
    assert "Novedades de caja, Arqueos de caja" in hub

    grupo = client.get("/reportes/caja").text
    for slug in ("novedades", "arqueos", "movimientos", "retiros-efectivo",
                 "cobros-joyero", "senas", "retiros-mercaderia"):
        assert f'href="/reportes/caja/{slug}"' in grupo
        assert client.get(f"/reportes/caja/{slug}").status_code == 200

    # Retiros de mercadería se mudó de Producto a Caja.
    assert "/reportes/caja/retiros-mercaderia" not in client.get("/reportes/productos").text
    assert client.get("/reportes/retiros-mercaderia", follow_redirects=False).headers[
        "location"
    ] == "/reportes/caja/retiros-mercaderia"
    assert client.get("/reportes/caja/no-existe").status_code == 404


def test_sin_permiso_de_reportes_no_se_ve_el_grupo_de_caja(client, db, crear_usuario):
    crear_usuario("vende", ROL_VENDEDOR)
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})

    assert 'href="/reportes/caja"' not in client.get("/reportes").text
    assert client.get("/api/v1/reportes/caja/novedades").status_code == 403


# ── Novedades ───────────────────────────────────────────────────────────────


def test_novedades_agrupa_por_turno_con_subtotales(db, autor, local, turno, autorizador):
    gasto = servicio_novedades.crear_concepto(db, autor, "Pago electricista", "salida")
    ingreso = servicio_novedades.crear_concepto(db, autor, "Falla del sistema", "entrada")
    _novedad(db, autor, local, gasto, "200", autorizador)
    _novedad(db, autor, local, gasto, "100", autorizador)
    _novedad(db, autor, local, ingreso, "50", autorizador)

    datos = servicio.novedades(db, _hoy())

    assert len(datos["turnos"]) == 1
    grupo = datos["turnos"][0]
    assert [n["concepto"] for n in grupo["novedades"]] == [
        "Pago electricista", "Pago electricista", "Falla del sistema",
    ]
    assert grupo["total_entradas"] == Decimal("50")
    assert grupo["total_salidas"] == Decimal("300")
    assert grupo["neto"] == Decimal("-250")
    assert datos["neto"] == Decimal("-250")


def test_novedades_filtra_por_local_y_por_dia(
    db, autor, local, otro_local, turno, autorizador,
):
    servicio_turnos.abrir_turno(
        punto_de_venta_id=otro_local.id, usuario_id=autor.id,
        efectivo_apertura=0, notas=None, db=db,
    )
    concepto = servicio_novedades.crear_concepto(db, autor, "Gasto", "salida")
    _novedad(db, autor, local, concepto, "10", autorizador)
    _novedad(db, autor, otro_local, concepto, "20", autorizador)

    assert servicio.novedades(db, _hoy())["total_salidas"] == Decimal("30")
    assert servicio.novedades(db, _hoy(), otro_local.id)["total_salidas"] == Decimal("20")
    assert servicio.novedades(db, _hoy() - timedelta(days=1))["turnos"] == []


# ── Arqueos ─────────────────────────────────────────────────────────────────


def test_arqueos_compara_sistema_contra_contado(db, autor, local, turno):
    esperado = servicio_arqueo.calcular_esperado(turno.id, db)
    items = [{**i, "monto_declarado": i["monto_esperado"]} for i in esperado["items"]]
    efectivo = next(i for i in items if i["medio_nombre"] == "Efectivo")
    efectivo["monto_declarado"] = efectivo["monto_esperado"] - Decimal("150")
    servicio_arqueo.registrar_arqueo(
        turno_id=turno.id, items_declarados=items,
        total_declarado=esperado["total_esperado"] - Decimal("150"),
        usuario_id=autor.id, db=db,
    )

    datos = servicio.arqueos(db, _hoy())

    assert "Efectivo" in datos["columnas"]
    fila = datos["filas"][0]
    item = next(i for i in fila["items"] if i["columna"] == "Efectivo")
    assert item["monto_esperado"] == Decimal("1000")
    assert item["monto_declarado"] == Decimal("850")
    assert item["diferencia"] == Decimal("-150")
    assert fila["diferencia"] == Decimal("-150")


# ── Movimientos ─────────────────────────────────────────────────────────────


def test_movimientos_en_orden_y_cuadran_con_el_arqueo(
    db, autor, local, turno, dueno, autorizador,
):
    servicio_joyero.registrar_cobro(
        db, autor, punto_de_venta_id=local.id, medio_de_pago_id=_medio(db, "Efectivo").id,
        monto_efectivo=Decimal("500"), monto_otros=Decimal("600"),
    )
    concepto = servicio_novedades.crear_concepto(db, autor, "Gasto", "salida")
    _novedad(db, autor, local, concepto, "100", autorizador)
    servicio_retiros.registrar_retiro(
        db, autor, punto_de_venta_id=local.id, monto=Decimal("300"), codigo="1234"
    )

    grupo = servicio.movimientos(db, _hoy())["turnos"][0]

    assert [m["tipo"] for m in grupo["movimientos"]] == [
        "apertura", "cobro_joyero", "novedad", "retiro_efectivo",
    ]
    assert grupo["total_ingresos"] == Decimal("1500")
    assert grupo["total_egresos"] == Decimal("400")
    # Todo fue en efectivo: ingresos − egresos es lo que tiene que haber.
    assert grupo["efectivo_esperado"] == Decimal("1100")
    assert grupo["efectivo_esperado"] == servicio_arqueo.efectivo_esperado(turno.id, db)


# ── Retiros de efectivo y cobros de joyero ──────────────────────────────────


def test_retiros_de_efectivo_con_persona_y_total(db, autor, local, turno, dueno):
    servicio_retiros.registrar_retiro(
        db, autor, punto_de_venta_id=local.id, monto=Decimal("300"), codigo="1234"
    )
    servicio_retiros.registrar_retiro(
        db, autor, punto_de_venta_id=local.id, monto=Decimal("200"), codigo="1234"
    )

    datos = servicio.retiros_efectivo(db, _hoy(), local.id)

    assert [f["usuario_nombre"] for f in datos["filas"]] == [dueno.nombre, dueno.nombre]
    assert datos["total"] == Decimal("500")


def test_cobros_de_joyero_con_total_por_medio(db, autor, local, turno):
    for medio, reclamo in (("Efectivo", None), ("Débito", "R-1"), ("Débito", "R-2")):
        servicio_joyero.registrar_cobro(
            db, autor, punto_de_venta_id=local.id, medio_de_pago_id=_medio(db, medio).id,
            monto_efectivo=Decimal("500"), monto_otros=Decimal("600"), numero_reclamo=reclamo,
        )

    datos = servicio.cobros_joyero(db, _hoy())

    assert len(datos["filas"]) == 3
    assert datos["filas"][0]["vendedora_nombre"] == autor.nombre
    assert {t["medio_de_pago"]: t["monto"] for t in datos["totales_por_medio"]} == {
        "Débito": Decimal("1200"), "Efectivo": Decimal("500"),
    }
    assert datos["total"] == Decimal("1700")


# ── Señas ───────────────────────────────────────────────────────────────────


def test_senas_activa_usada_y_vencida(db, autor, config):
    cliente = servicio_clientes.crear_cliente(db, autor, nombre="Leandra", dni="39059158")
    activa = servicio_senas.registrar_sena(db, autor, cliente_id=cliente.id, monto=Decimal("1000"))
    usada = servicio_senas.registrar_sena(db, autor, cliente_id=cliente.id, monto=Decimal("500"))
    servicio_senas.consumir(db, autor, usada, Decimal("500"))
    db.flush()

    datos = servicio.senas(db, _hoy())
    estados = {f["id"]: f["estado"] for f in datos["filas"]}
    assert estados == {activa.id: "activa", usada.id: "usada"}
    assert datos["filas"][0]["fecha_vencimiento"] == _hoy() + timedelta(days=config.dias_vigencia_sena)
    assert datos["total_saldo"] == Decimal("1000")

    # Con vigencia de 1 día, una seña de hace 3 días con saldo está vencida.
    servicio_configuracion.cambiar_dias_vigencia_sena(db, autor.id, 1)
    activa.created_at = activa.created_at - timedelta(days=3)
    db.flush()
    hace_tres = _hoy() - timedelta(days=3)
    assert [f["estado"] for f in servicio.senas(db, hace_tres)["filas"]] == ["vencida"]
    assert servicio.senas(db, hace_tres, "activa")["filas"] == []


# ── Retiros de mercadería ───────────────────────────────────────────────────


def test_mercaderia_agrupa_por_empleada_con_subtotal(
    db, autor, local, turno, variante, motivo_empleada, crear_usuario,
):
    empleada = crear_usuario("zoe", ROL_VENDEDOR, nombre="Zoe")
    for _ in range(2):
        servicio_mercaderia.registrar_retiro(
            db, autor, punto_de_venta_id=local.id, variante_id=variante.id,
            empleada_usuario_id=empleada.id,
        )
    servicio_mercaderia.registrar_retiro(
        db, autor, punto_de_venta_id=local.id, variante_id=variante.id,
        empleada_nombre="Ana de la otra",
    )

    datos = servicio.retiros_mercaderia(db, _hoy())

    assert [g["empleada_nombre"] for g in datos["empleadas"]] == ["Zoe", "Ana de la otra"]
    zoe = datos["empleadas"][0]
    assert len(zoe["retiros"]) == 2
    assert zoe["subtotal_lista"] == Decimal("20000")
    assert zoe["subtotal"] == Decimal("14000")
    assert datos["total"] == Decimal("21000")


# ── API y Excel ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "slug",
    ["novedades", "arqueos", "movimientos", "retiros-efectivo",
     "cobros-joyero", "senas", "retiros-mercaderia"],
)
def test_cada_reporte_responde_y_exporta(client, db, autor, config, local, turno, slug):
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    resp = client.get(f"/api/v1/reportes/caja/{slug}?fecha={_hoy().isoformat()}")
    assert resp.status_code == 200, resp.text
    if slug != "senas":
        assert any(o["id"] == local.id for o in resp.json()["opciones_locales"])

    excel = client.get(f"/api/v1/reportes/caja/{slug}/exportar")
    assert excel.status_code == 200
    assert excel.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert excel.content[:2] == b"PK"


def test_api_movimientos_trae_la_apertura(client, db, autor, local, turno):
    db.commit()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    datos = client.get(f"/api/v1/reportes/caja/movimientos?punto_de_venta_id={local.id}").json()
    apertura = datos["turnos"][0]["movimientos"][0]
    assert apertura["tipo"] == "apertura"
    assert Decimal(apertura["ingreso"]) == Decimal("1000")


def test_vigencia_de_senas_se_cambia_por_api_y_queda_auditada(client, db, autor, config):
    from sqlalchemy import select

    from app.models.auditoria import Auditoria

    db.commit()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    assert client.get("/api/v1/configuracion/vigencia-senas").json() == {"dias": 30}
    assert client.put("/api/v1/configuracion/vigencia-senas", json={"dias": 0}).status_code == 422
    assert client.put("/api/v1/configuracion/vigencia-senas", json={"dias": 45}).json() == {"dias": 45}
    assert db.execute(
        select(Auditoria).where(Auditoria.accion == "configuracion.vigencia_senas")
    ).scalar_one_or_none() is not None
