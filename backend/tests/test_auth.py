"""Tests de autenticación: login, tokens, historial y auditoría."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.permisos import ROL_VENDEDOR
from app.models.auditoria import Auditoria
from app.models.usuario import HistorialAcceso, ResultadoAcceso
from app.services import auth as servicio_auth


def test_login_exitoso(client, crear_usuario):
    crear_usuario("juan", ROL_VENDEDOR)

    resp = client.post(
        "/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"}
    )

    assert resp.status_code == 200
    cuerpo = resp.json()
    assert cuerpo["usuario"]["username"] == "juan"
    assert cuerpo["access_token"]
    assert cuerpo["refresh_token"]
    # El token también viaja en cookie HttpOnly, que es lo que usa HTMX.
    assert "soleil_access_token" in resp.cookies


def test_login_password_incorrecta(client, crear_usuario):
    crear_usuario("juan", ROL_VENDEDOR)

    resp = client.post(
        "/api/v1/auth/login", json={"username": "juan", "password": "incorrecta"}
    )

    assert resp.status_code == 401
    # El mensaje no revela si el usuario existe.
    assert resp.json()["detail"] == "Usuario o contraseña incorrectos"


def test_login_usuario_inexistente_mismo_mensaje(client):
    resp = client.post(
        "/api/v1/auth/login", json={"username": "nadie", "password": "loquesea"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Usuario o contraseña incorrectos"


def test_login_usuario_inactivo(client, crear_usuario):
    crear_usuario("juan", ROL_VENDEDOR, activo=False)

    resp = client.post(
        "/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"}
    )
    assert resp.status_code == 401


def test_intento_exitoso_queda_registrado(client, db, crear_usuario):
    """Criterio: todo login queda en historial_accesos Y en auditoria."""
    usuario = crear_usuario("juan", ROL_VENDEDOR)
    client.post("/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"})

    accesos = db.execute(
        select(HistorialAcceso).where(HistorialAcceso.usuario_id == usuario.id)
    ).scalars().all()
    assert len(accesos) == 1
    assert accesos[0].resultado == ResultadoAcceso.EXITOSO

    auditorias = db.execute(
        select(Auditoria).where(Auditoria.accion == "auth.login")
    ).scalars().all()
    assert len(auditorias) == 1
    assert auditorias[0].usuario_id == usuario.id


def test_intento_fallido_queda_registrado(client, db, crear_usuario):
    usuario = crear_usuario("juan", ROL_VENDEDOR)
    client.post("/api/v1/auth/login", json={"username": "juan", "password": "mal"})

    accesos = db.execute(
        select(HistorialAcceso).where(HistorialAcceso.usuario_id == usuario.id)
    ).scalars().all()
    assert len(accesos) == 1
    assert accesos[0].resultado == ResultadoAcceso.FALLIDO
    assert accesos[0].detalle == "Contraseña incorrecta"

    assert db.execute(
        select(Auditoria).where(Auditoria.accion == "auth.login_fallido")
    ).scalars().first() is not None


def test_login_de_usuario_inexistente_va_solo_a_auditoria(client, db):
    """historial_accesos tiene FK NOT NULL: sin usuario, solo queda en auditoria."""
    client.post("/api/v1/auth/login", json={"username": "fantasma", "password": "x"})

    registro = db.execute(
        select(Auditoria).where(Auditoria.accion == "auth.login_fallido")
    ).scalars().one()
    assert registro.usuario_id is None
    assert registro.estado_nuevo["username"] == "fantasma"


def test_token_expirado_da_401(client, crear_usuario, monkeypatch):
    """Criterio de aceptación: token expirado → 401."""
    crear_usuario("juan", ROL_VENDEDOR)

    token_vencido = servicio_auth._crear_token(
        {"sub": "1"}, timedelta(minutes=-5), tipo="access"
    )

    resp = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token_vencido}"}
    )
    assert resp.status_code == 401
    assert "expirado" in resp.json()["detail"].lower()


def test_refresh_token_no_sirve_como_access(client, crear_usuario):
    crear_usuario("juan", ROL_VENDEDOR)
    resp = client.post(
        "/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"}
    )
    refresh = resp.json()["refresh_token"]

    # Usar el refresh como si fuera access debe fallar.
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh}"})
    assert resp.status_code == 401


def test_refresh_emite_access_nuevo(client, crear_usuario):
    crear_usuario("juan", ROL_VENDEDOR)
    login = client.post(
        "/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"}
    ).json()

    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_logout_invalida_el_refresh(client, crear_usuario):
    crear_usuario("juan", ROL_VENDEDOR)
    login = client.post(
        "/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"}
    ).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    assert (
        client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": login["refresh_token"]},
            headers=headers,
        ).status_code
        == 200
    )

    # El refresh ya no sirve.
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert resp.status_code == 401


def test_primer_login_exige_cambio_de_password(client, crear_usuario):
    """ultimo_acceso NULL = usuario recién creado que nunca ingresó."""
    crear_usuario("nuevo", ROL_VENDEDOR, ultimo_acceso=None)

    resp = client.post(
        "/api/v1/auth/login", json={"username": "nuevo", "password": "Test1234!"}
    )
    assert resp.json()["usuario"]["debe_cambiar_password"] is True


def test_cambiar_password_completa_el_primer_ingreso(client, crear_usuario):
    crear_usuario("nuevo", ROL_VENDEDOR, ultimo_acceso=None)
    login = client.post(
        "/api/v1/auth/login", json={"username": "nuevo", "password": "Test1234!"}
    ).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    resp = client.post(
        "/api/v1/auth/cambiar-password",
        json={"password_actual": "Test1234!", "password_nueva": "NuevaClave99!"},
        headers=headers,
    )
    assert resp.status_code == 200

    # Con la contraseña nueva ya no debe cambiarla.
    resp = client.post(
        "/api/v1/auth/login", json={"username": "nuevo", "password": "NuevaClave99!"}
    )
    assert resp.status_code == 200
    assert resp.json()["usuario"]["debe_cambiar_password"] is False


def test_forgot_password_sin_email_no_falla(client, crear_usuario):
    """Criterio: la recuperación solo aplica si hay email, pero nunca revela nada."""
    crear_usuario("sinmail", ROL_VENDEDOR, email=None)

    resp = client.post("/api/v1/auth/forgot-password", json={"username": "sinmail"})
    assert resp.status_code == 200


def test_forgot_password_usuario_inexistente_misma_respuesta(client, crear_usuario):
    con_mail = client.post("/api/v1/auth/forgot-password", json={"username": "fantasma"})
    assert con_mail.status_code == 200


def test_reset_password_token_de_un_solo_uso(client, db, crear_usuario):
    usuario = crear_usuario("juan", ROL_VENDEDOR, email="juan@test.local")
    token = servicio_auth.generar_token_reset(usuario)

    primera = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password_nueva": "Clave12345!"}
    )
    assert primera.status_code == 200

    # El mismo token no sirve dos veces.
    segunda = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password_nueva": "Otra12345!"}
    )
    assert segunda.status_code == 400


def test_hash_password_no_es_reversible():
    hash_ = servicio_auth.hash_password("Secreta123!")
    assert hash_ != "Secreta123!"
    assert servicio_auth.verificar_password("Secreta123!", hash_) is True
    assert servicio_auth.verificar_password("otra", hash_) is False


@pytest.mark.parametrize("hash_roto", ["", "no-es-un-hash", "$2b$12$corto"])
def test_verificar_password_con_hash_invalido_no_explota(hash_roto):
    assert servicio_auth.verificar_password("cualquiera", hash_roto) is False
