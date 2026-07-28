"""Tests del módulo de puntos de venta."""

import pytest

from app.core.permisos import ROL_CUENTA_MAESTRA, ROL_VENDEDOR, Modulo
from app.models.punto_de_venta import TipoPuntoVenta
from app.services import puntos_de_venta as servicio
from app.services.roles import ReglaDeNegocio


@pytest.fixture
def autor(crear_usuario):
    return crear_usuario("admin", ROL_CUENTA_MAESTRA)


def test_solo_un_cd(db, autor):
    servicio.crear_punto(db, autor, "CD Central", TipoPuntoVenta.CD)

    with pytest.raises(ReglaDeNegocio, match="Centro de Distribución"):
        servicio.crear_punto(db, autor, "CD Secundario", TipoPuntoVenta.CD)


def test_codigo_confirmacion_solo_locales(db, autor):
    # En un local: permitido.
    local = servicio.crear_punto(db, autor, "Local Centro", TipoPuntoVenta.LOCAL, "1234")
    assert local.codigo_confirmacion == "1234"

    # En un CD u online: rechazado.
    with pytest.raises(ReglaDeNegocio, match="solo aplica a locales"):
        servicio.crear_punto(db, autor, "Online", TipoPuntoVenta.ONLINE, "1234")


def test_cambiar_a_online_borra_codigo(db, autor):
    local = servicio.crear_punto(db, autor, "Local", TipoPuntoVenta.LOCAL, "1234")
    servicio.editar_punto(db, autor, local.id, tipo=TipoPuntoVenta.ONLINE)
    assert local.codigo_confirmacion is None


def test_no_desactivar_con_dispositivos_activos_sin_confirmar(db, autor):
    from app.models.dispositivo import Dispositivo

    local = servicio.crear_punto(db, autor, "Local", TipoPuntoVenta.LOCAL)
    db.add(Dispositivo(punto_de_venta_id=local.id, descripcion="Cel 1", activo=True))
    db.flush()

    with pytest.raises(ReglaDeNegocio, match="dispositivo"):
        servicio.cambiar_estado(db, autor, local.id, activo=False)

    # Con confirmación explícita, procede.
    servicio.cambiar_estado(db, autor, local.id, activo=False, confirmar=True)
    assert local.activo is False


def test_alta_registra_en_auditoria(db, autor):
    from sqlalchemy import select

    from app.models.auditoria import Auditoria

    servicio.crear_punto(db, autor, "CD", TipoPuntoVenta.CD)

    assert db.execute(
        select(Auditoria).where(Auditoria.accion == "punto_venta.crear")
    ).scalars().first() is not None


def test_endpoint_requiere_configuracion(client, crear_usuario, login):
    """Un vendedor sin permiso de configuración → 403."""
    crear_usuario("juan", ROL_VENDEDOR)
    resp = client.get("/api/v1/puntos-de-venta", headers=login("juan"))
    assert resp.status_code == 403


def test_endpoint_alta_y_listado(client, crear_usuario, roles, dar_permiso, login):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    headers = login("admin")

    alta = client.post(
        "/api/v1/puntos-de-venta",
        json={"nombre": "Local Patio Olmos", "tipo": "local", "codigo_confirmacion": "9876"},
        headers=headers,
    )
    assert alta.status_code == 201
    assert alta.json()["codigo_confirmacion"] == "9876"

    listado = client.get("/api/v1/puntos-de-venta?tipo=local", headers=headers)
    assert listado.status_code == 200
    assert len(listado.json()) == 1
