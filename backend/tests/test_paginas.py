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


def test_el_formato_del_dolar_no_vuelve_a_redondear():
    """
    El dólar se muestra sin decimales cuando no los tiene, PERO no con
    `maximumFractionDigits: 0`: ese modificador aplica su propio redondeo
    half-expand y 1.385,50 se mostraría "1.386" — un número que nadie
    guardó. Es el mismo defecto que ya tuvo el precio en pesos.

    Y vive en app.js, no copiado en cada pantalla: estaba duplicado en
    proveedores.js y dolar_masivo.js, y cualquier ajuste tenía que hacerse
    dos veces para que no divergieran.
    """
    from pathlib import Path

    js = Path(__file__).resolve().parents[1] / "app" / "static" / "js"
    app = (js / "app.js").read_text()

    assert "window.formatearDolar" in app, "el formateo del dólar no está en app.js"
    assert "Number.isInteger" in app, "sin isInteger, el redondeo lo hace Intl"

    # Ninguna pantalla puede volver a implementarlo por su cuenta. Se busca
    # `minimumFractionDigits`, que es lo que usa el formateo de NÚMEROS:
    # `toLocaleString` a secas también lo usa `formatearFecha`, que sí es
    # propia de cada pantalla y no tiene nada que ver.
    for pantalla in ("proveedores.js", "dolar_masivo.js"):
        contenido = (js / pantalla).read_text()
        assert "formatearDolar: window.formatearDolar" in contenido, (
            f"{pantalla} no delega el formateo del dólar"
        )
        assert "minimumFractionDigits" not in contenido, (
            f"{pantalla} volvió a formatear números por su cuenta"
        )


def test_el_dolar_se_cambia_desde_editar_y_no_desde_ver(client, crear_usuario):
    """
    La ficha ("Ver") es de consulta: muestra el valor actual del dólar pero
    no deja cambiarlo ni abre el historial. Las dos cosas son acciones y
    viven en el modal de edición.

    El cambio de dólar además va en su propio bloque, con botón aparte: no
    entra en "Finalizar" porque recalcula el precio de venta de TODOS los
    productos del proveedor, y eso no puede pasar de arrastre al guardar un
    teléfono.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/proveedores").text

    # Se comprueba por identificadores y no recortando el HTML: los
    # marcadores de cada modal (`ficha.abierta`, `form.abierto`) aparecen
    # varias veces cada uno y cualquier recorte queda a merced del orden.

    # La ficha muestra el valor actual…
    assert "ficha.proveedor?.dolar_actual" in html
    # …pero ya no tiene el campo de cambio ni la tabla de historial.
    assert 'id="fc-dolar"' not in html, "el cambio de dólar volvió a la ficha"
    assert "ficha.historial" not in html, "el historial volvió a la ficha"

    # Los dos bloques viven ahora en la edición.
    assert 'id="pv-nuevo-dolar"' in html, "falta el cambio de dólar en la edición"
    assert "form.historial" in html, "falta el historial en la edición"


def test_la_tabla_muestra_el_precio_efectivo_y_marca_el_propio(client, crear_usuario):
    """
    El precio que se muestra es el efectivo —el de la variante si tiene, el
    del producto si no— y lo resuelve el backend.

    La marca importa: sin ella, cambiar el precio del producto y ver que
    algunas filas no se movieron parece un error del sistema en vez de un
    precio puesto a mano.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    assert "v.precio_usd_efectivo" in html
    assert "v.precio_venta_efectivo" in html
    # Ya no puede mostrar el del producto directo: taparía el propio.
    assert "v.producto.precio_usd" not in html
    assert "v.producto.precio_venta" not in html

    assert "v.tiene_precio_propio" in html, "falta la marca de precio propio"
    assert 'id="ev-usd"' in html, "falta el campo de precio en el modal de variante"

    # El panel del código de barras también muestra los precios: es donde se
    # ve de dónde sale el que se cobra.
    panel = html.split("variantesVisibles()")[1]
    assert "usd(v.precio_usd_efectivo)" in panel
    assert "pesos(v.precio_venta_efectivo)" in panel


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


def test_el_filtro_de_categoria_muestra_el_camino_completo(client, crear_usuario):
    """
    El filtro del listado elige de una lista plana de todo el árbol, así que
    cada opción tiene que decir de qué rama es: dos ramas pueden tener hojas
    con el mismo nombre y, con el nombre suelto, al elegir no habría forma de
    saber cuál se eligió.

    Lo arma `rutaCategoria()` con la lista que ya está en memoria.

    El formulario NO usa esto: baja por el árbol con un select por nivel, y
    ahí el camino lo dicen los selects anteriores.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    assert html.count("texto: (o) => rutaCategoria(o)") == 1, (
        "el camino completo es del filtro, y solo de él"
    )
    # La sangría con puntos del `<select>` viejo no puede volver.
    assert ".repeat(" not in html


def test_el_selector_de_categoria_se_puede_buscar_tipeando(client, crear_usuario):
    """
    Era un `<select>` nativo, que no se filtra: tipear ahí solo salta por la
    primera letra, y como cada opción muestra el camino completo, todas las de
    una misma rama empiezan igual ("Joyas - …"). Con el árbol de 5 niveles de
    una bijouterie, encontrar la categoría era bajar con la rueda.

    Ahora es un combobox: un input que filtra la lista mientras se escribe.
    Los de la cascada del formulario también, aunque cada uno ofrezca pocas
    opciones: un nivel puede tener decenas (un "Material" de bijouterie).
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    # Tres filtros (categoría, proveedor, temporada), dos del formulario
    # (proveedor y temporada) y los cinco niveles de categoría: todos el
    # mismo componente. Temporada va sin buscador, pero es el mismo.
    assert html.count("combobox({") == 10

    for campo in ("f-categoria", "pr-categoria-1", "pr-categoria-5"):
        assert f'id="{campo}" type="text"' in html, f"{campo} dejó de ser un input"
        # Sin esto un lector de pantalla lee un campo de texto suelto y no
        # anuncia ni que hay lista ni cuál fila está marcada.
        assert f'aria-controls="{campo}-lista"' in html

    # El desplegable viejo no puede quedar dando vueltas al lado del nuevo.
    assert 'x-model="filtros.categoria_id"' not in html
    assert 'x-model="form.categoria_id"' not in html


