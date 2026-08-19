"""Tests de autenticación: login, tokens, historial y auditoría."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.permisos import ROL_VENDEDOR
from app.models.auditoria import Auditoria
from app.models.usuario import HistorialAcceso, ResultadoAcceso
from app.services import auth as servicio_auth
from config import settings


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


def _vencer_el_access(client):
    """Deja la cookie de acceso vencida, con el refresh intacto."""
    client.cookies.set(
        "soleil_access_token",
        servicio_auth._crear_token({"sub": "1"}, timedelta(minutes=-5), tipo="access"),
    )


def test_la_sesion_se_renueva_sola_cuando_vence_el_access(
    client, crear_usuario
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
    client, crear_usuario
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


def test_no_renueva_si_se_cerro_la_sesion(client, crear_usuario):
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
    client, crear_usuario
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
    client, db, crear_usuario
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


def test_renovar_no_abre_una_sesion_nueva(client, db, crear_usuario):
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
    client, crear_usuario
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


def test_el_logout_no_recibe_una_cookie_nueva(client, crear_usuario):
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


# ============================================================================
# LA SESIÓN VENCE POR INACTIVIDAD
# ============================================================================
#
# Hasta este cambio no vencía nunca: los 30 minutos eran la vida del access
# token, que el middleware renovaba en silencio mientras el refresh de 7 días
# siguiera vivo. La ventana ahora vive en `sesiones.expira_en`, que se corre
# con cada request.


def _sesion_de(db, usuario_nombre="juan"):
    """La fila de `sesiones` del usuario, que es donde vive la ventana."""
    from app.models.sesion import Sesion
    from app.models.usuario import Usuario

    usuario = db.execute(
        select(Usuario).where(Usuario.username == usuario_nombre)
    ).scalar_one()
    return db.execute(
        select(Sesion).where(Sesion.usuario_id == usuario.id)
    ).scalars().first()


def _pasar_inactivo(db, minutos, usuario_nombre="juan"):
    """
    Simula `minutos` sin actividad corriendo la ventana hacia atrás.

    Mover la ventana es exactamente lo que significa "pasó el tiempo": es el
    dato que el servidor mira, y evita tener que congelar el reloj.
    """
    from app.core.utils import ahora_db

    sesion = _sesion_de(db, usuario_nombre)
    sesion.expira_en = ahora_db() + timedelta(
        minutes=settings.SESION_INACTIVIDAD_MINUTOS - minutos
    )
    db.flush()
    return sesion


def _entrar(client, crear_usuario, nombre="juan"):
    crear_usuario(nombre, ROL_VENDEDOR)
    resp = client.post(
        "/api/v1/auth/login", json={"username": nombre, "password": "Test1234!"}
    )
    assert resp.status_code == 200
    return resp.json()


def test_la_sesion_arranca_con_la_ventana_de_inactividad(client, db, crear_usuario):
    """
    `expira_en` es la ventana, no el vencimiento del refresh: si naciera en 7
    días nacería abierta de par en par y no se cerraría nunca — que es
    exactamente como estaba.
    """
    from app.core.utils import ahora_db

    _entrar(client, crear_usuario)
    sesion = _sesion_de(db)

    faltan = (sesion.expira_en - ahora_db()).total_seconds() / 60
    assert settings.SESION_INACTIVIDAD_MINUTOS - 1 < faltan <= settings.SESION_INACTIVIDAD_MINUTOS


def test_pasada_la_ventana_la_sesion_no_se_renueva(
    client, db, crear_usuario
):
    """
    El agujero que este cambio cierra: antes, el primer click después de una
    hora sin hacer nada renovaba el access en silencio y se seguía trabajando.
    """
    _entrar(client, crear_usuario)
    _pasar_inactivo(db, minutos=31)
    _vencer_el_access(client)

    resp = client.get("/api/v1/auth/me")

    assert resp.status_code == 401
    # Y la sesión queda revocada: un refresh copiado tampoco sirve después.
    assert _sesion_de(db).revocada is True


def test_al_vencer_por_inactividad_se_borran_las_cookies(
    client, db, crear_usuario
):
    """
    Sin esto el navegador sigue mandando un refresh muerto en cada request y
    el servidor sigue contestando 401, sin que nada explique por qué.
    """
    _entrar(client, crear_usuario)
    _pasar_inactivo(db, minutos=31)
    _vencer_el_access(client)

    resp = client.get("/api/v1/auth/me")

    borradas = [
        c for c in resp.headers.get_list("set-cookie")
        if c.startswith(("soleil_access_token=", "soleil_refresh_token="))
    ]
    assert len(borradas) == 2, resp.headers.get_list("set-cookie")
    assert all('Max-Age=0' in c or 'expires=Thu, 01 Jan 1970' in c.lower() for c in borradas)


def test_dentro_de_la_ventana_se_sigue_renovando(
    client, db, crear_usuario
):
    """Lo de siempre tiene que seguir andando: 25 minutos no cierran nada."""
    _entrar(client, crear_usuario)
    _pasar_inactivo(db, minutos=25)
    _vencer_el_access(client)

    resp = client.get("/api/v1/auth/me")

    assert resp.status_code == 200
    assert _sesion_de(db).revocada is False


def test_la_ventana_se_corre_con_la_actividad(
    client, db, crear_usuario
):
    """
    Es lo que la hace DESLIZANTE: trabajar a los 25 minutos compra media hora
    más, así que a los 35 desde el login la sesión sigue viva.
    """
    from app.core.utils import ahora_db

    _entrar(client, crear_usuario)
    _pasar_inactivo(db, minutos=25)

    assert client.get("/api/v1/auth/me").status_code == 200

    faltan = (_sesion_de(db).expira_en - ahora_db()).total_seconds() / 60
    assert faltan > settings.SESION_INACTIVIDAD_MINUTOS - 1, "la ventana no se corrió"


def test_la_actividad_cuenta_aunque_el_access_siga_vigente(
    client, db, crear_usuario
):
    """
    Si la ventana se corriera solo al renovar, alguien trabajando sin parar
    media hora vería vencer su sesión igual: su access token vigente nunca
    habría pasado por la renovación.
    """
    _entrar(client, crear_usuario)
    antes = _pasar_inactivo(db, minutos=25).expira_en

    # Sin vencer el access a propósito: es el caso de alguien trabajando.
    assert client.get("/api/v1/auth/me").status_code == 200

    assert _sesion_de(db).expira_en > antes


def test_el_endpoint_de_refresh_tambien_corta(client, db, crear_usuario):
    """
    `/auth/refresh` está excluido del middleware, así que si la regla viviera
    ahí este endpoint seria un desvío para saltearla. Por eso vive en el
    service, que es por donde pasan los dos caminos.
    """
    login = _entrar(client, crear_usuario)
    _pasar_inactivo(db, minutos=31)

    resp = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )

    assert resp.status_code == 401
    assert "inactividad" in resp.json()["detail"].lower()


def test_la_ventana_no_pasa_el_tope_absoluto(db, crear_usuario):
    """
    Una sesión con movimiento cada 20 minutos viviría para siempre si la
    ventana pudiera correrse sin límite. El tope son los 7 días desde que se
    creó, que es lo que dura el refresh token.
    """
    from app.core.utils import ahora_db
    from app.models.sesion import Sesion

    usuario = crear_usuario("ana", ROL_VENDEDOR)
    sesion = Sesion(
        usuario_id=usuario.id,
        jti="jti-de-prueba",
        # Creada hace casi 7 días: le quedan 10 minutos de vida absoluta.
        creada_en=ahora_db() - timedelta(days=settings.JWT_REFRESH_TOKEN_DAYS) + timedelta(minutes=10),
        expira_en=ahora_db() + timedelta(minutes=1),
    )
    db.add(sesion)
    db.flush()

    servicio_auth.registrar_actividad(db, sesion)

    faltan = (sesion.expira_en - ahora_db()).total_seconds() / 60
    assert faltan <= 10.1, "la actividad empujó la sesión más allá del tope"


def test_la_ventana_no_se_escribe_en_cada_request(db, crear_usuario):
    """
    El punto de venta hace muchos requests seguidos y no hace falta un UPDATE
    por cada uno: la ventana se mueve a lo sumo una vez por minuto.
    """
    from app.core.utils import ahora_db
    from app.models.sesion import Sesion

    usuario = crear_usuario("ana", ROL_VENDEDOR)
    sesion = Sesion(
        usuario_id=usuario.id, jti="jti-freno",
        creada_en=ahora_db(),
        expira_en=ahora_db() + timedelta(minutes=settings.SESION_INACTIVIDAD_MINUTOS),
    )
    db.add(sesion)
    db.flush()
    primera = sesion.expira_en

    servicio_auth.registrar_actividad(db, sesion)

    assert sesion.expira_en == primera, "escribió con menos de un minuto de diferencia"


def test_el_access_no_puede_durar_mas_que_la_ventana():
    """
    Si el access durara más que la ventana, un token todavía vigente dejaría
    entrar después de vencida: `get_current_user` lo acepta sin mirar la
    sesión. Los dos valores viven en `config.py` y nada más los ata.
    """
    assert settings.JWT_ACCESS_TOKEN_MINUTES <= settings.SESION_INACTIVIDAD_MINUTOS
