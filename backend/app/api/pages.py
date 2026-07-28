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
from app.services import configuracion as servicio_configuracion
from app.services import roles as servicio_roles
from app.services import usuarios as servicio_usuarios
from app.services.auth import debe_cambiar_password

router = APIRouter(include_in_schema=False)

# Estructura del sidebar. Vive acá y no en el template para que agregar
# un módulo sea una línea de Python y no tocar HTML (Principio 2).
# `modulo` es el permiso que se necesita para ver el ítem; None = siempre.
# `modulos` (plural) hace visible el ítem si el usuario puede ver CUALQUIERA
# de esos módulos: lo usa "Configuraciones", que agrupa varias secciones.
MENU_SIDEBAR = [
    {"nombre": "Home", "url": "/", "icono": "home", "modulo": None},
    {"nombre": "Usuarios", "url": "/usuarios", "icono": "users", "modulo": Modulo.USUARIOS},
    {"nombre": "Roles", "url": "/roles", "icono": "shield", "modulo": None, "solo_maestra": True},
    {"nombre": "Proveedores", "url": "/proveedores", "icono": "truck", "modulo": Modulo.PROVEEDORES},
    {"nombre": "Productos", "url": "/productos", "icono": "box", "modulo": Modulo.PRODUCTOS},
    {"nombre": "Ventas", "url": "/ventas", "icono": "cart", "modulo": Modulo.VENTAS},
    {"nombre": "Reportes", "url": "/reportes", "icono": "chart", "modulo": Modulo.REPORTES},
    {"nombre": "Auditoría", "url": "/auditoria", "icono": "list", "modulo": Modulo.AUDITORIA},
    {
        "nombre": "Configuraciones",
        "url": "/configuracion",
        "icono": "settings",
        # Hub de secciones: visible si puede ver alguna de ellas.
        "modulos": [Modulo.CONFIGURACION, Modulo.DISPOSITIVOS],
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


def menu_visible(db: Session, usuario) -> tuple[list, list]:
    """
    Filtra el sidebar según lo que el usuario puede ver. Usa la misma
    `resolver_permiso` que la API: no hay una segunda tabla de verdades.
    """
    es_maestra = usuario.rol is not None and usuario.rol.nombre == ROL_CUENTA_MAESTRA

    def _visible(item) -> bool:
        if item.get("solo_maestra"):
            return es_maestra
        # `modulos` (plural): visible si puede ver cualquiera de ellos.
        if item.get("modulos"):
            return any(
                resolver_permiso(db, usuario.id, m, "ver") for m in item["modulos"]
            )
        if item["modulo"] is None:
            return True
        return resolver_permiso(db, usuario.id, item["modulo"], "ver")

    return (
        [i for i in MENU_SIDEBAR if _visible(i)],
        [i for i in MENU_SIDEBAR_PIE if _visible(i)],
    )


def secciones_configuracion(db: Session, usuario) -> list[dict]:
    """Tarjetas de la página de Configuraciones visibles para el usuario."""
    return [
        s
        for s in CONFIGURACION_SECCIONES
        if resolver_permiso(db, usuario.id, s["modulo"], "ver")
    ]


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

    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"request": request, "letra_empresa": servicio_configuracion.letra_empresa(db)},
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
        contexto_base(request, db, usuario, titulo="Usuarios", ruta_activa="/usuarios"),
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
            ruta_activa="/usuarios",
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
            ruta_activa="/usuarios",
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
        contexto_base(request, db, usuario, titulo="Roles", ruta_activa="/roles"),
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
            ruta_activa="/roles",
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