def test_el_alta_de_producto_exige_categoria_y_proveedor_sin_el_required(
    client, crear_usuario
):
    """
    La obligatoriedad la daba el `required` del `<select>`. El combobox es un
    input de texto libre —lo que se tipea es la búsqueda, no el valor— así que
    un `required` ahí exigiría texto, no una categoría elegida: bastaría dejar
    a medio escribir "ani" para que el navegador diera el formulario por bueno.

    Pasa a exigirlo el botón, como en los dos modales de variante. Vale igual
    para el proveedor desde que también es un combobox; en edición no bloquea
    nada porque `editar()` carga el proveedor del producto.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    assert "form.guardando || !categoriaCompleta() || !form.proveedor_id" in html, (
        "el botón Guardar tiene que quedar deshabilitado sin categoría"
    )


def test_la_categoria_se_elige_bajando_por_el_arbol(client, crear_usuario):
    """
    Un select por nivel en vez de una lista plana con el camino completo en
    cada fila: en cada paso se ve nada más que lo que cuelga de lo ya
    elegido.

    Se dibujan los cinco niveles y se muestran los que correspondan. No se
    generan con un `x-for` porque el macro `combobox` fija un `id` que usan
    el `<label for>` y el `aria-controls`, y clonarlo lo repetiría en el DOM.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    # Un select por cada nivel que admite el árbol (NIVEL_MAXIMO = 5), cada
    # uno con sus propias opciones y escribiendo en su lugar de la ruta.
    for nivel in range(1, 6):
        assert f'id="pr-categoria-{nivel}"' in html
        assert f"opciones: () => opcionesCategoria({nivel})" in html
        assert f"form.categoriaRuta[{nivel - 1}]" in html
        assert f"elegirCategoria({nivel})" in html

    # El primero se muestra siempre; los demás, cuando hay algo que elegir.
    assert html.count("nivelCategoriaVisible(") == 5

    # El camino completo es cosa del filtro: acá cada opción es un nombre
    # suelto, porque la rama la dicen los selects anteriores.
    assert html.count("texto: (o) => o.nombre") >= 5


def test_cada_nivel_de_categoria_tiene_su_propia_leyenda(client, crear_usuario):
    """
    La leyenda gris de cada campo es lo que lo nombra: los dos primeros
    niveles tienen nombre propio y del tercero en adelante son subcategorías
    numeradas.

    Van como `placeholder` y como etiqueta oculta —no como `<label>` visible—
    porque el grupo ya lleva un solo título "Categoría": repetirlo encima de
    cada campo sería decirlo dos veces.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    for leyenda in ("Tipo", "Material", "Subcategoría 1", "Subcategoría 2",
                    "Subcategoría 3"):
        assert f'placeholder="{leyenda}"' in html, f"falta la leyenda {leyenda}"

    # Cada nivel con la suya, y ninguno con la genérica del componente: los
    # dos "Seleccionar" que quedan son de proveedor y temporada.
    assert html.count('placeholder="Seleccionar"') == 2


def test_no_se_guarda_sin_llegar_al_final_de_la_rama(client, crear_usuario):
    """
    Todos los selects a la vista son obligatorios. Dicho al revés: si queda
    uno visible sin elegir es porque lo último elegido todavía tiene hijos, y
    el producto quedaría colgado de un nodo intermedio.

    `!form.categoria_id` no alcanzaba: con un intermedio elegido tiene valor.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    # Los dos botones del alta y el de la edición usan la misma guarda.
    assert html.count("!categoriaCompleta()") == 3
    # Y se dice por qué el botón está apagado, que si no no se entiende.
    assert "Elegí hasta el último nivel" in html

    js = _js_de("/productos")
    # Completa = lo último elegido no tiene hijos.
    assert "categoriaCompleta()" in js
    assert "opcionesCategoria(ruta.length + 1).length === 0" in js


def test_elegir_un_nivel_de_arriba_borra_los_de_abajo(client, crear_usuario):
    """
    Cambiar el Tipo invalida el Material que estaba puesto: era hijo de otra
    rama. Sin cortar la cola, el producto terminaría guardado en una
    categoría que ya no se ve en pantalla.

    Se reemplaza el array entero y no se lo trunca con `length`: el
    `x-effect` de cada combobox depende de `form.categoriaRuta`, y cambiar la
    propiedad es lo que hace que los de abajo se vacíen.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    js = _js_de("/productos")

    assert "this.form.categoriaRuta = this.form.categoriaRuta.slice(0, nivel)" in js
    assert "categoriaRuta.length =" not in js, "truncar el array no dispara Alpine"
    # La edición abre con el camino del producto ya puesto.
    assert "categoriaRuta: this.rutaDeIds(p.categoria_id)" in js


def test_el_modal_de_producto_se_ensancha_recien_en_el_cuarto_nivel(
    client, crear_usuario
):
    """
    El ancho de arranque ya entra los tres primeros selects, así que elegir
    Tipo y Material —el camino de casi todo el catálogo— no mueve el modal.
    Recién del cuarto en adelante se ve crecer, que es cuando hace falta: con
    cuatro o cinco en fila, el ancho de siempre los dejaba apretados en dos
    renglones.

    Las clases van escritas en el HTML y no armadas en un helper de JS: el
    CDN de Tailwind genera las que encuentra en el documento, y una que solo
    existiera dentro de un `.js` no se generaría nunca.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    for ancho in ("max-w-[44rem]", "max-w-[52rem]", "max-w-[60rem]"):
        assert ancho in html, f"falta el ancho {ancho}"
    # Uno, dos o tres selects comparten ancho: el modal no se mueve.
    assert "'max-w-[44rem]': nivelesCategoriaVisibles() <= 3" in html
    # `w-full` sigue mandando en pantallas chicas: el max-w es un techo.
    assert 'class="w-full my-8 bg-surface' in html


def test_el_filtro_de_categoria_recarga_y_se_puede_limpiar(client, crear_usuario):
    """
    El `<select>` del filtro traía dos cosas que el combobox tiene que
    conservar: recargaba la tabla al elegir (`@change="cargar()"`) y tenía una
    opción vacía para sacar el filtro. Sin la primera el filtro no se aplica;
    sin la segunda no hay forma de volver al catálogo completo.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    assert "filtros.categoria_id = v; cargar();" in html
    assert "vacio: 'Todas las categorías'" in html

    # Los del formulario NO la llevan: los cinco niveles de categoría, el
    # proveedor y la temporada siempre tienen valor.
    assert html.count("vacio: null") == 7


def test_el_selector_de_proveedor_se_puede_buscar_tipeando(client, crear_usuario):
    """
    Mismo problema que tenía categoría: era un `<select>` nativo, que no se
    filtra. Con el catálogo de una bijouterie los proveedores son decenas y
    encontrar uno era bajar con la rueda, mientras el campo de al lado
    —categoría— ya se buscaba tipeando. Dos campos pegados en la misma fila no
    pueden comportarse distinto.

    Es el mismo componente, no una copia: lo único que cambia es la etiqueta de
    cada opción (`o.nombre` en vez del camino del árbol).
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    for campo in ("f-proveedor", "pr-proveedor"):
        assert f'id="{campo}" type="text"' in html, f"{campo} dejó de ser un input"
        assert f'aria-controls="{campo}-lista"' in html

    # El desplegable viejo no puede quedar dando vueltas al lado del nuevo.
    assert 'x-model="filtros.proveedor_id"' not in html
    assert 'x-model="form.proveedor_id"' not in html


