"""
Tests de las páginas HTML.

No prueban la UI, sino que las plantillas Jinja rendericen sin errores y
que la navegación respete la sesión: un error de template solo aparece al
pedir la página, y sin estos tests se descubriría recién en el navegador.
"""

import re

from app.core.permisos import ROL_CUENTA_MAESTRA, ROL_DUENO, ROL_VENDEDOR, Modulo

PAGINAS_CON_SESION = ["/", "/usuarios", "/roles"]


def test_sin_sesion_redirige_al_login(client):
    for url in PAGINAS_CON_SESION:
        resp = client.get(url, follow_redirects=False)
        assert resp.status_code == 303, url
        assert resp.headers["location"] == "/login"


def test_login_se_renderiza(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "Iniciar Sesión" in resp.text
    assert "¿Olvidé mi contraseña?" in resp.text
    assert "RECUPERAR" in resp.text


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
    # El título dice de quién es el historial: al pasar al encabezado común
    # se acortó ("Accesos: X") porque ese estilo es mucho más grande y el
    # texto largo partía en dos líneas.
    assert "Accesos:" in resp.text
    assert admin.nombre in resp.text


def test_la_cabecera_del_sidebar_identifica_la_cuenta_logueada(client, crear_usuario):
    """
    Según el grupo "HeaderLateral" del Figma: el logo centrado y, debajo, el
    nombre de quien está operando alineado al borde DERECHO del logo. El
    nombre importa: en un local con varias personas usando la misma máquina,
    es lo que dice de quién es la sesión antes de tocar nada.
    """
    crear_usuario("juan", ROL_CUENTA_MAESTRA, nombre="Juan Pérez")
    client.post("/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"})

    html = client.get("/").text
    cabecera = html.split('id="sidebar-nav"')[1].split("<nav")[0]

    assert 'role="img"' in cabecera, "el logo no está en la cabecera del sidebar"
    assert "Juan Pérez" in cabecera, "falta el nombre de la cuenta logueada"
    assert cabecera.index('role="img"') < cabecera.index("Juan Pérez"), (
        "el nombre tiene que ir DEBAJO del logo"
    )
    assert "justify-center" in cabecera, "el bloque dejó de estar centrado"

    # El nombre se alinea a la derecha DEL LOGO, no del sidebar: por eso el
    # `text-right` va en el mismo contenedor que le da el ancho al logo.
    assert "text-right" in cabecera.split("Juan Pérez")[0].rsplit("<p", 1)[1]


