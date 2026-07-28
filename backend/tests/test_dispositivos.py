"""
Tests del módulo de dispositivos: flujo de identificación y ABM.

Los del flujo de identificación usan el service directamente (con la sesión
de test) y no dependen del middleware, que en tests está apagado.
"""

import uuid as uuid_lib

import pytest
from sqlalchemy import select

from app.core.permisos import ROL_CUENTA_MAESTRA, ROL_VENDEDOR, Modulo
from app.models.auditoria import Auditoria
from app.models.dispositivo import Dispositivo
from app.models.punto_de_venta import TipoPuntoVenta
from app.services import puntos_de_venta as pv_servicio
from app.services.device_service import DeviceService
from app.services.roles import ReglaDeNegocio


@pytest.fixture
def autor(crear_usuario):
    return crear_usuario("admin", ROL_CUENTA_MAESTRA)


@pytest.fixture
def servicio(db):
    return DeviceService(db)


# ============================================================================
# Flujo de identificación
# ============================================================================


def test_crear_dispositivo_nuevo(db, servicio):
    """Sin cookie → dispositivo creado con activo=False, hay que setear cookie."""
    dispositivo, set_cookie = servicio.identificar_dispositivo(None, "fp-123", "1.2.3.4")

    assert dispositivo.activo is False
    assert dispositivo.punto_de_venta_id is None
    assert dispositivo.descripcion == "Sin asignar"
    assert set_cookie is True


def test_recuperar_por_cookie_existente(db, servicio):
    dispositivo, _ = servicio.identificar_dispositivo(None, None, "1.1.1.1")
    uuid = str(dispositivo.uuid)

    recuperado, set_cookie = servicio.identificar_dispositivo(uuid, None, "9.9.9.9")

    assert recuperado.id == dispositivo.id
    # No hace falta reescribir la cookie cuando ya es válida.
    assert set_cookie is False
    assert recuperado.ultima_ip == "9.9.9.9"


def test_restaurar_por_fingerprint(db, servicio, autor):
    # Un dispositivo activo, con fingerprint conocido.
    dispositivo, _ = servicio.identificar_dispositivo(None, "fp-activo", "1.1.1.1")
    dispositivo.activo = True
    db.flush()

    # Otro navegador, sin cookie, con el mismo fingerprint → restaura.
    restaurado, set_cookie = servicio.identificar_dispositivo(None, "fp-activo", "2.2.2.2")

    assert restaurado.id == dispositivo.id
    assert set_cookie is True


def test_no_restaurar_por_fingerprint_inactivo(db, servicio):
    """Fingerprint coincide pero el dispositivo está inactivo → crea uno nuevo."""
    dispositivo, _ = servicio.identificar_dispositivo(None, "fp-inactivo", "1.1.1.1")
    assert dispositivo.activo is False  # nace inactivo

    nuevo, set_cookie = servicio.identificar_dispositivo(None, "fp-inactivo", "2.2.2.2")

    assert nuevo.id != dispositivo.id
    assert set_cookie is True


def test_cookie_invalida_se_trata_como_sin_cookie(db, servicio):
    """Un uuid que no existe en la base no debe romper: crea uno nuevo."""
    inexistente = str(uuid_lib.uuid4())
    dispositivo, set_cookie = servicio.identificar_dispositivo(inexistente, None, "1.1.1.1")

    assert dispositivo.uuid != uuid_lib.UUID(inexistente)
    assert set_cookie is True


# ============================================================================
# Auditoría
# ============================================================================


def test_auditoria_registra_creacion(db, servicio):
    servicio.identificar_dispositivo(None, None, "1.1.1.1")

    assert db.execute(
        select(Auditoria).where(Auditoria.accion == "dispositivo.creado")
    ).scalars().first() is not None


def test_auditoria_registra_restauracion(db, servicio):
    dispositivo, _ = servicio.identificar_dispositivo(None, "fp-x", "1.1.1.1")
    dispositivo.activo = True
    db.flush()
    servicio.identificar_dispositivo(None, "fp-x", "2.2.2.2")

    assert db.execute(
        select(Auditoria).where(Auditoria.accion == "dispositivo.restaurado_por_fingerprint")
    ).scalars().first() is not None


# ============================================================================
# Administración
# ============================================================================


def test_desactivar_dispositivo(db, servicio, autor):
    dispositivo, _ = servicio.identificar_dispositivo(None, None, "1.1.1.1")
    dispositivo.activo = True
    db.flush()

    servicio.desactivar(dispositivo.id, autor.id, "1.1.1.1")

    assert dispositivo.activo is False
    assert db.execute(
        select(Auditoria).where(Auditoria.accion == "dispositivo.desactivado")
    ).scalars().first() is not None


