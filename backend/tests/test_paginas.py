"""
Tests de las páginas HTML.

No prueban la UI, sino que las plantillas Jinja rendericen sin errores y
que la navegación respete la sesión: un error de template solo aparece al
pedir la página, y sin estos tests se descubriría recién en el navegador.
"""

from app.core.permisos import ROL_CUENTA_MAESTRA, ROL_VENDEDOR, Modulo

PAGINAS_CON_SESION = ["/", "/usuarios", "/roles"]


def test_sin_sesion_redirige_al_login(client):
    for url in PAGINAS_CON_SESION:
        resp = client.get(url, follow_redirects=False)
        assert resp.status_code == 303, url
        assert resp.headers["location"] == "/login"


def test_login_se_renderiza(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "Ingresar" in resp.text
    assert "¿Olvidaste tu contraseña?" in resp.text


def test_con_sesion_activa_login_manda_al_dashboard(client, crear_usuario):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    resp = client.get("/login", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_primer_ingreso_va_a_cambiar_password(client, crear_usuario):
    """
    Con el cambio pendiente no se entra a NINGUNA pantalla, no solo al
    dashboard: la regla vive en una única dependency.
    """
    crear_usuario("nuevo", ROL_CUENTA_MAESTRA, ultimo_acceso=None)
    client.post("/api/v1/auth/login", json={"username": "nuevo", "password": "Test1234!"})

    for url in PAGINAS_CON_SESION:
        resp = client.get(url, follow_redirects=False)
        assert resp.status_code == 303, url
        assert resp.headers["location"] == "/cambiar-password", url


def test_dashboard_se_renderiza(client, crear_usuario):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    resp = client.get("/")
    assert resp.status_code == 200
    assert "Bienvenido" in resp.text
    # El badge del usuario logueado sale del contexto, no hardcodeado.
    assert "Admin" in resp.text


def test_paginas_de_gestion_se_renderizan(client, crear_usuario):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    for url in ("/usuarios", "/roles"):
        resp = client.get(url)
        assert resp.status_code == 200, url


def test_arbol_de_permisos_se_renderiza(client, crear_usuario, roles):
    admin = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    # Árbol de un rol.
    resp = client.get(f"/roles/{roles[ROL_VENDEDOR].id}/permisos")
    assert resp.status_code == 200
    assert "arbolPermisos" in resp.text
    assert "Guardar permisos" in resp.text

    # Árbol de overrides de un usuario.
    resp = client.get(f"/usuarios/{admin.id}/permisos")
    assert resp.status_code == 200
    assert "'usuario'" in resp.text  # modo usuario


def test_historial_se_renderiza(client, crear_usuario):
    admin = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    resp = client.get(f"/usuarios/{admin.id}/historial")
    assert resp.status_code == 200
    assert "Historial de accesos" in resp.text


def test_sidebar_se_filtra_por_permisos(client, crear_usuario, roles, dar_permiso):
    """
    El sidebar usa la misma `resolver_permiso` que la API: un vendedor sin
    permisos no ve los ítems de gestión.
    """
    crear_usuario("juan", ROL_VENDEDOR)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.VENTAS, ver=True)
    client.post("/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"})

    resp = client.get("/")
    assert resp.status_code == 200
    assert 'href="/ventas"' in resp.text
    # Sin permiso sobre usuarios ni acceso a roles (exclusivo Cuenta Maestra).
    assert 'href="/usuarios"' not in resp.text
    assert 'href="/roles"' not in resp.text


def test_item_activo_del_sidebar_en_cada_pagina(client, crear_usuario, roles):
    """
    Cada página marca su ítem del menú como activo (la lengüeta que se
    funde con el fondo). Si una ruta olvida pasar `ruta_activa`, el menú
    queda sin nada seleccionado y este test lo detecta.
    """
    admin = crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    rutas = {
        "/": "/",
        "/usuarios": "/usuarios",
        "/roles": "/roles",
        f"/usuarios/{admin.id}/permisos": "/usuarios",
        f"/usuarios/{admin.id}/historial": "/usuarios",
        f"/roles/{roles[ROL_VENDEDOR].id}/permisos": "/roles",
        # Las secciones de configuración mantienen "Configuraciones" activo.
        "/configuracion": "/configuracion",
        "/puntos-de-venta": "/configuracion",
        "/dispositivos": "/configuracion",
    }

    for url, item_esperado in rutas.items():
        resp = client.get(url)
        assert resp.status_code == 200, url
        # Exactamente un ítem activo, y es el que corresponde.
        assert resp.text.count("nav-activo") == 1, url
        assert resp.text.count('aria-current="page"') == 1, url
        activo = resp.text.split('aria-current="page"')[0].rsplit('href="', 1)[1].rstrip('"\n ')
        assert activo == item_esperado, f"{url}: marcó {activo}"


def test_paginas_de_proveedores_se_renderizan(client, crear_usuario):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    listado = client.get("/proveedores")
    assert listado.status_code == 200
    assert "Proveedores" in listado.text
    assert "abmProveedores" in listado.text

    masivo = client.get("/proveedores/dolar-masivo")
    assert masivo.status_code == 200
    assert "dolarMasivo" in masivo.text


def test_paginas_de_puntos_y_dispositivos_se_renderizan(client, crear_usuario):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    puntos = client.get("/puntos-de-venta")
    assert puntos.status_code == 200
    assert "abmPuntos" in puntos.text

    dispositivos = client.get("/dispositivos")
    assert dispositivos.status_code == 200
    assert "abmDispositivos" in dispositivos.text


def test_hub_de_configuraciones(client, crear_usuario):
    """
    La Cuenta Maestra ve las tarjetas de Puntos de venta y Dispositivos
    dentro de Configuraciones, y ya no como ítems sueltos del sidebar.
    """
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    resp = client.get("/configuracion")
    assert resp.status_code == 200
    assert 'href="/puntos-de-venta"' in resp.text
    assert 'href="/dispositivos"' in resp.text

    # En el sidebar (contexto de cualquier página) no están como top-level.
    home = client.get("/")
    aside = home.text.split("<aside")[1].split("</aside>")[0]
    assert "Puntos de venta" not in aside
    assert ">Dispositivos<" not in aside
    assert "Configuraciones" in aside


def test_hub_config_filtra_por_permiso(client, crear_usuario, roles, dar_permiso):
    """
    Un usuario con permiso solo sobre dispositivos ve esa tarjeta pero no
    la de puntos de venta (que requiere configuración).
    """
    crear_usuario("dist", "distribucion")
    dar_permiso(rol_id=roles["distribucion"].id, modulo=Modulo.DISPOSITIVOS, ver=True)
    client.post("/api/v1/auth/login", json={"username": "dist", "password": "Test1234!"})

    resp = client.get("/configuracion")
    assert resp.status_code == 200
    assert 'href="/dispositivos"' in resp.text
    assert 'href="/puntos-de-venta"' not in resp.text


def test_pagina_de_usuario_inexistente_da_404(client, crear_usuario):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    assert client.get("/usuarios/999999/permisos").status_code == 404
