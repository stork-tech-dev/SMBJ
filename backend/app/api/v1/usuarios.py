"""
Endpoints de usuarios.

El acceso al módulo lo decide `requiere_permiso(Modulo.USUARIOS, ...)`.
Sobre qué usuarios concretos puede operar cada rol lo decide el service.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permisos import Modulo, requiere_permiso
from app.core.utils import ip_de_request
from app.schemas.comunes import RespuestaPaginada
from app.schemas.permisos import (
    AccesoResponse,
    ActualizarAccesosRequest,
    ActualizarPermisosRequest,
    ModuloPermisoEfectivo,
)
from app.schemas.roles import RolResponse
from app.schemas.usuarios import (
    ClaveEspecialResetear,
    ClaveEspecialResultado,
    ClaveEspecialValidar,
    HistorialAccesoResponse,
    LocalResumen,
    UsuarioCrear,
    UsuarioEditar,
    UsuarioEstado,
    UsuarioResponse,
)
from app.services import permisos as servicio_permisos
from app.services import roles as servicio_roles
from app.services import usuarios as servicio_usuarios

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


def _404(exc: Exception):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _403(exc: Exception):
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


def _409(exc: Exception):
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("", response_model=RespuestaPaginada[UsuarioResponse], summary="Listado de usuarios")
def listar(
    nombre: str | None = Query(default=None),
    username: str | None = Query(default=None),
    email: str | None = Query(default=None),
    rol_id: int | None = Query(default=None),
    local_asignado_id: int | None = Query(default=None),
    activo: bool | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.USUARIOS, "ver")),
):
    """Filtros del Principio 5, todos resueltos en el backend."""
    resultados, total = servicio_usuarios.listar_usuarios(
        db,
        nombre=nombre,
        username=username,
        email=email,
        rol_id=rol_id,
        local_asignado_id=local_asignado_id,
        activo=activo,
        pagina=pagina,
        tamano=tamano,
    )
    return RespuestaPaginada[UsuarioResponse](
        total=total, pagina=pagina, tamano=tamano, resultados=resultados
    )


@router.get("/roles-asignables", response_model=list[RolResponse], summary="Roles que puede asignar")
def roles_asignables(
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.USUARIOS, "ver")),
):
    """Alimenta el selector de rol del formulario de alta/edición."""
    return servicio_usuarios.roles_asignables(db, autor)


@router.get(
    "/locales-asignables",
    response_model=list[LocalResumen],
    summary="Locales que se pueden asignar",
)
def locales_asignables(
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.USUARIOS, "ver")),
):
    """
    Alimenta el selector "Local Asignado" del formulario.

    Existe acá, y no se reusa GET /puntos-de-venta, porque ese endpoint
    exige permiso de CONFIGURACION: quien gestiona usuarios no tiene por
    qué tenerlo, y se quedaría sin opciones en el desplegable.
    """
    return servicio_usuarios.locales_asignables(db)


@router.get(
    "/accesos",
    response_model=list[AccesoResponse],
    summary="Accesos que otorga un rol",
)
def accesos_de_rol(
    rol_id: int = Query(description="Rol del que se quieren ver los accesos"),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.USUARIOS, "ver")),
):
    """
    Alimenta la sección "Accesos permitidos" en el ALTA, cuando el usuario
    todavía no existe: muestra lo que va a heredar del rol elegido.
    """
    try:
        servicio_roles.obtener_rol(db, rol_id)
    except servicio_roles.NoEncontrado as exc:
        raise _404(exc) from exc

    return servicio_permisos.accesos_de_rol(db, rol_id)


@router.get(
    "/{usuario_id}/accesos",
    response_model=list[AccesoResponse],
    summary="Accesos efectivos de un usuario",
)
def accesos_de_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.USUARIOS, "ver")),
):
    """Lo mismo que el anterior, pero para un usuario ya existente."""
    try:
        usuario = servicio_usuarios.obtener_usuario(db, usuario_id)
    except servicio_roles.NoEncontrado as exc:
        raise _404(exc) from exc

    return servicio_permisos.accesos_de_usuario(db, usuario)


@router.put(
    "/{usuario_id}/accesos",
    response_model=list[AccesoResponse],
    summary="Guardar accesos individuales",
)
def actualizar_accesos(
    usuario_id: int,
    datos: ActualizarAccesosRequest,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.USUARIOS, "editar")),
):
    """
    Guarda los accesos marcados como overrides individuales.

    Solo toca la acción de cada acceso del catálogo: los permisos que el
    usuario tenga cargados desde la pantalla completa quedan intactos.
    """
    try:
        usuario = servicio_usuarios.obtener_usuario(db, usuario_id)
        servicio_usuarios.validar_puede_gestionar(autor, usuario.rol)
        accesos = servicio_permisos.actualizar_accesos_usuario(
            db, usuario, datos.accesos, autor.id, ip_de_request(request)
        )
    except servicio_usuarios.SinPermiso as exc:
        raise _403(exc) from exc
    except servicio_roles.NoEncontrado as exc:
        raise _404(exc) from exc

    db.commit()
    return accesos


@router.get("/{usuario_id}", response_model=UsuarioResponse, summary="Detalle de usuario")
def detalle(
    usuario_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.USUARIOS, "ver")),
):
    try:
        return servicio_usuarios.obtener_usuario(db, usuario_id)
    except servicio_roles.NoEncontrado as exc:
        raise _404(exc) from exc


@router.post("", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED, summary="Alta de usuario")
def crear(
    datos: UsuarioCrear,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.USUARIOS, "crear")),
):
    try:
        usuario = servicio_usuarios.crear_usuario(
            db,
            autor,
            username=datos.username,
            nombre=datos.nombre,
            password=datos.password,
            rol_id=datos.rol_id,
            email=datos.email,
            fecha_nacimiento=datos.fecha_nacimiento,
            celular=datos.celular,
            local_asignado_id=datos.local_asignado_id,
            ip_origen=ip_de_request(request),
        )
    except servicio_usuarios.SinPermiso as exc:
        raise _403(exc) from exc
    except servicio_roles.NoEncontrado as exc:
        raise _404(exc) from exc
    except servicio_roles.ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return usuario


@router.put("/{usuario_id}", response_model=UsuarioResponse, summary="Editar usuario")
def editar(
    usuario_id: int,
    datos: UsuarioEditar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.USUARIOS, "editar")),
):
    try:
        usuario = servicio_usuarios.editar_usuario(
            db,
            autor,
            usuario_id,
            nombre=datos.nombre,
            email=datos.email,
            rol_id=datos.rol_id,
            password=datos.password,
            fecha_nacimiento=datos.fecha_nacimiento,
            celular=datos.celular,
            local_asignado_id=datos.local_asignado_id,
            # Distinguen "no lo mandaron" de "lo mandaron vacío": los tres
            # campos son opcionales y se tienen que poder borrar.
            editar_fecha_nacimiento="fecha_nacimiento" in datos.model_fields_set,
            editar_celular="celular" in datos.model_fields_set,
            editar_local="local_asignado_id" in datos.model_fields_set,
            ip_origen=ip_de_request(request),
        )
    except servicio_usuarios.SinPermiso as exc:
        raise _403(exc) from exc
    except servicio_roles.NoEncontrado as exc:
        raise _404(exc) from exc
    except servicio_roles.ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return usuario


@router.patch("/{usuario_id}/estado", response_model=UsuarioResponse, summary="Activar o desactivar")
def cambiar_estado(
    usuario_id: int,
    datos: UsuarioEstado,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.USUARIOS, "editar")),
):
    try:
        usuario = servicio_usuarios.cambiar_estado_usuario(
            db, autor, usuario_id, datos.activo, ip_de_request(request)
        )
    except servicio_usuarios.SinPermiso as exc:
        raise _403(exc) from exc
    except servicio_roles.NoEncontrado as exc:
        raise _404(exc) from exc
    except servicio_roles.ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return usuario


@router.get(
    "/{usuario_id}/permisos",
    response_model=list[ModuloPermisoEfectivo],
    summary="Árbol de permisos efectivos",
)
def obtener_permisos(
    usuario_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.USUARIOS, "ver")),
):
    """
    Devuelve el permiso efectivo (rol OR override) y, por separado, qué
    parte viene heredada del rol y qué parte es override individual.
    """
    try:
        usuario = servicio_usuarios.obtener_usuario(db, usuario_id)
    except servicio_roles.NoEncontrado as exc:
        raise _404(exc) from exc

    return servicio_permisos.arbol_de_usuario(db, usuario)


@router.put(
    "/{usuario_id}/permisos",
    response_model=list[ModuloPermisoEfectivo],
    summary="Actualizar overrides de permisos",
)
def actualizar_permisos(
    usuario_id: int,
    datos: ActualizarPermisosRequest,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.USUARIOS, "editar")),
):
    try:
        usuario = servicio_usuarios.obtener_usuario(db, usuario_id)
        servicio_usuarios.validar_puede_gestionar(autor, usuario.rol)
        arbol = servicio_permisos.actualizar_permisos_usuario(
            db,
            usuario,
            [p.model_dump() for p in datos.permisos],
            autor.id,
            ip_de_request(request),
        )
    except servicio_usuarios.SinPermiso as exc:
        raise _403(exc) from exc
    except servicio_roles.NoEncontrado as exc:
        raise _404(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    db.commit()
    return arbol


@router.get(
    "/{usuario_id}/historial",
    response_model=RespuestaPaginada[HistorialAccesoResponse],
    summary="Historial de accesos",
)
def historial(
    usuario_id: int,
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    resultado: str | None = Query(default=None, pattern="^(exitoso|fallido)$"),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.USUARIOS, "ver")),
):
    try:
        filas, total = servicio_usuarios.historial_de_usuario(
            db, usuario_id, desde=desde, hasta=hasta, resultado=resultado,
            pagina=pagina, tamano=tamano,
        )
    except servicio_roles.NoEncontrado as exc:
        raise _404(exc) from exc

    return RespuestaPaginada[HistorialAccesoResponse](
        total=total, pagina=pagina, tamano=tamano, resultados=filas
    )


# ----------------------------------------------------------------------------
# Clave especial — solo la Cuenta Maestra tiene una.
# Para cualquier otro usuario estos endpoints devuelven 404.
# ----------------------------------------------------------------------------


@router.post(
    "/{usuario_id}/clave-especial/validar",
    response_model=ClaveEspecialResultado,
    summary="Validar clave especial",
)
def validar_clave_especial(
    usuario_id: int,
    datos: ClaveEspecialValidar,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.USUARIOS, "ver")),
):
    try:
        valida = servicio_usuarios.validar_clave_especial(db, usuario_id, datos.clave)
    except servicio_roles.NoEncontrado as exc:
        raise _404(exc) from exc

    return ClaveEspecialResultado(valida=valida)


@router.patch(
    "/{usuario_id}/clave-especial/resetear",
    response_model=ClaveEspecialResultado,
    summary="Resetear clave especial",
)
def resetear_clave_especial(
    usuario_id: int,
    datos: ClaveEspecialResetear,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.USUARIOS, "editar")),
):
    try:
        servicio_usuarios.resetear_clave_especial(
            db, autor, usuario_id, datos.clave_nueva, ip_de_request(request)
        )
    except servicio_roles.NoEncontrado as exc:
        raise _404(exc) from exc

    db.commit()
    return ClaveEspecialResultado(valida=True)