def test_reactivar_dispositivo(db, servicio, autor):
    dispositivo, _ = servicio.identificar_dispositivo(None, None, "1.1.1.1")

    servicio.reactivar(dispositivo.id, autor.id, "1.1.1.1")

    assert dispositivo.activo is True
    assert db.execute(
        select(Auditoria).where(Auditoria.accion == "dispositivo.reactivado")
    ).scalars().first() is not None


def test_solo_locales_en_asignacion(db, servicio, autor):
    """Asignar un punto de venta que no es local → error de negocio."""
    dispositivo, _ = servicio.identificar_dispositivo(None, None, "1.1.1.1")
    cd = pv_servicio.crear_punto(db, autor, "CD", TipoPuntoVenta.CD)

    with pytest.raises(ReglaDeNegocio, match="tipo local"):
        servicio.actualizar(
            dispositivo.id, usuario_id=autor.id, ip="1.1.1.1",
            punto_de_venta_id=cd.id, asignar_local=True,
        )

    # A un local sí lo deja.
    local = pv_servicio.crear_punto(db, autor, "Local", TipoPuntoVenta.LOCAL)
    servicio.actualizar(
        dispositivo.id, usuario_id=autor.id, ip="1.1.1.1",
        punto_de_venta_id=local.id, asignar_local=True,
    )
    assert dispositivo.punto_de_venta_id == local.id


def test_asignar_local_audita(db, servicio, autor):
    dispositivo, _ = servicio.identificar_dispositivo(None, None, "1.1.1.1")
    local = pv_servicio.crear_punto(db, autor, "Local", TipoPuntoVenta.LOCAL)

    servicio.actualizar(
        dispositivo.id, usuario_id=autor.id, ip="1.1.1.1",
        punto_de_venta_id=local.id, asignar_local=True,
    )

    assert db.execute(
        select(Auditoria).where(Auditoria.accion == "dispositivo.asignado_local")
    ).scalars().first() is not None


# ============================================================================
# Endpoints
# ============================================================================


def test_me_crea_dispositivo_y_setea_cookie(client):
    resp = client.get("/api/v1/dispositivos/me")

    assert resp.status_code == 200
    assert resp.json()["activo"] is False
    assert "device_uuid" in resp.cookies


def test_me_con_cookie_reusa_dispositivo(client):
    primera = client.get("/api/v1/dispositivos/me")
    uuid1 = primera.json()["uuid"]

    # El TestClient conserva la cookie: la segunda debe devolver el mismo.
    segunda = client.get("/api/v1/dispositivos/me")
    assert segunda.json()["uuid"] == uuid1


def test_uuid_no_editable(client, db, crear_usuario, login, servicio):
    """PUT con uuid en el body: el uuid no cambia (no es un campo del schema)."""
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    dispositivo, _ = servicio.identificar_dispositivo(None, None, "1.1.1.1")
    db.commit()
    uuid_original = str(dispositivo.uuid)

    resp = client.put(
        f"/api/v1/admin/dispositivos/{dispositivo.id}",
        json={"uuid": str(uuid_lib.uuid4()), "descripcion": "Caja 1"},
        headers=login("admin"),
    )

    assert resp.status_code == 200
    assert resp.json()["uuid"] == uuid_original
    assert resp.json()["descripcion"] == "Caja 1"


def test_admin_requiere_permiso(client, crear_usuario, login):
    crear_usuario("juan", ROL_VENDEDOR)
    resp = client.get("/api/v1/admin/dispositivos", headers=login("juan"))
    assert resp.status_code == 403


def test_admin_activar_desactivar(client, db, crear_usuario, login, servicio):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    dispositivo, _ = servicio.identificar_dispositivo(None, None, "1.1.1.1")
    db.commit()
    headers = login("admin")

    r1 = client.patch(f"/api/v1/admin/dispositivos/{dispositivo.id}/activar", headers=headers)
    assert r1.status_code == 200 and r1.json()["activo"] is True

    r2 = client.patch(f"/api/v1/admin/dispositivos/{dispositivo.id}/desactivar", headers=headers)
    assert r2.status_code == 200 and r2.json()["activo"] is False


def test_response_admin_no_expone_fingerprint(client, db, crear_usuario, login, servicio):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    servicio.identificar_dispositivo(None, "fp-secreto", "1.1.1.1")
    db.commit()

    resp = client.get("/api/v1/admin/dispositivos", headers=login("admin"))
    assert resp.status_code == 200
    assert "fingerprint" not in resp.text
    assert "fp-secreto" not in resp.text