def test_el_filtro_de_proveedor_recarga_y_se_puede_limpiar(client, crear_usuario):
    """
    Lo mismo que se le exige al filtro de categoría: el `<select>` recargaba la
    tabla al elegir y tenía una opción vacía. Sin la primera el filtro no se
    aplica; sin la segunda no hay forma de volver al catálogo completo.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    assert "filtros.proveedor_id = v; cargar();" in html
    assert "vacio: 'Todos los proveedores'" in html


def test_elegir_proveedor_en_el_alta_recalcula_el_precio(client, crear_usuario):
    """
    El precio en pesos sale de la cotización del proveedor, así que el
    `@change="calcularPreview()"` del `<select>` no era decorativo: sin él los
    valores informativos quedan con el dólar del proveedor anterior y el alta
    muestra un precio que no es el que se va a guardar.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    assert "form.proveedor_id = v; calcularPreview();" in html


def test_la_temporada_ofrece_solo_las_tres_opciones(client, crear_usuario):
    """
    El desplegable decía "Estacionalidad" y listaba las cuatro estaciones más
    "permanente", en minúscula y capitalizadas por CSS. Ahora es "Temporada"
    con las tres que se compran, y la etiqueta visible no se deriva del valor:
    "otoño_invierno" con el guion bajo cambiado por un espacio no da
    "Otoño-Invierno".

    Son los dos campos —el filtro del listado y el del formulario— y los dos
    salen de la misma constante `TEMPORADAS`.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    assert "Estacionalidad" not in html, "quedó el nombre viejo en pantalla"
    for campo in ("f-temporada", "pr-temporada"):
        assert f'id="{campo}"' in html
    assert html.count("opciones: () => TEMPORADAS") == 2
    assert "filtros.temporada = v; cargar();" in html
    assert "form.temporada = v;" in html

    js = _js_de("/productos")
    for etiqueta in ("Atemporal", "Otoño-Invierno", "Primavera-Verano"):
        assert etiqueta in js, f"falta la opción {etiqueta}"
    # Las estaciones sueltas ya no existen como valor.
    for vieja in ("'permanente'", "'invierno'", "'primavera'"):
        assert vieja not in js, f"quedó la estación vieja {vieja}"
    # El alta arranca en atemporal, que es lo que corresponde a la mayoría
    # del catálogo.
    assert "temporada: 'atemporal'" in js


def test_temporada_es_el_mismo_desplegable_que_los_otros_pero_sin_buscador(
    client, crear_usuario
):
    """
    Los tres desplegables de la barra de filtros tienen que verse igual. Con
    un `<select>` nativo no se puede: su lista la dibuja el sistema operativo,
    así que al lado de Categoría y Proveedor —que abren una lista propia,
    estilada— Temporada se veía como otra cosa.

    Pasa al mismo componente con `buscable=false`: el campo va `readonly`, se
    despliega y se navega con el teclado, pero no se tipea. Con tres opciones
    un buscador no aporta nada, y un campo que invita a escribir donde no hay
    nada que buscar confunde.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    # Ni un `<select>` de temporada ni el `x-for` de sus `<option>`.
    assert "<select" not in html, "volvió un select nativo a la pantalla"

    for campo in ("f-temporada", "pr-temporada"):
        assert f'id="{campo}" type="text"' in html
        assert f'aria-controls="{campo}-lista"' in html

    # Los dos van de solo lectura; los ocho buscables, no.
    assert html.count("readonly") == 2
    # Y sin el `@input` que filtra, que es lo único que los diferencia.
    assert html.count("alEscribir()") == 8


def test_el_stock_infinito_solo_lo_ve_la_cuenta_maestra(client, crear_usuario):
    """
    El checkbox hace que el producto NO descuente stock al vender. No es una
    decisión de quien carga mercadería: prendido por error, el sistema deja
    de saber cuánto hay de ese artículo y nada avisa.

    Esconderlo no es la barrera —la API se puede llamar sin la pantalla, y de
    eso se ocupa `_validar_stock_infinito()` en el service—: lo que se evita
    acá es ofrecerle a un vendedor una decisión que no es suya.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    crear_usuario("vende", ROL_VENDEDOR)

    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})
    assert "form.stock_infinito" in client.get("/productos").text, (
        "la Cuenta Maestra tiene que poder elegirlo"
    )

    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})
    html = client.get("/productos").text
    assert "form.stock_infinito" not in html, "el vendedor no puede elegirlo"
    assert "Stock infinito" not in html

    # Pero sigue viendo el dato en la tabla: saber que un producto no
    # descuenta stock es distinto de poder cambiarlo.
    assert "v.producto.stock_infinito" in html


def test_el_alta_de_producto_acepta_una_foto(client, crear_usuario):
    """
    Antes había que crear el producto, buscarlo en el listado, abrir la ficha
    y recién ahí subirle la foto. Ahora se elige en el mismo formulario.

    No se sube al elegirla: el endpoint cuelga de `/productos/{id}/fotos` y
    ese id no existe hasta que el producto está creado. El archivo espera en
    el formulario y lo sube `guardar()` con el id que devuelve el alta.

    Solo en el ALTA: en edición la ficha ya tiene la grilla de las cinco con
    "principal" y "borrar", y dos lugares para lo mismo se contradicen.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    # El campo existe y está dentro de la rama de alta (`!form.id`).
    assert 'x-if="!form.id"' in html
    assert "elegirFoto($event)" in html
    assert "quitarFoto()" in html
    # Mismos formatos que acepta la ficha.
    assert html.count('accept="image/jpeg,image/png,image/gif,image/webp"') == 2

    js = _js_de("/productos")
    # Se sube DESPUÉS del alta, con el id que devolvió el backend.
    assert "subirFotoDelAlta(guardado.id)" in js
    assert "/fotos`" in js


