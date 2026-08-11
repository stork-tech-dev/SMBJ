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


# ============================================================================
# RENOVACIÓN AUTOMÁTICA DE LA SESIÓN (AuthRefreshMiddleware)
# ============================================================================


class _SesionDeTest:
    """
    La sesión del test, con `close()` desactivado.

    El middleware no puede usar `Depends`, así que abre y cierra la suya. Acá
    se le pasa la del test —la de él no vería nada, porque los datos del login
    viven en una transacción que nunca se commitea— y se le saca el `close()`,
    que cerraría la sesión que el fixture todavía necesita.
    """

    def __init__(self, sesion):
        self._sesion = sesion

    def __getattr__(self, nombre):
        return getattr(self._sesion, nombre)

    def close(self):
        pass


@pytest.fixture
def middleware_ve_la_base(monkeypatch, db):
    from app.middleware import auth_refresh_middleware as mw

    monkeypatch.setattr(mw, "SessionLocal", lambda: _SesionDeTest(db))


def _vencer_el_access(client):
    """Deja la cookie de acceso vencida, con el refresh intacto."""
    client.cookies.set(
        "soleil_access_token",
        servicio_auth._crear_token({"sub": "1"}, timedelta(minutes=-5), tipo="access"),
    )


def test_la_sesion_se_renueva_sola_cuando_vence_el_access(
    client, crear_usuario, middleware_ve_la_base
):
    """
    El corazón del cambio: con el access vencido y el refresh vivo, se sigue
    trabajando sin volver a loguearse.

    Antes de esto la sesión duraba 30 minutos contados desde el login —no
    desde la última actividad— y el refresh de 7 días no lo usaba nadie.
    """
    crear_usuario("juan", ROL_VENDEDOR)
    client.post("/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"})

    _vencer_el_access(client)
    resp = client.get("/api/v1/auth/me")

    assert resp.status_code == 200
    assert resp.json()["username"] == "juan"
    # Y se llevó una cookie nueva, para no renovar en cada request.
    assert "soleil_access_token" in resp.cookies


def test_la_renovacion_tambien_vale_para_las_paginas(
    client, crear_usuario, middleware_ve_la_base
):
    """
    Las páginas HTML no pasan por el mismo camino que la API —usan
    `requiere_sesion`, que redirige a /login en vez de dar 401—, así que se
    prueban aparte: es donde más se nota si deja de andar.
    """
    crear_usuario("juan", ROL_VENDEDOR)
    client.post("/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"})

    _vencer_el_access(client)
    resp = client.get("/", follow_redirects=False)

    assert resp.status_code == 200, "la página redirigió al login en vez de renovar"


def test_no_renueva_si_se_cerro_la_sesion(client, crear_usuario, middleware_ve_la_base):
    """
    El test que protege el logout. Si el middleware renovara sin mirar
    `sesiones.revocada`, cerrar sesión no serviría de nada: alcanzaría con
    esperar a que venza el access para volver a entrar con la cookie vieja.
    """
    crear_usuario("juan", ROL_VENDEDOR)
    login = client.post(
        "/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"}
    ).json()

    # Control positivo: con la sesión viva, este mismo pedido se renueva. Sin
    # él el test daría verde aunque el middleware no existiera, porque un 401
    # es también lo que pasa cuando no hay ninguna renovación.
    _vencer_el_access(client)
    assert client.get("/api/v1/auth/me").status_code == 200

    client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": login["refresh_token"]},
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )

    # La cookie de refresh sigue en el navegador, pero su sesión está revocada.
    client.cookies.set("soleil_refresh_token", login["refresh_token"])
    _vencer_el_access(client)

    assert client.get("/api/v1/auth/me").status_code == 401


def test_no_renueva_con_el_refresh_tambien_vencido(
    client, crear_usuario, middleware_ve_la_base
):
    """Los 7 días son el techo: pasados, se vuelve a entrar."""
    crear_usuario("juan", ROL_VENDEDOR)
    client.post("/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"})

    _vencer_el_access(client)
    client.cookies.set(
        "soleil_refresh_token",
        servicio_auth._crear_token(
            {"sub": "1", "jti": "x"}, timedelta(days=-1), tipo="refresh"
        ),
    )

    assert client.get("/api/v1/auth/me").status_code == 401


def test_no_renueva_a_un_usuario_desactivado(
    client, db, crear_usuario, middleware_ve_la_base
):
    """
    Dar de baja a alguien tiene que sacarlo, no esperar 7 días. Lo controla
    `refrescar_access_token`, que es la misma función del endpoint.
    """
    usuario = crear_usuario("juan", ROL_VENDEDOR)
    client.post("/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"})

    # Control positivo, por el mismo motivo que en el test del logout.
    _vencer_el_access(client)
    assert client.get("/api/v1/auth/me").status_code == 200

    usuario.activo = False
    db.flush()

    _vencer_el_access(client)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_renovar_no_abre_una_sesion_nueva(client, db, crear_usuario, middleware_ve_la_base):
    """
    Sigue siendo la MISMA sesión: si cada renovación insertara una fila,
    `sesiones` crecería una por usuario cada 30 minutos y el logout dejaría
    de alcanzar para cerrarlas todas.
    """
    from app.models.sesion import Sesion

    crear_usuario("juan", ROL_VENDEDOR)
    client.post("/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"})
    antes = len(db.execute(select(Sesion)).scalars().all())

    _vencer_el_access(client)
    client.get("/api/v1/auth/me")
    client.get("/api/v1/auth/me")

    assert len(db.execute(select(Sesion)).scalars().all()) == antes


def test_el_bearer_vencido_no_lo_tapa_la_cookie(
    client, crear_usuario, middleware_ve_la_base
):
    """
    Una credencial explícita manda: si alguien manda un Bearer vencido, la
    respuesta es 401 y no una sesión sacada de la cookie del navegador, que
    podría ser de otro usuario.
    """
    crear_usuario("juan", ROL_VENDEDOR)
    client.post("/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"})

    vencido = servicio_auth._crear_token({"sub": "1"}, timedelta(minutes=-5), tipo="access")
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {vencido}"})

    assert resp.status_code == 401


def test_el_logout_no_recibe_una_cookie_nueva(client, crear_usuario, middleware_ve_la_base):
    """
    El middleware corre DESPUÉS del handler para agregar la cookie, así que
    sin la comprobación de "el handler ya la tocó" le devolvería al usuario un
    access token válido por 30 minutos justo al cerrar sesión.
    """
    crear_usuario("juan", ROL_VENDEDOR)
    login = client.post(
        "/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"}
    ).json()

    _vencer_el_access(client)
    resp = client.post("/api/v1/auth/logout", json={"refresh_token": login["refresh_token"]})

    assert resp.status_code == 200, "el logout tiene que funcionar con el access vencido"
    # La única cookie de acceso que emite es la que la borra.
    cookies = [v for k, v in resp.headers.items() if k.lower() == "set-cookie"]
    de_acceso = [c for c in cookies if c.startswith("soleil_access_token=")]
    assert de_acceso, "el logout tiene que borrar la cookie"
    assert all('soleil_access_token=""' in c or "Max-Age=0" in c for c in de_acceso), (
        f"el logout devolvió una cookie de acceso viva: {de_acceso}"
    )


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
