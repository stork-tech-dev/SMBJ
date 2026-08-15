"""
Rutas HTML servidas con Jinja2.

Estas rutas NO son la API: solo renderizan las plantillas. Los datos los
piden los templates a /api/v1 (Principio 1: la API es el contrato, el
frontend es un consumidor más).

El control de acceso de las páginas es solo de navegación (redirige al
login si no hay sesión). La barrera real está en la API: cada endpoint
valida con `resolver_permiso`, así que no alcanza con adivinar una URL.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permisos import (
    ROL_CUENTA_MAESTRA,
    Modulo,
    get_current_user,
    resolver_permiso,
)
from app.core.templates import templates
from app.models.categoria import NIVEL_MAXIMO
from app.services import configuracion as servicio_configuracion
from app.services import roles as servicio_roles
from app.services import usuarios as servicio_usuarios
from app.services.auth import debe_cambiar_password

router = APIRouter(include_in_schema=False)

# Estructura del sidebar. Vive acá y no en el template para que agregar
# un módulo sea una línea de Python y no tocar HTML (Principio 2).
# `modulo` es el permiso que se necesita para ver el ítem; None = siempre.
# `solo_maestra` lo restringe a la Cuenta Maestra.
# `hub_configuracion` marca el ítem que agrupa CONFIGURACION_SECCIONES: se
# muestra si el usuario puede ver al menos una de esas secciones.
# `oculto` lo esconde de TODOS los perfiles, sin importar sus permisos: es
# para módulos cuya pantalla todavía no existe.
MENU_SIDEBAR = [
    {"nombre": "Home", "url": "/", "icono": "home", "modulo": None},
    {"nombre": "Proveedores", "url": "/proveedores", "icono": "truck", "modulo": Modulo.PROVEEDORES},
    {"nombre": "Productos", "url": "/productos", "icono": "box", "modulo": Modulo.PRODUCTOS},
    {"nombre": "Ventas", "url": "/ventas", "icono": "cart", "modulo": Modulo.VENTAS},
    {"nombre": "Reportes", "url": "/reportes", "icono": "chart", "modulo": Modulo.REPORTES},
    # Oculto hasta que exista su pantalla: hoy /auditoria no tiene ruta HTML
    # y el ítem llevaba a un 404. El endpoint GET /api/v1/auditoria sigue
    # funcionando; lo que se esconde es la entrada del menú. Para reactivarlo
    # alcanza con borrar la línea `"oculto": True`.
    {
        "nombre": "Auditoría",
        "url": "/auditoria",
        "icono": "list",
        "modulo": Modulo.AUDITORIA,
        "oculto": True,
    },
    {
        "nombre": "Configuraciones",
        "url": "/configuracion",
        "icono": "settings",
        "modulo": None,
        # Hub de secciones: visible si el usuario puede ver alguna de las
        # de CONFIGURACION_SECCIONES. Se deriva de esa lista en vez de
        # repetir acá los módulos, para que agregar una sección no obligue
        # a acordarse de tocar también el sidebar (Principio 2).
        "hub_configuracion": True,
    },
]

MENU_SIDEBAR_PIE = [
    {"nombre": "Ajustes", "url": "/ajustes", "icono": "sliders", "modulo": None},
]

# Secciones que se muestran como tarjetas dentro de la página de
# Configuraciones (diseño "Configuraciones CM"). Agregar una sección nueva
# es una línea acá; cada una se muestra solo si el usuario tiene su permiso.
CONFIGURACION_SECCIONES = [
    {
        "nombre": "Usuarios",
        "descripcion": "Altas, permisos e historial de accesos",
        "url": "/usuarios",
        "modulo": Modulo.USUARIOS,
    },
    {
        "nombre": "Roles",
        "descripcion": "Perfiles de permisos y su alcance por módulo",
        "url": "/roles",
        "modulo": None,
        "solo_maestra": True,
    },
    {
        "nombre": "Puntos de venta",
        "descripcion": "Locales, Centro de Distribución y tiendas online",
        "url": "/puntos-de-venta",
        "modulo": Modulo.CONFIGURACION,
    },
    {
        "nombre": "Dispositivos",
        "descripcion": "Celulares corporativos y su asignación a locales",
        "url": "/dispositivos",
        "modulo": Modulo.DISPOSITIVOS,
    },
]


def usuario_de_pagina(request: Request, db: Session = Depends(get_db)):
    """
    Como `get_current_user`, pero para páginas HTML: en lugar de 401
    devuelve None, para poder redirigir al login en vez de mostrar un JSON.
    """
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None


def _redirigir(destino: str) -> HTTPException:
    """Redirección 303 desde una dependency."""
    return HTTPException(status_code=303, headers={"Location": destino})


def requiere_sesion(usuario=Depends(usuario_de_pagina)):
    """
    Dependency de todas las páginas del sistema.

    Concentra las dos redirecciones de navegación —sin sesión al login,
    con cambio de contraseña pendiente a esa pantalla— para que ninguna
    página se olvide de alguna (Principio 2: DRY).

    No es la barrera de seguridad: esa es `resolver_permiso` en la API.
    """
    if usuario is None:
        raise _redirigir("/login")
    if debe_cambiar_password(usuario):
        raise _redirigir("/cambiar-password")
    return usuario


def _es_maestra(usuario) -> bool:
    return usuario.rol is not None and usuario.rol.nombre == ROL_CUENTA_MAESTRA


def _visible(db: Session, usuario, item: dict, es_maestra: bool) -> bool:
    """
    Regla de visibilidad única para los ítems del sidebar y para las
    tarjetas de Configuraciones (Principio 2: una sola tabla de verdades).

    Sin esto, mover un ítem al hub le cambiaría silenciosamente las reglas
    de acceso: las tarjetas se filtraban solo por módulo e ignoraban
    `solo_maestra`, que es lo que protege a Roles.
    """
    # Se evalúa primero: un ítem oculto no se muestra a nadie, ni siquiera
    # a la Cuenta Maestra.
    if item.get("oculto"):
        return False

    if item.get("solo_maestra"):
        return es_maestra
    # Hub de Configuraciones: visible si alguna de sus secciones lo es.
    if item.get("hub_configuracion"):
        return any(
            _visible(db, usuario, s, es_maestra) for s in CONFIGURACION_SECCIONES
        )
    if item.get("modulo") is None:
        return True
    return resolver_permiso(db, usuario.id, item["modulo"], "ver")


def menu_visible(db: Session, usuario) -> tuple[list, list]:
    """
    Filtra el sidebar según lo que el usuario puede ver. Usa la misma
    `resolver_permiso` que la API: no hay una segunda tabla de verdades.
    """
    es_maestra = _es_maestra(usuario)
    return (
        [i for i in MENU_SIDEBAR if _visible(db, usuario, i, es_maestra)],
        [i for i in MENU_SIDEBAR_PIE if _visible(db, usuario, i, es_maestra)],
    )


def secciones_configuracion(db: Session, usuario) -> list[dict]:
    """Tarjetas de la página de Configuraciones visibles para el usuario."""
    es_maestra = _es_maestra(usuario)
    return [s for s in CONFIGURACION_SECCIONES if _visible(db, usuario, s, es_maestra)]


def contexto_base(request: Request, db: Session, actual, **extra) -> dict:
    """
    Contexto común a todas las páginas: evita repetirlo en cada ruta.

    El parámetro se llama `actual` y no `usuario` a propósito: varias
    páginas pasan en `extra` un `usuario` distinto (el que se está
    editando), y el nombre chocaría.
    """
    menu, menu_pie = menu_visible(db, actual)
    return {
        "request": request,
        "menu": menu,
        "menu_pie": menu_pie,
        "usuario_actual": actual,
        # Para los campos que solo decide la Cuenta Maestra (hoy el stock
        # infinito del producto). Va acá y no en cada ruta para que la
        # pregunta se escriba una sola vez (Principio 2), y sale de la misma
        # `_es_maestra()` que filtra el sidebar: una sola tabla de verdades.
        #
        # No es la barrera de seguridad —esconder un campo no impide mandarlo
        # por la API—: esa vive en el service, que es por donde pasan todos
        # los clientes.
        "es_maestra": _es_maestra(actual),
        # Define qué logotipo se muestra ('S' Soleil / 'M' Mallorca).
        "letra_empresa": servicio_configuracion.letra_empresa(db),
        **extra,
    }


# ============================================================================
# Autenticación
# ============================================================================


@router.get("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    db: Session = Depends(get_db),
    usuario=Depends(usuario_de_pagina),
):
    """Si ya hay sesión activa, va derecho al dashboard."""
    if usuario is not None:
        return RedirectResponse("/", status_code=303)

    # Saludo del local: solo en dispositivos activos y asignados. Se
    # resuelve desde la cookie, en modo lectura — renderizar el login no
    # crea ni modifica ningún dispositivo.
    from app.services.device_service import local_a_saludar
    from config import settings as configuracion

    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {
            "request": request,
            "letra_empresa": servicio_configuracion.letra_empresa(db),
            "local_dispositivo": local_a_saludar(
                db, request.cookies.get(configuracion.DEVICE_COOKIE_NAME)
            ),
        },
    )


@router.get("/cambiar-password", response_class=HTMLResponse)
async def cambiar_password(
    request: Request,
    db: Session = Depends(get_db),
    usuario=Depends(usuario_de_pagina),
):
    if usuario is None:
        return RedirectResponse("/login", status_code=303)

    return templates.TemplateResponse(
        request,
        "auth/cambiar_password.html",
        {"request": request, "letra_empresa": servicio_configuracion.letra_empresa(db)},
    )


# ============================================================================
# Páginas del sistema
# ============================================================================


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request, db: Session = Depends(get_db), usuario=Depends(requiere_sesion)
):
    """Dashboard."""

    return templates.TemplateResponse(
        request,
        "pages/index.html",
        contexto_base(request, db, usuario, titulo="Inicio", ruta_activa="/"),
    )


@router.get("/usuarios", response_class=HTMLResponse)
async def usuarios(
    request: Request, db: Session = Depends(get_db), usuario=Depends(requiere_sesion)
):
    return templates.TemplateResponse(
        request,
        "pages/usuarios/listado.html",
        contexto_base(request, db, usuario, titulo="Usuarios", ruta_activa="/configuracion"),
    )


@router.get("/usuarios/{usuario_id}/permisos", response_class=HTMLResponse)
async def usuario_permisos(
    usuario_id: int,
    request: Request,
    db: Session = Depends(get_db),
    usuario=Depends(requiere_sesion),
):
    try:
        objetivo = servicio_usuarios.obtener_usuario(db, usuario_id)
    except servicio_roles.NoEncontrado as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return templates.TemplateResponse(
        request,
        "pages/usuarios/permisos.html",
        contexto_base(
            request, db, usuario,
            titulo=f"Permisos de {objetivo.nombre}",
            ruta_activa="/configuracion",
            usuario=objetivo,
        ),
    )


@router.get("/usuarios/{usuario_id}/historial", response_class=HTMLResponse)
async def usuario_historial(
    usuario_id: int,
    request: Request,
    db: Session = Depends(get_db),
    usuario=Depends(requiere_sesion),
):
    try:
        objetivo = servicio_usuarios.obtener_usuario(db, usuario_id)
    except servicio_roles.NoEncontrado as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return templates.TemplateResponse(
        request,
        "pages/usuarios/historial.html",
        contexto_base(
            request, db, usuario,
            titulo=f"Historial de {objetivo.nombre}",
            ruta_activa="/configuracion",
            usuario=objetivo,
        ),
    )


@router.get("/roles", response_class=HTMLResponse)
async def roles(
    request: Request, db: Session = Depends(get_db), usuario=Depends(requiere_sesion)
):
    return templates.TemplateResponse(
        request,
        "pages/roles/listado.html",
        contexto_base(request, db, usuario, titulo="Roles", ruta_activa="/configuracion"),
    )


@router.get("/roles/{rol_id}/permisos", response_class=HTMLResponse)
async def rol_permisos(
    rol_id: int,
    request: Request,
    db: Session = Depends(get_db),
    usuario=Depends(requiere_sesion),
):
    try:
        rol = servicio_roles.obtener_rol(db, rol_id)
    except servicio_roles.NoEncontrado as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return templates.TemplateResponse(
        request,
        "pages/roles/permisos.html",
        contexto_base(
            request, db, usuario,
            titulo=f"Permisos de {rol.nombre}",
            ruta_activa="/configuracion",
            rol=rol,
        ),
    )


@router.get("/proveedores", response_class=HTMLResponse)
async def proveedores(
    request: Request, db: Session = Depends(get_db), usuario=Depends(requiere_sesion)
):
    return templates.TemplateResponse(
        request,
        "pages/proveedores/listado.html",
        contexto_base(request, db, usuario, titulo="Proveedores", ruta_activa="/proveedores"),
    )


@router.get("/proveedores/dolar-masivo", response_class=HTMLResponse)
async def proveedores_dolar_masivo(
    request: Request, db: Session = Depends(get_db), usuario=Depends(requiere_sesion)
):
    return templates.TemplateResponse(
        request,
        "pages/proveedores/dolar_masivo.html",
        contexto_base(
            request, db, usuario, titulo="Cambio masivo del dólar", ruta_activa="/proveedores"
        ),
    )


@router.get("/configuracion", response_class=HTMLResponse)
async def configuracion(
    request: Request, db: Session = Depends(get_db), usuario=Depends(requiere_sesion)
):
    """Hub de Configuraciones: tarjetas hacia cada sección (diseño CM)."""
    return templates.TemplateResponse(
        request,
        "pages/configuracion/index.html",
        contexto_base(
            request, db, usuario,
            titulo="Configuraciones",
            ruta_activa="/configuracion",
            secciones=secciones_configuracion(db, usuario),
        ),
    )


# Módulos que todavía no se construyeron. Su ítem sigue en el sidebar —el
# usuario quiere verlos— y estas rutas existen solo para que resuelvan en
# vez de dar 404. Cuando cada módulo se implemente, su entrada sale de acá
# y pasa a tener su propia ruta.
MODULOS_PENDIENTES = {
    "/ventas": "Ventas",
    "/reportes": "Reportes",
    "/ajustes": "Ajustes",
}


def _registrar_pendientes() -> None:
    """
    Da de alta las rutas de los módulos pendientes.

    En un bucle y no una por una: las tres son idénticas salvo el título y
    la ruta activa, así que escribirlas a mano sería copiar tres veces el
    mismo handler.
    """
    for ruta, titulo in MODULOS_PENDIENTES.items():

        def _pagina(
            request: Request,
            db: Session = Depends(get_db),
            usuario=Depends(requiere_sesion),
            # Se capturan por defecto: sin esto las tres closures leerían
            # el valor de la última vuelta del bucle.
            _ruta: str = ruta,
            _titulo: str = titulo,
        ):
            return templates.TemplateResponse(
                request,
                "pages/pendiente.html",
                contexto_base(request, db, usuario, titulo=_titulo, ruta_activa=_ruta),
            )

        router.get(ruta, response_class=HTMLResponse, name=f"pendiente{ruta}")(_pagina)


_registrar_pendientes()


@router.get("/productos", response_class=HTMLResponse)
async def productos(
    request: Request, db: Session = Depends(get_db), usuario=Depends(requiere_sesion)
):
    return templates.TemplateResponse(
        request,
        "pages/productos/listado.html",
        contexto_base(
            request,
            db,
            usuario,
            titulo="Productos",
            ruta_activa="/productos",
            # Cuántos selects de categoría dibuja el formulario: uno por nivel
            # posible del árbol. Sale del modelo y no de un 5 escrito en la
            # plantilla, que quedaría corto el día que el árbol admita más.
            nivel_maximo=NIVEL_MAXIMO,
        ),
    )


@router.get("/categorias", response_class=HTMLResponse)
async def categorias(
    request: Request, db: Session = Depends(get_db), usuario=Depends(requiere_sesion)
):
    """Árbol de categorías. Cuelga de Productos, no de Configuraciones."""
    return templates.TemplateResponse(
        request,
        "pages/categorias/arbol.html",
        contexto_base(request, db, usuario, titulo="Categorías", ruta_activa="/productos"),
    )


@router.get("/puntos-de-venta", response_class=HTMLResponse)
async def puntos_de_venta(
    request: Request, db: Session = Depends(get_db), usuario=Depends(requiere_sesion)
):
    # ruta_activa apunta a /configuracion: la sección vive dentro del hub,
    # así el sidebar mantiene "Configuraciones" marcado.
    return templates.TemplateResponse(
        request,
        "pages/puntos_de_venta/listado.html",
        contexto_base(
            request, db, usuario, titulo="Puntos de venta", ruta_activa="/configuracion"
        ),
    )


@router.get("/dispositivos", response_class=HTMLResponse)
async def dispositivos(
    request: Request, db: Session = Depends(get_db), usuario=Depends(requiere_sesion)
):
    return templates.TemplateResponse(
        request,
        "pages/dispositivos/listado.html",
        contexto_base(request, db, usuario, titulo="Dispositivos", ruta_activa="/configuracion"),
    )