def test_crear_con_variantes_lleva_al_alta_de_la_primera_variante(client, crear_usuario):
    """
    El camino de quien ya sabe que el producto viene en colores o talles:
    crear y seguir derecho, en vez de buscarlo en el listado y abrir la ficha
    para recién ahí empezar.

    El botón NO es submit: los dos envían el mismo formulario, y siendo
    submit el Enter dentro de un campo abriría el modal de variante sin
    haberlo pedido.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    assert "Crear con variantes" in html
    assert "guardar({ conVariantes: true })" in html
    # Solo en el alta: editar un producto ya tiene su ficha con las variantes.
    assert 'x-show="!form.id"' in html
    # Con la misma guarda que "Crear": sin categoría ni proveedor —y con una
    # descripción que ya está usada— no se crea.
    assert html.count("!categoriaCompleta() || !form.proveedor_id") == 2
    assert html.count("|| duplicadoExacto()") == 2

    js = _js_de("/productos")
    # El panel primero: `abrirVariante()` mira si todavía está la BASE para
    # avisar que la primera variante real la reemplaza.
    assert "await this.abrirProducto(guardado.id)" in js
    assert "this.abrirVariante()" in js


def test_la_variante_tiene_su_propio_sku_de_proveedor(client, crear_usuario):
    """
    El proveedor no numera por producto: numera por color y por talle. El
    campo va en los dos formularios de variante, debajo del sufijo y su
    descripción, y vacío hereda el del producto —misma regla que el precio—.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    # En el alta (va-) y en la edición (ev-) de variante.
    for campo in ("va-skuprov", "ev-skuprov"):
        assert f'id="{campo}"' in html, f"falta {campo}"
    # Debajo del sufijo y de su descripción, no antes.
    assert html.index('id="va-nombre"') < html.index('id="va-skuprov"')
    assert html.index('id="va-sufijo"') < html.index('id="va-skuprov"')
    assert html.index('id="ev-nombre"') < html.index('id="ev-skuprov"')

    # Vacío = hereda, dicho en el campo y en la aclaración de abajo.
    assert html.count('placeholder="Usa el del producto"') == 3
    assert html.count("Vacío = usa el del producto") == 2

    js = _js_de("/productos")
    assert "sku_proveedor: this.variante.sku_proveedor || null" in js
    # null explícito al vaciarlo: es lo que lo devuelve al del producto.
    assert "sku_proveedor: e.sku_proveedor === '' ? null : e.sku_proveedor" in js


def test_la_ficha_muestra_el_sku_de_proveedor_que_manda(client, crear_usuario):
    """
    Se ve el efectivo —el propio si lo tiene, el del producto si no— y se
    aclara cuál de los dos es, igual que con el precio: sin la aclaración, un
    código que no coincide con el del producto parece un error.

    La línea no aparece si no hay ninguno de los dos: el campo es opcional en
    los dos niveles.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    assert 'x-text="v.sku_proveedor_efectivo"' in html
    assert 'x-show="v.sku_proveedor_efectivo"' in html
    assert "SKU del proveedor propio de esta variante" in html
    assert "SKU del proveedor del producto" in html


def test_agregar_una_variante_deja_la_ficha_abierta_para_la_siguiente(
    client, crear_usuario
):
    """
    Un producto que viene en colores o talles necesita varias variantes
    cargadas una atrás de la otra. Guardar cerraba el formulario Y la ficha,
    y la pantalla quedaba en el listado: para la segunda había que buscar el
    producto y volver a entrar.

    Ahora se cierra solo el formulario y la ficha queda abierta y releída,
    con "Agregar variante" ahí mismo. Es el mismo camino que ya usaba la
    edición de variante.

    Se relee SIN acotar a un código: la recién creada tiene que verse, y si
    era la primera, el backend acaba de eliminar la BASE que el panel venía
    mostrando —filtrar por ese id dejaría la ficha vacía—.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    js = _js_de("/productos")

    # Cerrar la ficha al guardar era lo que obligaba a volver a buscar el
    # producto: no puede volver a aparecer en el módulo.
    assert "this.detalle.abierto = false" not in js
    assert (
        "await this.abrirProducto(this.detalle.producto.id, { varianteId: null })" in js
    )
    # El listado se recarga igual: se va la fila de la BASE y entra la nueva.
    assert js.count("this.cargar();") >= 2


def test_la_descripcion_va_despues_del_proveedor_y_su_sku(client, crear_usuario):
    """
    El orden del formulario es el del trabajo: primero dónde va y de quién
    viene, después cómo se llama.

    No es cosmético. El buscador de parecidos del campo Descripción ofrece
    solo lo que ya está cargado en ESA categoría y ESE proveedor, así que
    con la descripción arriba de todo la lista salía sin acotar y ofrecía
    medio catálogo.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    # Se compara la posición de cada campo DENTRO del modal de alta/edición:
    # 'pr-' es el prefijo de sus ids.
    orden = [html.index(f'id="pr-{campo}"') for campo in ("categoria-1", "skuprov", "desc")]
    assert orden == sorted(orden), "el formulario no sigue el orden esperado"
    # El proveedor no tiene `id="pr-proveedor"` visible en edición (ahí es un
    # dato fijo), pero su combobox se declara antes que la descripción.
    assert html.index("'pr-proveedor'") < html.index('id="pr-desc"')


def test_la_descripcion_ofrece_los_productos_ya_cargados_con_nombre_parecido(
    client, crear_usuario
):
    """
    Sirve para dos cosas a la vez: ver que el artículo tal vez ya existe
    antes de duplicarlo —el alta lo rechaza si descripción, categoría y
    proveedor coinciden— y adoptar el nombre con el que quedó cargado, para
    que el catálogo no tenga "Cadena plata 925" y "cadena de plata 925" como
    si fueran cosas distintas.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    assert "buscarSimilares()" in html
    assert "elegirSimilar(p)" in html
    # Se puede recorrer con el teclado, como el resto de los desplegables.
    assert "moverSimilar(1)" in html and "moverSimilar(-1)" in html
    # Cambiar el proveedor rehace la búsqueda: la lista está acotada a él y
    # quedaría vieja. La categoría hace lo mismo, pero por dentro de
    # `elegirCategoria()`, que además corta los niveles de abajo.
    assert html.count("buscarSimilares();") == 1
    assert "elegirCategoria(1);" in html

    js = _js_de("/productos")
    # El umbral es el mismo que aplica el backend.
    assert "const MINIMO_SIMILARES = 10;" in js
    assert "/api/v1/productos/similares?" in js
    # En la edición no se busca: la descripción ya viene puesta y el
    # desplegable se abriría solo, ofreciendo el producto que se edita.
    assert "if (this.form.id || texto.length < MINIMO_SIMILARES)" in js
    # Las respuestas pueden llegar desordenadas; la vieja no pisa a la nueva.
    assert "token !== this.similaresToken" in js