def test_el_logo_del_sidebar_se_dimensiona_por_ancho(client, crear_usuario):
    """
    Regresión: con el alto fijo, el logo de Soleil —un triángulo mucho más
    ancho que el de Mallorca— se desbordaba de los 290px del sidebar. Se
    dimensiona por ancho para que los dos entren sin deformarse.

    La clase sale de una variable del macro, así que Jinja la emite escapada
    (`[&amp;&gt;svg]`). El navegador la decodifica y el selector funciona
    igual, pero acá hay que deshacer el escape para compararla.
    """
    import html as escape_html

    crear_usuario("juan", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"})

    pagina = escape_html.unescape(client.get("/").text)
    cabecera = pagina.split('id="sidebar-nav"')[1].split("<nav")[0]

    assert "[&>svg]:w-full" in cabecera
    assert "[&>svg]:h-full" not in cabecera


def test_todas_las_tablas_usan_el_mismo_alto_de_fila():
    """
    Las tablas de los listados están escritas a mano en cada plantilla, no
    con el macro `components/table.html`, así que el alto de fila puede
    divergir de una pantalla a otra sin que nada falle.

    El valor (`py-3`, 0.75rem) es además el que ya usaba el macro: las
    tablas escritas a mano venían con `py-5` y se veían más aireadas que
    las del componente.
    """
    from pathlib import Path

    paginas = Path(__file__).resolve().parents[1] / "app" / "templates" / "pages"
    celdas = re.compile(r"<td[^>]*\bclass=\"[^\"]*?\bpy-(\d+)\b")

    altos = {}
    for plantilla in sorted(paginas.rglob("listado.html")):
        for alto in celdas.findall(plantilla.read_text()):
            altos.setdefault(alto, []).append(plantilla.name)

    # `py-16` es la fila de "Sin resultados", que no es una fila de datos.
    de_datos = {k: v for k, v in altos.items() if k != "16"}
    assert list(de_datos) == ["3"], f"hay altos de fila distintos entre tablas: {de_datos}"


def test_en_edicion_el_proveedor_se_muestra_como_dato_y_no_como_select(client, crear_usuario):
    """
    El proveedor no se puede cambiar al editar, y no es una regla de la
    pantalla: `ProductoActualizar` no tiene el campo y `actualizar_producto()`
    tampoco lo recibe, porque movería la base del precio sin dejar rastro.

    Antes eso se resolvía con el select deshabilitado, que se veía igual que
    uno roto: no se desplegaba y nada explicaba por qué. Ahora en edición se
    muestra el nombre con su motivo, y el desplegable existe solo en el alta.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    assert ':disabled="!!form.id"' not in html, "volvió el select deshabilitado"
    assert 'x-text="nombreProveedor()"' in html, "falta el proveedor como dato fijo"
    assert "No se cambia" in html, "falta la explicación de por qué no se cambia"


def test_el_buscador_de_productos_no_promete_lo_que_no_hace(client, crear_usuario):
    """
    Regresión: el label accesible decía "SKU o descripción" pero el campo
    estaba atado a `filtros.descripcion`, que en el backend busca solo sobre
    `Producto.descripcion`. Ni el SKU ni el código de la etiqueta encontraban
    nada, y nada lo delataba.

    Ahora es un solo campo `busqueda` que el backend desambigua en las tres
    formas. Este test ata el texto visible a lo que el campo realmente manda.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    assert 'x-model="filtros.busqueda"' in html
    assert "filtros.descripcion" not in html, "el buscador volvió al filtro de descripción"

    # Lo que dice el label y el placeholder tiene que ser lo que resuelve.
    assert html.count("Código, SKU o descripción") == 2


def test_la_tabla_de_productos_lista_variantes(client, crear_usuario):
    """
    Cada fila es una variante: es lo que tiene stock propio y lo que dice la
    etiqueta. El SKU no es columna porque no aparece impreso en ningún lado.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    assert 'x-for="v in variantes"' in html
    # El código va con el dígito verificador, como en la etiqueta.
    assert "v.codigo_completo + v.verificador" in html
    assert ">Stock</th>" in html
    # El contador cuenta variantes, así que no puede decir "productos".
    assert "códigos encontrados" in html


def test_el_alto_del_header_y_el_ancho_del_sidebar_viven_en_un_solo_lugar():
    """
    Los dos valores estaban escritos por duplicado: como variable CSS en
    custom.css y como literal en la config de Tailwind. La variable no la
    usaba nadie, así que cambiar el alto tocando solo la config dejaba a la
    otra copia mintiendo — y eso no falla en ningún lado, simplemente queda
    un valor viejo esperando a confundir.

    Ahora la config los consume con var(). Este test impide volver al
    literal, que es un cambio que nada más delataría.
    """
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1] / "app"
    config = (raiz / "templates" / "components" / "_tailwind_config.html").read_text()
    css = (raiz / "static" / "css" / "custom.css").read_text()

    bloque = re.search(r"spacing:\s*\{(.*?)\}", config, flags=re.S).group(1)
    for token in ("sidebar", "header"):
        assert f"{token}: 'var(--" in bloque, (
            f"`{token}` volvió a un literal en la config en vez de la variable"
        )

    # Y la variable tiene que existir de verdad, o `var()` no resuelve nada.
    assert "--sidebar-width:" in css
    assert "--header-height:" in css


def test_toda_pantalla_interna_tiene_como_volver():
    """
    Una pantalla a la que se llega desde otra tiene que ofrecer el camino de
    vuelta, y siempre el mismo: el botón del macro `encabezado`.

    `/roles/{id}/permisos` tenía en su lugar un breadcrumb propio —enlazaba
    bien, pero no se parecía al resto y pasaba desapercibido—, y lo mismo las
    dos pantallas de usuario. `dolar_masivo` tenía las dos cosas a la vez.

    Se excluye `index.html` (el home, que no cuelga de nada) y las pantallas
    que se abren desde el sidebar, que no tienen "anterior".
    """
    from pathlib import Path

    paginas = Path(__file__).resolve().parents[1] / "app" / "templates" / "pages"
    # Las que se alcanzan desde otra pantalla, no desde el menú.
    internas = [
        "roles/permisos.html",
        "usuarios/permisos.html",
        "usuarios/historial.html",
        "proveedores/dolar_masivo.html",
        "categorias/arbol.html",
    ]

    for relativa in internas:
        contenido = (paginas / relativa).read_text()
        assert "volver_url=" in contenido, f"{relativa}: no ofrece cómo volver"
        # Un breadcrumb propio al lado del botón serían dos caminos iguales.
        assert 'aria-hidden="true">/<' not in contenido, (
            f"{relativa}: tiene un breadcrumb además del botón de volver"
        )


def test_la_tabla_nombra_las_variantes_con_su_descripcion(client, crear_usuario):
    """
    Antes decía "variante R", que no dice si la R es de rojo, de rebajado o
    del talle. Ahora muestra el texto que se carga al crear la variante.

    Y tiene que existir la edición: las variantes creadas antes de esto no
    tienen nombre, y sin editarlas habría que borrarlas —lo que invalida la
    etiqueta ya impresa— para poder ponérselo.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    assert 'x-text="v.descripcion_sufijo"' in html
    assert "'variante ' + v.sufijo" not in html, "volvió el texto armado con el sufijo"

    # El campo en el alta y el modal de edición.
    assert 'id="va-nombre"' in html
    assert 'id="ev-nombre"' in html
    assert "guardarEdicionVariante()" in html


def test_ver_abre_el_panel_acotado_a_la_variante_de_la_fila(client, crear_usuario):
    """
    El listado es por variante, así que "ver" se toca sobre un código
    concreto. Mostrar además las hermanas obligaba a buscar de nuevo cuál
    era la que se había tocado.

    El panel sigue cargando el producto entero —lo necesita para las fotos y
    para dar de alta variantes— pero muestra solo la elegida, y avisa cuántas
    quedan fuera para no dar a entender que es la única.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    assert "varianteId: v.id" in html, "'ver' no le pasa la variante de la fila"
    assert 'x-for="v in variantesVisibles()"' in html, "el panel sigue listando todas"
    assert "variantesOcultas()" in html, "falta el aviso de las variantes restantes"


def test_los_dos_selectores_de_categoria_muestran_el_camino_completo(client, crear_usuario):
    """
    El filtro del listado y el selector del formulario tienen que decir lo
    mismo. El del formulario mostraba solo la hoja con sangría de puntos
    ("· · Deportivas"), y dos ramas distintas pueden tener hojas con el mismo
    nombre: al elegir, no había forma de saber cuál se había elegido.

    Los dos usan `rutaCategoria()`, que arma "Calzado - Zapatillas -
    Deportivas" con la lista que ya está en memoria.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text
    assert html.count('x-text="rutaCategoria(c)"') == 2, (
        "los dos selectores de categoría tienen que usar el camino completo"
    )
    # La sangría con puntos era lo que los hacía distintos.
    assert ".repeat(" not in html


def test_agregar_variante_usa_un_formulario_y_no_un_prompt(client, crear_usuario):
    """
    El alta de variante se hacía con `window.prompt()`: no validaba el sufijo,
    no dejaba cargar la ubicación ni el stock mínimo —que el endpoint sí
    acepta— y no avisaba de que la primera variante elimina la BASE, con lo
    que el código ya impreso queda sin producto.

    Un prompt no falla ningún test por sí solo, así que la regresión se cuida
    acá: si alguien lo reintroduce, esto se pone en rojo.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    assert "window.prompt" not in html and "prompt(" not in html

    # Los tres campos del formulario, incluidos los dos que el prompt perdía.
    for campo in ('id="va-sufijo"', 'id="va-ubicacion"', 'id="va-stock-min"'):
        assert campo in html, f"falta {campo} en el modal de variante"

    # El aviso de que se pierde el código de la BASE.
    assert "deja de existir" in html


def test_el_header_oculta_el_buscador_y_muestra_la_campanita(client, crear_usuario):
    """
    El buscador global ("Rectangle 50" del Figma) queda oculto hasta que
    exista el módulo que lo implemente, y en su lugar aparece la campanita
    de notificaciones ("Grupo 88").

    Que el buscador esté comentado en la plantilla no alcanza: un `{# #}` mal
    cerrado deja el markup vivo sin que falle nada, y ya pasó una vez en este
    proyecto. Por eso se comprueba sobre el HTML renderizado.
    """
    crear_usuario("juan", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "juan", "password": "Test1234!"})

    html = client.get("/").text

    assert "buscador-global" not in html, "el buscador se sigue renderizando"
    assert 'placeholder="Buscar…"' not in html

    # La campanita está, y está inerte a propósito: todavía no hay módulo
    # de notificaciones detrás.
    assert "Notificaciones" in html, "falta la campanita"
    campana = html.split("Notificaciones")[0].rsplit("<button", 1)[1]
    assert "disabled" in campana, "la campanita tiene que estar deshabilitada"


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
    # Y sin ninguna sección visible, tampoco aparece el hub que las agrupa.
    assert 'href="/configuracion"' not in resp.text


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
        # Las secciones de configuración mantienen "Configuraciones" activo.
        "/configuracion": "/configuracion",
        "/usuarios": "/configuracion",
        "/roles": "/configuracion",
        f"/usuarios/{admin.id}/permisos": "/configuracion",
        f"/usuarios/{admin.id}/historial": "/configuracion",
        f"/roles/{roles[ROL_VENDEDOR].id}/permisos": "/configuracion",
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
    La Cuenta Maestra ve las cuatro secciones dentro de Configuraciones,
    y ninguna de ellas como ítem suelto del sidebar.
    """
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    resp = client.get("/configuracion")
    assert resp.status_code == 200
    for url in ("/usuarios", "/roles", "/puntos-de-venta", "/dispositivos"):
        assert f'href="{url}"' in resp.text, url

    # En el sidebar (contexto de cualquier página) no están como top-level.
    home = client.get("/")
    aside = home.text.split("<aside")[1].split("</aside>")[0]
    for texto in ("Usuarios", "Roles", "Puntos de venta", ">Dispositivos<"):
        assert texto not in aside, texto
    assert "Configuraciones" in aside


def test_orden_de_las_secciones_de_configuracion(client, crear_usuario):
    """El orden de las tarjetas es el definido con el cliente."""
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    html = client.get("/configuracion").text
    posiciones = [
        html.index(f'href="{u}"')
        for u in ("/usuarios", "/roles", "/puntos-de-venta", "/dispositivos")
    ]
    assert posiciones == sorted(posiciones), "las secciones no están en orden"


def test_roles_tiene_una_sola_papelera_por_fila(client, crear_usuario):
    """
    En un rol nuevo —no es de sistema, así que se podía eliminar— aparecían
    DOS papeleras en la misma fila: la de baja, con el title "Desactivar", y
    otra con la etiqueta "Eliminar". Se leían como dos formas de hacer lo
    mismo, y ninguna otra pantalla del sistema ofrece borrado duro.

    Se cuenta sobre la plantilla porque las filas las arma Alpine en el
    navegador: en el HTML del servidor existe una sola, la del <template>.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/roles").text
    fila = html.split("<template")[1].split("</template>")[0]

    assert fila.count("Desactivar") == 1
    assert "Eliminar" not in fila, "volvió la segunda papelera"
    # La baja/alta sí sigue: son dos íconos excluyentes, nunca simultáneos.
    assert 'x-show="r.activo"' in fila and 'x-show="!r.activo"' in fila


def test_roles_sigue_siendo_exclusivo_de_cuenta_maestra(client, crear_usuario, roles, dar_permiso):
    """
    Roles pasó de ítem del sidebar a tarjeta del hub: la restricción a
    Cuenta Maestra tiene que viajar con él, no quedarse en el sidebar.
    """
    crear_usuario("dueno", ROL_DUENO)
    dar_permiso(rol_id=roles[ROL_DUENO].id, modulo=Modulo.USUARIOS, ver=True)
    client.post("/api/v1/auth/login", json={"username": "dueno", "password": "Test1234!"})

    resp = client.get("/configuracion")
    assert resp.status_code == 200
    # Ve Usuarios (tiene el permiso) pero no Roles (no es Cuenta Maestra).
    assert 'href="/usuarios"' in resp.text
    assert 'href="/roles"' not in resp.text


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


def test_los_estaticos_llevan_version_en_la_url(client, crear_usuario):
    """
    Regresión: StaticFiles no manda `Cache-Control`, así que sin un `?v=`
    en la URL el navegador se queda con el .js viejo y la pantalla corre
    código de otra versión (el bug del selector de local vacío).
    """
    import re

    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    html = client.get("/usuarios").text

    estaticos = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)
    assert estaticos, "la página no incluye ningún estático"
    sin_version = [u for u in estaticos if "?v=" not in u]
    assert not sin_version, f"estáticos sin versión: {sin_version}"


def test_la_version_del_estatico_cambia_al_editarlo():
    """La versión sale del mtime: si el archivo cambia, la URL cambia."""
    import os

    from app.core.templates import estatico

    antes = estatico("/js/usuarios.js")
    assert "?v=" in antes

    ruta = os.path.join(os.path.dirname(__file__), "..", "app", "static", "js", "usuarios.js")
    original = os.stat(ruta)
    try:
        os.utime(ruta, (original.st_atime, original.st_mtime + 10))
        assert estatico("/js/usuarios.js") != antes
    finally:
        os.utime(ruta, (original.st_atime, original.st_mtime))

    assert estatico("/js/usuarios.js") == antes


def test_estatico_inexistente_no_rompe_el_render():
    """Un path equivocado devuelve la URL sin versión, no una excepción."""
    from app.core.templates import estatico

    assert estatico("/js/no-existe.js") == "/static/js/no-existe.js"


def test_tabla_de_usuarios_tiene_la_columna_cumpleanos(client, crear_usuario):
    """La columna sale de `fecha_nacimiento`, formateada en el frontend."""
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    html = client.get("/usuarios").text
    assert ">Cumpleaños</th>" in html
    assert "formatearCumple(u.fecha_nacimiento)" in html


def test_el_colspan_de_la_fila_vacia_acompana_a_las_columnas(client, crear_usuario):
    """
    Al agregar una columna es fácil olvidarse del colspan de "Sin
    resultados." y que la fila vacía quede corrida. Este test lo ata a la
    cantidad real de <th>.
    """
    import re

    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    html = client.get("/usuarios").text
    tabla = html.split("<thead>")[1]

    columnas = len(re.findall(r"<th\b", tabla.split("</thead>")[0]))
    colspan = int(re.search(r'colspan="(\d+)"', tabla).group(1))

    assert colspan == columnas, f"{columnas} columnas pero colspan={colspan}"


def test_hay_navegacion_alcanzable_en_mobile(client, crear_usuario):
    """
    El sidebar se oculta por debajo de lg, así que tiene que existir el
    botón que lo abre. Sin él la app queda sin navegación en teléfono,
    que es como estaba antes del Principio 6.
    """
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    html = client.get("/").text

    assert 'aria-controls="sidebar-nav"' in html, "falta el botón que abre el menú"
    assert 'id="sidebar-nav"' in html, "el aside no tiene el id que referencia el botón"
    assert 'aria-label="Cerrar menú"' in html, "el cajón no se puede cerrar sin el overlay"


def test_no_se_usan_breakpoints_fuera_de_la_escala(client, crear_usuario):
    """
    El Principio 6 define <640 / 640-1023 / 1024-1279 / >=1280. `md:` (768)
    y `2xl:` (1536) quedan fuera de esa escala.
    """
    import pathlib
    import re

    plantillas = pathlib.Path(__file__).parent.parent / "app" / "templates"
    fuera_de_escala = {}
    for p in plantillas.rglob("*.html"):
        hallazgos = re.findall(r'(?<![\w-])(?:md|2xl):[a-z]', p.read_text())
        if hallazgos:
            fuera_de_escala[str(p.relative_to(plantillas))] = len(hallazgos)

    assert not fuera_de_escala, f"breakpoints fuera de la escala: {fuera_de_escala}"


def test_el_macro_de_iconos_no_devuelve_svg_vacio(client, crear_usuario):
    """
    `trazos.get(nombre, '')` devuelve un SVG vacío si el nombre no existe:
    el ícono desaparece sin que nada falle. Este test ata cada nombre usado
    en las plantillas a un trazo real.
    """
    import pathlib
    import re

    plantillas = pathlib.Path(__file__).parent.parent / "app" / "templates"
    definidos = set(
        re.findall(r"^\s*'([a-z-]+)':", (plantillas / "components" / "icons.html").read_text(), re.M)
    )

    usados = set()
    for p in plantillas.rglob("*.html"):
        usados.update(re.findall(r"icono\('([a-z-]+)'", p.read_text()))

    assert usados <= definidos, f"íconos usados pero no definidos: {sorted(usados - definidos)}"


def test_la_config_de_tailwind_esta_definida_una_sola_vez():
    """
    Estaba copiada en base.html y en auth/base_auth.html, y las copias ya
    habían divergido (a la de auth le faltaban 4 colores y 2 escalas).
    Una sola definición, incluida por ambos.
    """
    import pathlib

    plantillas = pathlib.Path(__file__).parent.parent / "app" / "templates"
    con_config = [
        str(p.relative_to(plantillas))
        for p in plantillas.rglob("*.html")
        if "tailwind.config" in p.read_text()
    ]
    assert con_config == ["components/_tailwind_config.html"], con_config

    for base in ("base.html", "auth/base_auth.html"):
        contenido = (plantillas / base).read_text()
        assert 'include "components/_tailwind_config.html"' in contenido, base


def test_la_escala_tipografica_no_usa_pixeles():
    """El Principio 6 pide unidades relativas para tipografía."""
    import pathlib
    import re

    cfg = (
        pathlib.Path(__file__).parent.parent
        / "app" / "templates" / "components" / "_tailwind_config.html"
    ).read_text()

    bloque = re.search(r"fontSize: \{(.*?)\n\s*\},", cfg, re.S).group(1)
    # Los px que quedan son los del comentario de equivalencia, no valores.
    valores = re.findall(r":\s*'([^']+)'", bloque)
    con_px = [v for v in valores if "px" in v]
    assert not con_px, f"tamaños en px: {con_px}"


def test_hay_guard_global_contra_overflow_horizontal():
    """Ningún componente puede empujar la página a lo ancho (Principio 6)."""
    import pathlib

    css = (
        pathlib.Path(__file__).parent.parent / "app" / "static" / "css" / "custom.css"
    ).read_text()

    assert "overflow-x: hidden" in css
    assert "--toque-min" in css, "faltan las variables de área de toque"
    assert "pointer: coarse" in css, "el mínimo de 44px debe regir solo en táctil"


def test_los_controles_usan_los_tokens_de_altura():
    """
    Ningún control puede volver a fijar su alto a mano: las alturas salen
    de --alto-control / --alto-boton, que suben a 44px en táctil. Un
    `h-10` suelto se saltearía el mínimo del Principio 6 en silencio.
    """
    import pathlib
    import re

    plantillas = pathlib.Path(__file__).parent.parent / "app" / "templates"

    # Un alto precedido por un ancho igual (`w-8 h-8`, `w-[22px] h-[22px]`)
    # es el tamaño de un ícono, no de un control: los glifos sí llevan
    # medidas fijas y el Principio 6 no habla de ellos.
    icono = re.compile(r"w-(\S+)\s+h-\1")

    sueltas = {}
    for p in plantillas.rglob("*.html"):
        texto = icono.sub("", p.read_text())
        hallazgos = re.findall(r"\bh-(?:8|9|10|\[\d+px\])", texto)
        if hallazgos:
            sueltas[str(p.relative_to(plantillas))] = hallazgos

    assert not sueltas, f"alturas fijas fuera de los tokens: {sueltas}"


def test_los_botones_de_solo_icono_reservan_area_de_toque():
    """
    Son los controles más usados (Ver/Editar/Borrar de cada fila) y los
    más chicos: ~30px. Deben pedir el mínimo táctil.
    """
    import pathlib

    macro = (
        pathlib.Path(__file__).parent.parent
        / "app" / "templates" / "components" / "botones.html"
    ).read_text()

    assert "min-h-toque" in macro and "min-w-toque" in macro


def test_los_controles_no_tienen_ancho_fijo_en_mobile():
    """
    Un `w-[220px]` suelto no entra en 320px y empuja la página a lo ancho.
    Todo ancho de control debe arrancar fluido y fijarse recién desde sm.
    """
    import pathlib
    import re

    plantillas = pathlib.Path(__file__).parent.parent / "app" / "templates"

    # Captura la clase COMPLETA, con su prefijo: sin eso `max-w-[35rem]` y
    # `sm:w-[15rem]` se leen como si fueran `w-[...]` a secas.
    clase = re.compile(r"(?:^|[\s\"'])((?:[a-z]+:)?(?:min-|max-)?w-\[(\d+(?:\.\d+)?)(px|rem)\])")

    sin_fluido = {}
    for p in plantillas.rglob("*.html"):
        for m in re.finditer(clase, p.read_text()):
            token, valor, unidad = m.group(1), float(m.group(2)), m.group(3)
            px = valor if unidad == "px" else valor * 16
            # Los anchos chicos son glifos de íconos, no controles.
            if px < 100:
                continue
            # Válidos: con breakpoint (`sm:w-[…]`) o como tope (`max-w-[…]`).
            if ":" in token or token.startswith("max-"):
                continue
            sin_fluido.setdefault(str(p.relative_to(plantillas)), []).append(token)

    assert not sin_fluido, f"anchos fijos sin variante fluida: {sin_fluido}"


def test_el_padding_del_contenido_se_achica_en_mobile():
    """36px de cada lado se comen 72px de los 320 disponibles."""
    import pathlib

    base = (
        pathlib.Path(__file__).parent.parent / "app" / "templates" / "base.html"
    ).read_text()

    assert "px-4 sm:px-9" in base, "el contenido no reduce su padding en mobile"
    assert "pl-9" not in base and "pr-9" not in base


def test_la_pagina_de_categorias_se_renderiza(client, crear_usuario):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    resp = client.get("/categorias")
    assert resp.status_code == 200
    assert "arbolCategorias" in resp.text
    assert "Categorías" in resp.text


def test_la_pagina_de_productos_se_renderiza(client, crear_usuario):
    """El ítem del sidebar apuntaba a /productos, que no existía y daba 404."""
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    resp = client.get("/productos")
    assert resp.status_code == 200
    assert "abmProductos" in resp.text


def test_categorias_marca_productos_en_el_sidebar(client, crear_usuario):
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    resp = client.get("/categorias")
    assert resp.text.count("nav-activo") == 1
    activo = resp.text.split('aria-current="page"')[0].rsplit('href="', 1)[1].rstrip('"\n ')
    assert activo == "/productos"


def test_toda_pantalla_es_alcanzable_desde_la_navegacion(client, crear_usuario):
    """
    Regresión: el ABM de categorías quedó huérfano al reemplazar la
    redirección de /productos por el listado. La pantalla funcionaba, pero
    no se llegaba desde ningún lado — el tipo de rotura que no falla, solo
    desaparece.

    Cada página con sesión tiene que estar enlazada desde el sidebar o
    desde otra página.
    """
    import re

    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    # Páginas que no cuelgan del sidebar y necesitan un enlace de entrada.
    entradas = {
        "/categorias": "/productos",
        "/puntos-de-venta": "/configuracion",
        "/dispositivos": "/configuracion",
        "/usuarios": "/configuracion",
        "/roles": "/configuracion",
    }

    for destino, desde in entradas.items():
        origen = client.get(desde)
        assert origen.status_code == 200, desde
        assert f'href="{destino}"' in origen.text, f"{desde} no enlaza a {destino}"

        # Y el camino de vuelta, para no dejar al usuario sin salida.
        vuelta = client.get(destino)
        assert vuelta.status_code == 200, destino
        assert f'href="{desde}"' in vuelta.text, f"{destino} no vuelve a {desde}"


def test_todas_las_pantallas_usan_el_macro_de_encabezado():
    """
    El encabezado (título + acciones) es estructura de UI repetida: va en
    un macro, no copiado en cada plantilla (Principio 2). Un <h1> suelto
    significa que alguien volvió a copiarlo.
    """
    import pathlib
    import re

    paginas = pathlib.Path(__file__).parent.parent / "app" / "templates" / "pages"
    sueltos = {}
    for p in paginas.rglob("*.html"):
        texto = p.read_text()
        if re.search(r'<h1 class="[^"]*text-titulo', texto):
            sueltos[str(p.relative_to(paginas))] = "h1 fuera del macro"

    assert not sueltos, sueltos


def test_el_boton_de_alta_no_vive_en_la_barra_de_filtros(client, crear_usuario):
    """
    Crear no es una acción sobre el listado: mezclado con los filtros se
    confunde con ellos. Va arriba, con el título.
    """
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    for url in ("/productos", "/usuarios", "/roles", "/proveedores",
                "/puntos-de-venta", "/categorias"):
        html = client.get(url).text
        assert html.count("Crear ") >= 1, url

        # El botón tiene que aparecer ANTES del primer filtro.
        i_crear = html.find("Crear ")
        i_filtros = html.find("Limpiar filtros")
        if i_filtros != -1:
            assert i_crear < i_filtros, f"{url}: el botón de alta quedó entre los filtros"


def test_el_enlace_de_retorno_no_esta_duplicado(client, crear_usuario):
    """
    Al unificar los encabezados quedó un `volver` suelto conviviendo con
    el del macro, y la flecha aparecía dos veces. El HTML renderizado es
    el único lugar donde eso se nota.
    """
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    retornos = {
        "/usuarios": "/configuracion",
        "/roles": "/configuracion",
        "/puntos-de-venta": "/configuracion",
        "/dispositivos": "/configuracion",
        "/categorias": "/productos",
    }

    for url, destino in retornos.items():
        html = client.get(url).text
        # El <main> excluye el sidebar, que también enlaza a esas rutas.
        main = html.split('id="contenido"')[1]
        assert main.count(f'href="{destino}"') == 1, f"{url}: retorno duplicado o ausente"


def test_las_acciones_de_pantalla_estan_agrupadas(client, crear_usuario):
    """
    Proveedores tenía su propio contenedor flex alrededor del título, y al
    meter el macro adentro quedaron dos flex anidados: "Crear nuevo" se
    pegaba al título y "Cambio masivo" quedaba solo a la derecha.
    """
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    main = client.get("/proveedores").text.split('id="contenido"')[1]

    i_titulo = main.find(">Proveedores</h1>")
    i_masivo = main.find("Cambio masivo del dólar")
    i_crear = main.find("Crear nuevo")
    i_filtros = main.find("Limpiar filtros")

    # Las dos acciones van juntas, después del título y antes de los filtros.
    assert i_titulo < i_masivo < i_crear < i_filtros


# ============================================================================
# SALUDO DEL LOCAL EN EL LOGIN
# ============================================================================


def _dispositivo(db, activo, punto_de_venta_id):
    """Crea un dispositivo y devuelve su uuid, para mandarlo como cookie."""
    from app.models.dispositivo import Dispositivo

    d = Dispositivo(
        descripcion="Celular de prueba",
        activo=activo,
        punto_de_venta_id=punto_de_venta_id,
    )
    db.add(d)
    db.flush()
    return str(d.uuid)


def _local(db, crear_usuario, activo=True):
    from app.models.punto_de_venta import TipoPuntoVenta
    from app.services import puntos_de_venta as servicio

    autor = crear_usuario("cm_local", ROL_CUENTA_MAESTRA)
    punto = servicio.crear_punto(db, autor, "Patio Olmos", TipoPuntoVenta.LOCAL, "1234")
    if not activo:
        servicio.cambiar_estado(db, autor, punto.id, activo=False)
    return punto


def test_el_login_saluda_al_local_del_dispositivo(client, db, crear_usuario):
    punto = _local(db, crear_usuario)
    uuid = _dispositivo(db, activo=True, punto_de_venta_id=punto.id)
    db.commit()

    client.cookies.set("device_uuid", uuid)
    resp = client.get("/login")

    assert resp.status_code == 200
    assert "Bienvenido a Patio Olmos" in resp.text


def test_un_dispositivo_inactivo_no_muestra_saludo(client, db, crear_usuario):
    """Un celular todavía sin activar no es de ningún local."""
    punto = _local(db, crear_usuario)
    uuid = _dispositivo(db, activo=False, punto_de_venta_id=punto.id)
    db.commit()

    client.cookies.set("device_uuid", uuid)
    resp = client.get("/login")

    assert "Bienvenido a" not in resp.text


def test_un_dispositivo_sin_local_no_muestra_saludo(client, db, crear_usuario):
    uuid = _dispositivo(db, activo=True, punto_de_venta_id=None)
    db.commit()

    client.cookies.set("device_uuid", uuid)
    resp = client.get("/login")

    assert "Bienvenido a" not in resp.text


def test_un_navegador_sin_dispositivo_no_muestra_saludo(client):
    """El caso normal: alguien entrando desde una computadora cualquiera."""
    resp = client.get("/login")

    assert resp.status_code == 200
    assert "Bienvenido a" not in resp.text


def test_un_local_dado_de_baja_no_se_saluda(client, db, crear_usuario):
    """
    El dispositivo sigue activo y asignado, pero el local se dio de baja:
    saludar a un local cerrado sería confuso.
    """
    punto = _local(db, crear_usuario, activo=False)
    uuid = _dispositivo(db, activo=True, punto_de_venta_id=punto.id)
    db.commit()

    client.cookies.set("device_uuid", uuid)
    resp = client.get("/login")

    assert "Bienvenido a" not in resp.text


def test_el_saludo_va_arriba_del_formulario(client, db, crear_usuario):
    """
    El saludo tiene que leerse antes de empezar a tipear, no después. Se
    ancla en el primer campo porque el diseño no tiene título: la tarjeta
    arranca directamente con "Usuario".
    """
    punto = _local(db, crear_usuario)
    uuid = _dispositivo(db, activo=True, punto_de_venta_id=punto.id)
    db.commit()

    client.cookies.set("device_uuid", uuid)
    html = client.get("/login").text

    assert html.find("Bienvenido a Patio Olmos") < html.find('for="username"')


def test_el_formato_de_moneda_no_vuelve_a_redondear():
    """
    El redondeo del precio es CEIL y lo hace el backend. Si la vista usa
    `maximumFractionDigits: 0` aplica su propio redondeo half-expand: con
    el `redondeo` del sistema en 0,50 un precio guardado como 1234,49 se
    mostraría "$1.234", menos de lo que se cobra.

    Hoy no se nota porque el redondeo configurado es 1000 y los precios no
    tienen decimales, pero eso es un valor de configuración, no una
    garantía.
    """
    import pathlib
    import re

    js = pathlib.Path(__file__).parent.parent / "app" / "static" / "js"
    culpables = {}
    for archivo in js.glob("*.js"):
        texto = archivo.read_text()
        # Un máximo de decimales sin un mínimo igual deja que Intl redondee.
        for m in re.finditer(r"maximumFractionDigits:\s*(\d+)", texto):
            if "minimumFractionDigits" not in texto:
                culpables.setdefault(archivo.name, []).append(m.group(0))

    assert not culpables, f"formato que puede redondear importes: {culpables}"


def test_auditoria_no_se_muestra_a_nadie(client, crear_usuario, roles, dar_permiso):
    """
    Está oculta hasta que exista su pantalla: hoy /auditoria no tiene ruta
    HTML y el ítem llevaba a un 404.

    Se prueba con la Cuenta Maestra —que ve todo— y con un rol al que se le
    da el permiso explícitamente: `oculto` gana sobre cualquier permiso.
    """
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})
    assert 'href="/auditoria"' not in client.get("/").text

    crear_usuario("auditor", ROL_DUENO)
    dar_permiso(rol_id=roles[ROL_DUENO].id, modulo=Modulo.AUDITORIA, ver=True)
    client.post("/api/v1/auth/login", json={"username": "auditor", "password": "Test1234!"})
    assert 'href="/auditoria"' not in client.get("/").text


def test_el_endpoint_de_auditoria_sigue_activo(client, crear_usuario):
    """
    Se oculta el ítem del menú, no la funcionalidad: la auditoría es
    append-only y su endpoint de lectura tiene que seguir disponible.
    """
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    headers_login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"}
    )
    assert headers_login.status_code == 200

    resp = client.get("/api/v1/auditoria")
    assert resp.status_code == 200


def test_ningun_item_del_sidebar_lleva_a_un_404(client, crear_usuario):
    """
    Regresión: "Productos" y "Auditoría" apuntaban a rutas inexistentes y
    nadie lo notaba hasta hacer clic.

    Los módulos sin construir (Ventas, Reportes, Ajustes) tienen una
    pantalla en blanco para que su ítem resuelva, así que la regla vale
    para todos sin excepciones.
    """
    import re

    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    aside = client.get("/").text.split("<aside")[1].split("</aside>")[0]
    destinos = sorted(set(re.findall(r'href="(/[^"]*)"', aside)))
    assert destinos, "el sidebar no tiene ningún enlace"

    rotos = [d for d in destinos if client.get(d, follow_redirects=False).status_code == 404]
    assert not rotos, f"ítems del sidebar que dan 404: {rotos}"


def test_los_modulos_pendientes_muestran_su_pantalla(client, crear_usuario):
    """Cada uno con su título y su ítem del sidebar marcado."""
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    for ruta, titulo in {"/ventas": "Ventas", "/reportes": "Reportes",
                         "/ajustes": "Ajustes"}.items():
        resp = client.get(ruta)
        assert resp.status_code == 200, ruta
        assert f">{titulo}</h1>" in resp.text, ruta
        assert "todavía no está disponible" in resp.text, ruta

        # El ítem correcto queda activo: si las tres rutas compartieran la
        # misma closure, todas marcarían la última del bucle.
        activo = resp.text.split('aria-current="page"')[0].rsplit('href="', 1)[1].rstrip('"\n ')
        assert activo == ruta, f"{ruta}: marcó {activo}"


def test_la_documentacion_se_oculta_en_produccion():
    """
    Swagger, ReDoc y el openapi.json no exigen autenticación: publicados
    describen la API entera a cualquiera que entre a la URL.

    Se reconstruye la app con APP_ENV=production en vez de usar el `client`
    del conftest, que ya se creó con la configuración de test.
    """
    import importlib

    from config import settings

    original = settings.APP_ENV
    try:
        settings.APP_ENV = "production"
        import main

        app_prod = importlib.reload(main).app
        assert app_prod.docs_url is None
        assert app_prod.redoc_url is None
        assert app_prod.openapi_url is None

        settings.APP_ENV = "development"
        app_dev = importlib.reload(main).app
        assert app_dev.docs_url == "/docs"
        assert app_dev.openapi_url == "/openapi.json"
    finally:
        settings.APP_ENV = original
        importlib.reload(main)


def test_el_estado_del_dispositivo_no_lo_tapa_la_falta_de_local():
    """
    Regresión: `etiquetaEstado` devolvía "Sin asignar" cuando el
    dispositivo no tenía local, y esa rama cortaba antes de mirar
    `activo`. Dos dispositivos con estado opuesto se veían idénticos, y
    activar uno sin local parecía no haber tenido efecto.

    Se valida sobre el archivo real: es lógica de presentación en JS y no
    hay forma de ejercitarla desde el cliente de pruebas.
    """
    import pathlib
    import re

    js = (
        pathlib.Path(__file__).parent.parent / "app" / "static" / "js" / "dispositivos.js"
    ).read_text()

    cuerpo = re.search(r"etiquetaEstado\(d\) \{(.*?)\n        \},", js, re.S).group(1)

    # La etiqueta tiene que decidirse por `activo`, sin ramas previas que
    # miren el local.
    assert "punto_de_venta_id" not in cuerpo, (
        "la etiqueta de estado volvió a depender del local: tapa el valor de activo"
    )
    assert "d.activo" in cuerpo

    # El matiz "activo pero todavía no puede operar" no se pierde.
    assert "faltaLocal" in js


def test_las_pantallas_de_auth_muestran_la_marca_en_todo_ancho(client, crear_usuario):
    """
    Regresión: antes el logo vivía dentro de un panel `hidden lg:flex`, así
    que por debajo de 1024px la pantalla quedaba sin ninguna identificación
    de la empresa, y hubo que agregar un segundo logo solo para móvil.

    Con el diseño "DesktopLogin1" la columna es una sola y el logo es **uno**,
    centrado, visible en todo ancho. Se cuidan las dos cosas: que esté, y que
    no vuelva a haber una copia condicionada por breakpoint que haya que
    mantener en paralelo.
    """
    crear_usuario("admin", ROL_CUENTA_MAESTRA, ultimo_acceso=None)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    # /cambiar-password usa el mismo layout: es adonde va a parar un usuario
    # nuevo en su primer ingreso, muchas veces desde el celular.
    for url in ("/login", "/cambiar-password"):
        html = client.get(url, follow_redirects=True).text

        assert html.count('role="img"') == 1, f"{url}: tiene que haber un solo logo"
        assert "hidden lg:flex" not in html, f"{url}: volvió el panel de dos columnas"

        # La tarjeta blanca del diseño, con el ancho de 432px del Figma.
        assert "rounded-[10px]" in html, f"{url}: falta la tarjeta"
        assert "max-w-[27rem]" in html, f"{url}: falta el ancho del diseño"


def test_el_login_no_tiene_el_boton_de_modo_oscuro(client):
    """
    El diseño no lo incluye. El tema se elige desde adentro del sistema y la
    preferencia queda guardada, así que el próximo login ya la respeta.
    """
    html = client.get("/login").text

    assert "alternar()" not in html
    assert "Cambiar a modo oscuro" not in html


def test_el_error_de_login_no_revela_cual_de_los_dos_campos_fallo(client):
    """
    El diseño (DesktopLogin2) pone "Lo sentimos, usuario incorrecto" bajo el
    campo Usuario. No se puede implementar literalmente: `autenticar_usuario`
    devuelve SIEMPRE el mismo mensaje genérico justamente para no revelar si
    un usuario existe, y distinguirlo acá abriría la enumeración de usuarios.

    La adaptación marca los dos campos con el mismo estado `error`. Este test
    cuida que nadie "complete" el diseño más adelante rompiendo eso.
    """
    html = client.get("/login").text

    # El texto lo pone la API en tiempo de ejecución; la pantalla no puede
    # traer escrita una versión que señale un campo.
    assert "usuario incorrecto" not in html.lower()
    assert "contraseña incorrecta" not in html.lower()

    # Un único estado de error, compartido por los dos campos. El binding
    # está partido en varias líneas en el macro, así que se compara sobre el
    # HTML con los espacios colapsados.
    plano = " ".join(html.split())
    assert plano.count("error ? 'border-danger") == 2, (
        "los dos campos tienen que marcarse con el mismo estado"
    )


def test_el_error_de_login_se_muestra_en_el_formulario_y_no_como_toast(client):
    """
    Antes un 401 iba a `window.toast`, que se desvanece a los segundos y
    aparece lejos del campo. El diseño lo pide dentro del formulario.
    """
    html = client.get("/login").text

    assert "this.error = e.message" in html
    assert "window.toast(e.message" not in html