def test_el_choque_de_descripcion_se_avisa_antes_de_apretar_crear(client, crear_usuario):
    """
    El alta lo rechaza igual —lo controla el service y lo garantiza un índice
    único—, pero enterarse recién con el error obliga a volver a un campo que
    quedó abajo del formulario.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    html = client.get("/productos").text

    assert "duplicadoExacto()" in html
    assert "en esta categoría y proveedor" in html

    js = _js_de("/productos")
    # Solo con los dos elegidos: la lista se acota con ellos, y sin ellos un
    # nombre repetido en otra categoría no es ningún choque.
    assert "!this.form.categoria_id || !this.form.proveedor_id" in js


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

    # Los campos del formulario, incluidos los que el prompt perdía. El
    # stock mínimo ya no está: desde la 0022 es por ubicación y se carga en
    # la pantalla de stock, porque el mismo artículo necesita un colchón
    # distinto en el CD que en un local.
    for campo in ('id="va-sufijo"', 'id="va-ubicacion"', 'id="va-skuprov"'):
        assert campo in html, f"falta {campo} en el modal de variante"
    assert 'id="va-stock-min"' not in html

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
        # Las pantallas de stock mantienen "Gestión de Stock" activo.
        "/gestion-de-stock": "/gestion-de-stock",
        "/stock": "/gestion-de-stock",
        "/remitos": "/gestion-de-stock",
        "/auditorias-inventario": "/gestion-de-stock",
        "/motivos-baja": "/gestion-de-stock",
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
        "/stock": "/gestion-de-stock",
        "/remitos": "/gestion-de-stock",
        "/auditorias-inventario": "/gestion-de-stock",
        "/motivos-baja": "/stock",
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
    punto = servicio.crear_punto(db, autor, "Patio Olmos", TipoPuntoVenta.LOCAL, "PO")
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
    """
    Cada uno con su título y su ítem del sidebar marcado.

    `/ventas` salió de esta lista al implementarse el módulo: ahora sirve el
    listado de escritorio o el home mobile según el dispositivo. Lo cubre
    `test_ventas_rutea_por_dispositivo`.
    """
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    for ruta, titulo in {"/reportes": "Reportes", "/ajustes": "Ajustes"}.items():
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


def test_ningun_desactivar_ejecuta_sin_confirmar(client, crear_usuario):
    """
    Toda baja pide confirmación antes de ejecutarse.

    En /productos el botón llamaba derecho a `cambiarEstado(...)`: un clic al
    lado de "Producto", en una tabla donde cada fila es una variante, y el
    producto entero quedaba desactivado con todas sus variantes.

    Se comprueba sobre el HTML porque es donde está el cableado: el botón
    tiene que abrir el diálogo, no disparar la acción.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    # (pantalla, expresión que NO puede estar en un botón de desactivar)
    pantallas = {
        "/productos": "cambiarEstado(v.producto, false)",
        "/usuarios": "cambiarEstado(u, false)",
        "/dispositivos": "cambiarEstado(d, false)",
        "/roles": "cambiarEstado(rol, false)",
        "/puntos-de-venta": "cambiarEstado(p, false",
    }

    for url, ejecucion_directa in pantallas.items():
        html = client.get(url).text
        assert ejecucion_directa not in html, f"{url} desactiva sin confirmar"
        # Y el diálogo está en la página para poder confirmar.
        assert 'role="dialog"' in html and "Cancelar" in html, f"{url} no tiene el diálogo"


def test_las_bajas_usan_el_mismo_componente_de_confirmacion(client, crear_usuario):
    """
    El diálogo estaba copiado en tres pantallas con diferencias que nadie
    decidió (`rounded-[20px]` contra `rounded-input`, `p-8` contra `p-6`), y
    dos pantallas no lo tenían. Ahora sale todo de un macro.

    Se verifica por el `aria-labelledby` que genera el macro, que ninguna
    copia a mano tenía.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    for url, estado in (
        ("/productos", "confirmacion"),
        ("/usuarios", "confirmacion"),
        ("/dispositivos", "confirmacion"),
        ("/roles", "confirmacion"),
        ("/puntos-de-venta", "baja"),
        ("/categorias", "confirmacion"),
    ):
        html = client.get(url).text
        assert f'aria-labelledby="titulo-{estado}"' in html, f"{url} no usa el macro"


def test_ninguna_pantalla_usa_los_dialogos_del_navegador(client, crear_usuario):
    """
    Ni `confirm()`, ni `alert()`, ni `prompt()`: todos se ven como un cartel
    de Chrome en vez del sistema, no se pueden estilar y no dan lugar a
    explicar la consecuencia de lo que se está por hacer.

    Los tenían `/dispositivos` (dar de baja un equipo), el cambio masivo de
    dólar y el guardado del árbol de permisos. Ahora todos usan
    `components/modal_confirmacion.html`.
    """
    import pathlib
    import re

    js = pathlib.Path(__file__).parent.parent / "app" / "static" / "js"

    # Se ignoran las menciones dentro de comentarios, que explican por qué se
    # sacaron: lo que se busca es la LLAMADA.
    nativo = re.compile(r"(?<![a-zA-Z.`])(confirm|alert|prompt)\s*\(")
    culpables = {}
    for archivo in js.glob("*.js"):
        codigo = "\n".join(
            linea for linea in archivo.read_text().split("\n")
            if not linea.lstrip().startswith(("*", "//", "/*"))
        )
        hallazgos = nativo.findall(codigo)
        if hallazgos:
            culpables[archivo.name] = hallazgos

    assert not culpables, f"diálogos nativos del navegador: {culpables}"


def test_los_modales_no_se_cierran_al_clickear_afuera(client, crear_usuario):
    """
    Un clic al costado de un alta cerraba el modal y se llevaba todo lo
    cargado. Ahora se sale por la X, por Cancelar o con Escape.

    El test mira el HTML SERVIDO y no las plantillas —de eso se ocupa
    `test_ningun_modal_se_cierra_al_clickear_el_velo`— porque acá interesa la
    otra mitad del trato: sacar el clic afuera no puede dejar un modal sin
    salida. Cada pantalla con modales tiene que seguir ofreciendo la X o el
    botón Cancelar.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    for url in ("/productos", "/usuarios", "/proveedores", "/roles",
                "/dispositivos", "/puntos-de-venta", "/categorias"):
        html = client.get(url).text
        assert "@click.self" not in html, f"{url} cierra el modal al clickear el velo"
        assert 'aria-label="Cerrar"' in html or "Cancelar" in html, (
            f"{url} quedó con un modal sin forma de salir"
        )


def test_los_listados_arrancan_mostrando_solo_los_activos(client, crear_usuario):
    """
    Lo dado de baja no ensucia la pantalla del día a día: se ve apagando el
    switch, pero no de entrada. En /dispositivos la diferencia es enorme —de
    36 filas cargadas, 4 están activas—.

    El filtro es el string 'true' y no un booleano: así entra sin cambios en
    el bucle que arma los query params de cada pantalla, que saltea los
    vacíos y manda el resto tal cual.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    for url in ("/productos", "/usuarios", "/puntos-de-venta", "/dispositivos",
                "/roles", "/motivos-baja"):
        html = client.get(url).text
        assert "activo: 'true'" in html or "activo: 'true'" in _js_de(url), (
            f"{url} no arranca filtrado por activos"
        )


def _js_de(url: str) -> str:
    """El JS de cada pantalla, donde vive el estado inicial de los filtros."""
    import pathlib

    archivos = {
        "/productos": "productos.js",
        "/usuarios": "usuarios.js",
        "/puntos-de-venta": "puntos_de_venta.js",
        "/dispositivos": "dispositivos.js",
        "/roles": "roles.js",
        "/motivos-baja": "motivos_baja.js",
        "/proveedores": "proveedores.js",
        "/stock": "stock.js",
        "/remitos": "remitos.js",
        "/auditorias-inventario": "auditorias.js",
    }
    base = pathlib.Path(__file__).parent.parent / "app" / "static" / "js"
    return (base / archivos[url]).read_text()


def test_el_switch_solo_activos_esta_en_los_seis_listados(client, crear_usuario):
    """
    Mismo control en todos: un `role="switch"` del macro `switch_activos`.
    Antes eran tres selects distintos —y dos pantallas sin nada—, y ninguno
    arrancaba filtrado.
    """
    crear_usuario("cm", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "cm", "password": "Test1234!"})

    for url in ("/productos", "/usuarios", "/puntos-de-venta", "/dispositivos",
                "/roles", "/motivos-baja"):
        html = client.get(url).text
        assert 'role="switch"' in html, f"{url} no tiene el switch"
        assert "Solo activos" in html, f"{url} no tiene el label"
        # `ml-auto` es lo que lo alinea contra la derecha de la fila.
        assert "ml-auto" in html, f"{url}: el switch no está alineado a la derecha"
        # Y el select viejo de estado no puede haber quedado al lado.
        assert 'x-model="filtros.activo"' not in html, f"{url} conserva el select viejo"


def test_limpiar_filtros_no_muestra_los_inactivos(client, crear_usuario):
    """
    "Limpiar filtros" vuelve al estado de entrada, no a "mostrar todo": si
    reseteara `activo` a vacío, limpiar traería los dados de baja, que es lo
    contrario de lo que espera quien limpia para volver a empezar.
    """
    for url in ("/productos", "/usuarios", "/puntos-de-venta", "/dispositivos",
                "/roles", "/motivos-baja"):
        js = _js_de(url)
        limpiar = js[js.index("limpiar()"):]
        limpiar = limpiar[:limpiar.index("cargar()")]
        assert "activo: 'true'" in limpiar, f"{url}: limpiar() apaga el filtro de activos"


def test_proveedores_arranca_en_activo_con_su_propio_select(client, crear_usuario):
    """
    Proveedores no lleva el switch: tiene TRES estados (activo, desactivado,
    inhabilitado) y un sí/no no los distingue. Conserva su select, pero
    arranca en 'activo' para que la pantalla abra igual que las demás.
    """
    js = _js_de("/proveedores")
    assert "estado: 'activo'" in js
    limpiar = js[js.index("limpiar()"):]
    assert "estado: 'activo'" in limpiar[:limpiar.index("cargar()")]


# ============================================================================
# CONTROL DE STOCK: las tres pantallas
# ============================================================================


def _sesion_maestra(client, crear_usuario, nombre="cm_stock"):
    crear_usuario(nombre, ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": nombre, "password": "Test1234!"})


PANTALLAS_STOCK = ("/stock", "/remitos", "/auditorias-inventario")


def test_las_tres_pantallas_de_stock_responden(client, crear_usuario):
    """Un 500 acá sería una plantilla rota, que ningún otro test detecta."""
    _sesion_maestra(client, crear_usuario)

    for url in PANTALLAS_STOCK:
        resp = client.get(url)
        assert resp.status_code == 200, f"{url} devolvió {resp.status_code}"


def test_las_tres_pantallas_estan_en_el_hub_del_modulo(client, crear_usuario):
    """
    El sidebar tiene UNA entrada de stock y las tres pantallas cuelgan de su
    página de menú, igual que las secciones de Configuraciones. Con las tres
    sueltas en el sidebar el módulo se leía como tres cosas separadas.

    En el hub van en su orden real de uso: primero lo que hay, después lo que
    se mueve entre locales, y al final lo que se cuenta.
    """
    _sesion_maestra(client, crear_usuario)
    hub = client.get("/gestion-de-stock").text

    posiciones = [hub.index(f'href="{url}"') for url in PANTALLAS_STOCK]
    assert posiciones == sorted(posiciones), "el hub no respeta el orden"

    # Y el sidebar no las lleva: la entrada del módulo es la del hub, que va
    # después de Productos porque primero está el catálogo.
    menu = hub.split('<main')[0]
    assert 'href="/gestion-de-stock"' in menu
    for url in PANTALLAS_STOCK:
        assert f'href="{url}"' not in menu, f"{url} quedó suelta en el sidebar"
    assert menu.index('href="/productos"') < menu.index('href="/gestion-de-stock"')


def test_un_vendedor_sin_local_asignado_ve_las_pantallas_vacias(
    client, db, crear_usuario, crear_punto_de_venta
):
    """
    Criterio de aceptación del módulo: sin datos, sin filtros y sin acciones,
    con el motivo escrito. Mostrarle el stock de todos los locales sería peor
    que no mostrarle ninguno, y elegir uno por él sería adivinar.

    El cartel se decide en el servidor: pedirlo por API obligaría a dibujar la
    pantalla entera y vaciarla después.
    """
    from app.core.device_scope import MENSAJE_SIN_ASIGNACION
    from app.models.dispositivo import Dispositivo

    crear_usuario("vende", ROL_VENDEDOR)
    equipo = Dispositivo(descripcion="Sin asignar", activo=True, punto_de_venta_id=None)
    db.add(equipo)
    db.flush()

    client.cookies.set("device_uuid", str(equipo.uuid))
    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})

    for url in PANTALLAS_STOCK:
        html = client.get(url).text
        assert MENSAJE_SIN_ASIGNACION in html, f"{url} no explica por qué está vacía"
        # Ni tabla, ni filtros, ni botón de alta.
        assert "<table" not in html, f"{url} dibuja la tabla igual"
        assert "Limpiar filtros" not in html, f"{url} deja los filtros"


def test_un_vendedor_con_local_asignado_no_elige_ubicacion(
    client, db, crear_usuario, crear_punto_de_venta
):
    """
    Con una sola ubicación a la vista, un filtro por punto de venta no acota
    nada: ofrecerlo sugiere que se puede mirar otro local, y no se puede.
    """
    from app.models.dispositivo import Dispositivo
    from app.models.punto_de_venta import TipoPuntoVenta

    local = crear_punto_de_venta("MPO", "Patio Olmos", TipoPuntoVenta.LOCAL)
    crear_usuario("vende", ROL_VENDEDOR)
    equipo = Dispositivo(descripcion="Caja", activo=True, punto_de_venta_id=local.id)
    db.add(equipo)
    db.flush()

    client.cookies.set("device_uuid", str(equipo.uuid))
    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})

    html = client.get("/stock").text
    assert 'id="f-punto"' not in html, "el filtro de ubicación no debería estar"
    # Y la pantalla sí se dibuja: este equipo tiene local.
    assert "<table" in html
    assert f"puntoFijo: {local.id}" in html


def test_la_pantalla_de_stock_no_deja_editar_la_cantidad(client, crear_usuario):
    """
    La cantidad se mueve con movimientos, que son los que dejan el rastro de
    por qué cambió. Lo único editable a mano son los mínimos de reposición.
    """
    _sesion_maestra(client, crear_usuario)
    html = client.get("/stock").text

    assert 'x-model="minimos.stock_minimo_cd"' in html
    assert 'x-model="minimos.stock_minimo_local"' in html
    # No hay ningún campo atado a la cantidad de una fila de stock.
    assert 'x-model="f.cantidad"' not in html
    # Las tres puertas por las que sí se mueve.
    for accion in ("abrirIngreso()", "abrirBaja(f)", "abrirMinimos(f)"):
        assert accion in html, f"falta {accion}"


def test_la_recepcion_pide_el_numero_del_remito(client, crear_usuario):
    """
    El número está impreso en el papel que viaja con la carga: tenerlo es la
    prueba de que la mercadería llegó a destino. Si no coincide, la API
    devuelve 403.
    """
    _sesion_maestra(client, crear_usuario)
    html = client.get("/remitos").text

    assert 'x-model="recepcion.numero_confirmacion"' in html
    assert "impreso arriba a la derecha" in html
    # Las cantidades vienen precargadas con lo enviado: lo normal es que
    # llegue todo, y tipear cada línea para el caso habitual invita a errar.
    js = _js_de("/remitos")
    assert "recibida: i.cantidad_enviada" in js


def test_el_remito_muestra_cada_accion_en_su_estado(client, crear_usuario):
    """
    Un remito ya confirmado no se despacha ni se vuelve a recibir: cada botón
    aparece solo donde tiene sentido.
    """
    _sesion_maestra(client, crear_usuario)
    html = client.get("/remitos").text

    assert "r.estado === 'pendiente'" in html          # despachar
    assert "['pendiente','en_camino'].includes(r.estado)" in html  # recibir
    assert 'x-show="r.pdf_url"' in html                # reimprimir


def test_la_auditoria_separa_contar_de_aprobar(client, crear_usuario):
    """
    El que cuenta no valida su propio conteo: aprobar y rechazar aparecen
    recién con el conteo cerrado, y la API los pide con otro permiso.
    """
    _sesion_maestra(client, crear_usuario)
    html = client.get("/auditorias-inventario").text

    assert "a.estado === 'en_curso'" in html, "contar tiene que ser solo del conteo abierto"
    assert "detalle.auditoria?.estado === 'pendiente_aprobacion'" in html
    assert "confirmarAprobacion()" in html and "confirmarRechazo()" in html
    # Las dos decisiones piden confirmación: mueven stock o lo dejan quieto,
    # y las dos son difíciles de deshacer.
    assert "modal_confirmacion" not in html, "el macro se renderiza, no se nombra"
    assert 'x-show="confirmacion.abierta"' in html


def test_el_conteo_se_carga_sin_soltar_el_teclado(client, crear_usuario):
    """
    Contar un estante es escanear, tipear la cantidad y seguir. Enter pasa del
    código a la cantidad y de la cantidad al registro, y el foco vuelve al
    código.
    """
    _sesion_maestra(client, crear_usuario)
    html = client.get("/auditorias-inventario").text

    assert "$refs.cantidad.focus()" in html
    assert '@keydown.enter.prevent="registrar()"' in html

    js = _js_de("/auditorias-inventario")
    assert "document.getElementById('co-codigo')?.focus()" in js


def test_las_pantallas_no_ofrecen_acciones_sin_permiso(
    client, db, crear_usuario, crear_punto_de_venta, roles, dar_permiso
):
    """
    Esconder un botón no es la barrera —el endpoint valida igual— pero
    ofrecer una acción que siempre termina en 403 es peor que no ofrecerla:
    quien la toca no tiene forma de saber que nunca le iba a funcionar.

    Un vendedor cuenta y da de baja en su local, pero no ingresa mercadería
    ni arma envíos ni aprueba conteos.
    """
    from app.core.permisos import Modulo, Recurso
    from app.models.dispositivo import Dispositivo
    from app.models.punto_de_venta import TipoPuntoVenta

    local = crear_punto_de_venta("MPO", "Patio Olmos", TipoPuntoVenta.LOCAL)
    crear_usuario("vende", ROL_VENDEDOR)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.STOCK, ver=True)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.STOCK,
                recurso=Recurso.STOCK_BAJA, crear=True)
    dar_permiso(rol_id=roles[ROL_VENDEDOR].id, modulo=Modulo.STOCK,
                recurso=Recurso.STOCK_AUDITORIA, crear=True)

    equipo = Dispositivo(descripcion="Caja", activo=True, punto_de_venta_id=local.id)
    db.add(equipo)
    db.flush()
    client.cookies.set("device_uuid", str(equipo.uuid))
    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})

    stock = client.get("/stock").text
    assert "Ingreso de mercadería" not in stock, "el vendedor no ingresa mercadería"
    assert "abrirBaja(f)" in stock, "sí puede dar de baja en su local"
    assert "abrirMinimos(f)" not in stock, "los mínimos los define quien administra"

    remitos = client.get("/remitos").text
    assert "Armar envío" not in remitos, "armar envíos es de Distribución"

    auditorias = client.get("/auditorias-inventario").text
    assert "Iniciar conteo" in auditorias, "sí puede contar su local"
    assert "confirmarAprobacion()" not in auditorias, "aprobar es del Dueño"


def test_las_pantallas_de_stock_no_dependen_del_permiso_de_configuracion(
    client, crear_usuario
):
    """
    El catálogo de ubicaciones sale de `/stock/ubicaciones` y no de
    `/puntos-de-venta`, que pide permiso de CONFIGURACIÓN: un vendedor no lo
    tiene, y sin esto no podría ni iniciar un conteo en su propio local.
    """
    _sesion_maestra(client, crear_usuario, "cm_ubic")

    for url in PANTALLAS_STOCK:
        js = _js_de(url)
        assert "/api/v1/stock/ubicaciones" in js, f"{url} no usa el endpoint del módulo"
        assert "/api/v1/puntos-de-venta" not in js, f"{url} sigue pidiendo Configuración"


# ============================================================================
# VENTAS
# ============================================================================


def test_ventas_rutea_por_dispositivo(client, db, crear_usuario, crear_punto_de_venta):
    """
    El equipo decide qué pantalla se sirve, no el usuario ni el ancho del
    navegador.

    Es la regla del módulo: desde un celular registrado en un local se
    trabaja el punto de venta, y desde cualquier otro equipo se mira el
    listado. Si dependiera del ancho, una vendedora que gira el teléfono
    perdería la caja, y un supervisor en una notebook angosta recibiría el
    flujo de venta.
    """
    from app.models.dispositivo import Dispositivo
    from app.models.punto_de_venta import TipoPuntoVenta

    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    # Sin dispositivo de local: listado de escritorio.
    html = client.get("/ventas").text
    assert "listadoVentas(" in html
    assert "homeVentas()" not in html

    # Con un equipo asignado a un local: el home de la vendedora.
    local = crear_punto_de_venta("MPO", "Patio Olmos", TipoPuntoVenta.LOCAL)
    equipo = Dispositivo(descripcion="Caja", activo=True, punto_de_venta_id=local.id)
    db.add(equipo)
    db.flush()
    client.cookies.set("device_uuid", str(equipo.uuid))

    html = client.get("/ventas").text
    assert "homeVentas()" in html
    assert "listadoVentas(" not in html


def test_las_pantallas_del_flujo_son_solo_mobile(client, crear_usuario):
    """
    Entrar al carrito desde una notebook manda al listado, no dibuja una
    pantalla de 390px estirada a 1440.
    """
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    for ruta in ("/ventas/nueva", "/ventas/carrito", "/ventas/finalizar",
                 "/ventas/consulta-stock"):
        resp = client.get(ruta, follow_redirects=False)
        assert resp.status_code == 303, ruta
        assert resp.headers["location"] == "/ventas", ruta


def test_el_layout_mobile_no_arrastra_el_sidebar(client, db, crear_usuario,
                                                 crear_punto_de_venta):
    """
    En el celular no hay sidebar: lo reemplaza la barra inferior fija, con
    los tres destinos al alcance del pulgar.
    """
    from app.models.dispositivo import Dispositivo
    from app.models.punto_de_venta import TipoPuntoVenta

    local = crear_punto_de_venta("MPO", "Patio Olmos", TipoPuntoVenta.LOCAL)
    crear_usuario("vende", ROL_VENDEDOR)
    equipo = Dispositivo(descripcion="Caja", activo=True, punto_de_venta_id=local.id)
    db.add(equipo)
    db.flush()

    client.cookies.set("device_uuid", str(equipo.uuid))
    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})

    html = client.get("/ventas").text
    assert 'id="sidebar-nav"' not in html
    assert 'aria-label="Navegación del punto de venta"' in html
    # Los tres destinos de la barra.
    for destino in ("/ventas", "/ventas/nueva", "/ventas/consulta-stock"):
        assert f'href="{destino}"' in html, destino


def test_la_barra_inferior_respeta_el_area_segura(client, db, crear_usuario,
                                                  crear_punto_de_venta):
    """
    Sin `env(safe-area-inset-bottom)` la barra queda debajo del indicador de
    gestos del iPhone y el botón central se vuelve intocable — justo el que
    más se usa.
    """
    from app.models.dispositivo import Dispositivo
    from app.models.punto_de_venta import TipoPuntoVenta

    local = crear_punto_de_venta("MPO", "Patio Olmos", TipoPuntoVenta.LOCAL)
    crear_usuario("vende", ROL_VENDEDOR)
    equipo = Dispositivo(descripcion="Caja", activo=True, punto_de_venta_id=local.id)
    db.add(equipo)
    db.flush()

    client.cookies.set("device_uuid", str(equipo.uuid))
    client.post("/api/v1/auth/login", json={"username": "vende", "password": "Test1234!"})

    html = client.get("/ventas").text
    assert "env(safe-area-inset-bottom)" in html
    assert "viewport-fit=cover" in html


def test_el_descuento_se_elige_de_una_lista_y_no_se_escribe(
    client, db, crear_usuario, crear_punto_de_venta
):
    """
    La vendedora NO puede escribir un porcentaje: elige de la lista de 5 en
    5. Un `<input type="number">` en el modal de descuento sería la puerta
    de atrás que la regla del backend viene a cerrar.
    """
    from app.models.dispositivo import Dispositivo
    from app.models.punto_de_venta import TipoPuntoVenta

    local = crear_punto_de_venta("MPO", "Patio Olmos", TipoPuntoVenta.LOCAL)
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    equipo = Dispositivo(descripcion="Caja", activo=True, punto_de_venta_id=local.id)
    db.add(equipo)
    db.flush()

    client.cookies.set("device_uuid", str(equipo.uuid))
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    html = client.get("/ventas/carrito").text
    # Los porcentajes son botones alimentados por la lista del backend.
    assert 'x-for="p in porcentajes"' in html
    assert 'x-model="descuento.porcentaje"' not in html
    # Y el motivo va primero: el porcentaje queda deshabilitado sin él.
    assert ':disabled="!descuento.motivo_id"' in html


def test_las_pantallas_de_ventas_no_calculan_precios():
    """
    El total, los descuentos y los recargos los resuelve el backend. Si la
    pantalla hiciera su propia cuenta y diera distinto, la vendedora vería un
    número y el cliente pagaría otro.

    Se permite el reparto entre dos medios y el preview del recargo: son
    ayudas para completar el formulario, y el backend los vuelve a calcular
    antes de cobrar.
    """
    import pathlib

    js = (
        pathlib.Path(__file__).parent.parent / "app" / "static" / "js" / "ventas_mobile.js"
    ).read_text()

    # El total a cobrar siempre sale de la respuesta, nunca de sumar ítems.
    assert "venta.a_cobrar" in js
    assert "precio_final" not in js, "la pantalla está sumando los ítems por su cuenta"


def test_las_secciones_de_configuracion_de_ventas_resuelven(client, crear_usuario):
    """Las tres cuelgan del hub y ninguna puede llevar a un 404."""
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    hub = client.get("/configuracion").text
    for nombre in ("Medios de pago", "Motivos de descuento", "Promociones"):
        assert nombre in hub, nombre

    for ruta, componente in {
        "/medios-de-pago": "abmMediosDePago",
        "/motivos-descuento": "abmMotivosDescuento",
        "/promociones": "abmPromociones",
    }.items():
        resp = client.get(ruta)
        assert resp.status_code == 200, ruta
        assert componente in resp.text, ruta


def test_clientes_es_modulo_propio_en_el_sidebar(client, crear_usuario):
    """
    El cliente se carga en el día a día de la venta, no cuando se configura
    el sistema: por eso está en el sidebar y no dentro de Configuraciones.
    """
    crear_usuario("admin", ROL_CUENTA_MAESTRA)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Test1234!"})

    aside = client.get("/").text.split("<aside")[1].split("</aside>")[0]
    assert 'href="/clientes"' in aside

    assert "abmClientes" in client.get("/clientes").text
