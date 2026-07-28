"""
Sistema de permisos — fuente de verdad de todo el control de acceso.

Este archivo define:
  - Los Enums `Modulo` y `Recurso`: los únicos strings válidos de módulos
    y recursos en todo el sistema. Nunca escribir esos literales fuera de acá.
  - `resolver_permiso()`: la ÚNICA función que decide si un usuario puede
    hacer algo. Ningún endpoint valida acceso por su cuenta.
  - `requiere_permiso()`: la dependency de FastAPI que envuelve a la anterior.
"""

from enum import Enum

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db

# ============================================================================
# CONSTANTES DE DOMINIO
# ============================================================================


class Modulo(str, Enum):
    CLIENTES = "clientes"
    PROVEEDORES = "proveedores"
    PRODUCTOS = "productos"
    COMPRAS = "compras"
    VENTAS = "ventas"
    FACTURACION = "facturacion"
    TESORERIA = "tesoreria"
    REPORTES = "reportes"
    CONFIGURACION = "configuracion"
    AUDITORIA = "auditoria"
    USUARIOS = "usuarios"
    DISPOSITIVOS = "dispositivos"


class Recurso(str, Enum):
    # Reportes específicos (acceso granular dentro del módulo REPORTES)
    REPORTE_VENTAS_DIARIAS = "reporte.ventas_diarias"
    REPORTE_VENTAS_POR_PERIODO = "reporte.ventas_por_periodo"
    REPORTE_STOCK = "reporte.stock"
    REPORTE_STOCK_PVENTA = "reporte.stock_pventa"
    REPORTE_RANKING_CLIENTES = "reporte.ranking_clientes"
    REPORTE_RANKING_PRODUCTOS = "reporte.ranking_productos"
    REPORTE_DEUDA_CLIENTES = "reporte.deuda_clientes"
    REPORTE_DEUDA_PROVEEDORES = "reporte.deuda_proveedores"

    # Operaciones específicas de otros módulos
    PRECIO_CAMBIO_MASIVO = "precio.cambio_masivo"
    DOLAR_CAMBIO_MASIVO = "dolar.cambio_masivo"
    CAJA_ARQUEO = "caja.arqueo"
    CAJA_RETIRO = "caja.retiro"
    VENTA_DESCUENTO = "venta.descuento"
    VENTA_ANULAR = "venta.anular"
    STOCK_BAJA = "stock.baja"
    STOCK_AUDITORIA = "stock.auditoria"

    # recurso=NULL (ausencia de Recurso) = acceso general al módulo completo


# Acciones posibles sobre un módulo o recurso.
ACCIONES = ("ver", "crear", "editar", "eliminar")

# Nombres de los roles del sistema. Se referencian SIEMPRE por nombre,
# nunca por id (el id depende del orden de carga del seed).
ROL_CUENTA_MAESTRA = "cuenta_maestra"
ROL_DUENO = "dueno"
ROL_SUPERVISOR = "supervisor"
ROL_VENDEDOR = "vendedor"
ROL_DISTRIBUCION = "distribucion"
ROL_AUDITOR = "auditor"

ROLES_SISTEMA = (
    ROL_CUENTA_MAESTRA,
    ROL_DUENO,
    ROL_SUPERVISOR,
    ROL_VENDEDOR,
    ROL_DISTRIBUCION,
    ROL_AUDITOR,
)

# Etiquetas legibles para la UI. Viven acá y no en los templates para que
# el árbol de permisos y la API digan exactamente lo mismo (Principio 2).
LABEL_MODULO: dict[Modulo, str] = {
    Modulo.CLIENTES: "Clientes",
    Modulo.PROVEEDORES: "Proveedores",
    Modulo.PRODUCTOS: "Productos",
    Modulo.COMPRAS: "Compras",
    Modulo.VENTAS: "Ventas",
    Modulo.FACTURACION: "Facturación",
    Modulo.TESORERIA: "Tesorería",
    Modulo.REPORTES: "Reportes",
    Modulo.CONFIGURACION: "Configuración",
    Modulo.AUDITORIA: "Auditoría",
    Modulo.USUARIOS: "Usuarios",
    Modulo.DISPOSITIVOS: "Dispositivos",
}

LABEL_RECURSO: dict[Recurso, str] = {
    Recurso.REPORTE_VENTAS_DIARIAS: "Ventas diarias",
    Recurso.REPORTE_VENTAS_POR_PERIODO: "Ventas por período",
    Recurso.REPORTE_STOCK: "Stock",
    Recurso.REPORTE_STOCK_PVENTA: "Stock por punto de venta",
    Recurso.REPORTE_RANKING_CLIENTES: "Ranking de clientes",
    Recurso.REPORTE_RANKING_PRODUCTOS: "Ranking de productos",
    Recurso.REPORTE_DEUDA_CLIENTES: "Deuda de clientes",
    Recurso.REPORTE_DEUDA_PROVEEDORES: "Deuda de proveedores",
    Recurso.PRECIO_CAMBIO_MASIVO: "Cambio masivo de precios",
    Recurso.DOLAR_CAMBIO_MASIVO: "Cambio masivo del dólar",
    Recurso.CAJA_ARQUEO: "Arqueo de caja",
    Recurso.CAJA_RETIRO: "Retiro de efectivo",
    Recurso.VENTA_DESCUENTO: "Aplicar descuento",
    Recurso.VENTA_ANULAR: "Anular venta",
    Recurso.STOCK_BAJA: "Baja de stock",
    Recurso.STOCK_AUDITORIA: "Auditoría de inventario",
}

# A qué módulo pertenece cada recurso. Define la jerarquía del árbol de
# permisos: un recurso solo aparece dentro de su módulo.
MODULO_DE_RECURSO: dict[Recurso, Modulo] = {
    Recurso.REPORTE_VENTAS_DIARIAS: Modulo.REPORTES,
    Recurso.REPORTE_VENTAS_POR_PERIODO: Modulo.REPORTES,
    Recurso.REPORTE_STOCK: Modulo.REPORTES,
    Recurso.REPORTE_STOCK_PVENTA: Modulo.REPORTES,
    Recurso.REPORTE_RANKING_CLIENTES: Modulo.REPORTES,
    Recurso.REPORTE_RANKING_PRODUCTOS: Modulo.REPORTES,
    Recurso.REPORTE_DEUDA_CLIENTES: Modulo.REPORTES,
    Recurso.REPORTE_DEUDA_PROVEEDORES: Modulo.REPORTES,
    Recurso.PRECIO_CAMBIO_MASIVO: Modulo.PRODUCTOS,
    Recurso.DOLAR_CAMBIO_MASIVO: Modulo.PROVEEDORES,
    Recurso.CAJA_ARQUEO: Modulo.TESORERIA,
    Recurso.CAJA_RETIRO: Modulo.TESORERIA,
    Recurso.VENTA_DESCUENTO: Modulo.VENTAS,
    Recurso.VENTA_ANULAR: Modulo.VENTAS,
    Recurso.STOCK_BAJA: Modulo.PRODUCTOS,
    Recurso.STOCK_AUDITORIA: Modulo.PRODUCTOS,
}

# Qué acciones tienen sentido en cada recurso. Las que no están listadas
# se muestran como "—" en el árbol y se guardan siempre en FALSE.
#
# Los reportes solo se consultan: únicamente 'ver'. Las operaciones se
# mapean a la acción que mejor las describe, para no inventar una quinta
# acción fuera del modelo de datos.
ACCIONES_DE_RECURSO: dict[Recurso, tuple[str, ...]] = {
    Recurso.REPORTE_VENTAS_DIARIAS: ("ver",),
    Recurso.REPORTE_VENTAS_POR_PERIODO: ("ver",),
    Recurso.REPORTE_STOCK: ("ver",),
    Recurso.REPORTE_STOCK_PVENTA: ("ver",),
    Recurso.REPORTE_RANKING_CLIENTES: ("ver",),
    Recurso.REPORTE_RANKING_PRODUCTOS: ("ver",),
    Recurso.REPORTE_DEUDA_CLIENTES: ("ver",),
    Recurso.REPORTE_DEUDA_PROVEEDORES: ("ver",),
    Recurso.PRECIO_CAMBIO_MASIVO: ("editar",),
    Recurso.DOLAR_CAMBIO_MASIVO: ("editar",),
    Recurso.CAJA_ARQUEO: ("crear",),
    Recurso.CAJA_RETIRO: ("crear",),
    Recurso.VENTA_DESCUENTO: ("crear",),
    Recurso.VENTA_ANULAR: ("eliminar",),
    Recurso.STOCK_BAJA: ("crear",),
    Recurso.STOCK_AUDITORIA: ("crear",),
}


def recursos_de_modulo(modulo: Modulo) -> list[Recurso]:
    """Recursos específicos que cuelgan de un módulo, en orden de Enum."""
    return [r for r in Recurso if MODULO_DE_RECURSO[r] == modulo]


# ============================================================================
# ACCESOS INDIVIDUALES
# ============================================================================
#
# La sección "Accesos permitidos" del formulario de usuario es una vista
# simplificada de los permisos: una lista plana de casilleros, sin el árbol
# de módulos. Cada casillero es una terna (módulo, recurso, acción).
#
# Se arma desde los mismos Enums, así que agregar un Recurso lo suma a la
# pantalla sin tocar nada más (Principio 2: DRY).

# Permisos de módulo completo que tienen sentido como acceso suelto.
ACCESOS_DE_MODULO: tuple[tuple[Modulo, str, str], ...] = (
    (Modulo.CONFIGURACION, "ver", "Acceso a tablas y configuración"),
    (Modulo.USUARIOS, "crear", "Crear usuarios"),
    (Modulo.AUDITORIA, "ver", "Consultar la auditoría"),
)

# Verbo con el que se lee cada acción en la lista de accesos.
_VERBO = {"ver": "Consultar", "crear": "Registrar", "editar": "Modificar", "eliminar": "Anular"}


def _clave(modulo: Modulo, recurso: Recurso | None, accion: str) -> str:
    """Identificador estable de un acceso, el que viaja por la API."""
    return f"{modulo.value}:{recurso.value if recurso else ''}:{accion}"


def catalogo_accesos() -> list[dict]:
    """
    Lista completa de accesos individuales, en el orden en que se muestran.

    Cada entrada: clave, label, modulo, recurso y accion. Los recursos
    aportan una sola acción cada uno (la de `ACCIONES_DE_RECURSO`), que es
    justo lo que hace que se puedan mostrar como un casillero simple.
    """
    accesos: list[dict] = []

    for modulo, accion, label in ACCESOS_DE_MODULO:
        accesos.append(
            {
                "clave": _clave(modulo, None, accion),
                "label": label,
                "modulo": modulo,
                "recurso": None,
                "accion": accion,
            }
        )

    for recurso in Recurso:
        modulo = MODULO_DE_RECURSO[recurso]
        for accion in ACCIONES_DE_RECURSO[recurso]:
            etiqueta = LABEL_RECURSO[recurso]
            # Los reportes ya se leen bien solos ("Ventas diarias"); al
            # resto se le antepone el verbo para que se entienda la acción.
            if not recurso.value.startswith("reporte."):
                etiqueta = f"{_VERBO[accion]}: {etiqueta.lower()}"
            accesos.append(
                {
                    "clave": _clave(modulo, recurso, accion),
                    "label": etiqueta,
                    "modulo": modulo,
                    "recurso": recurso,
                    "accion": accion,
                }
            )

    return accesos


def acceso_por_clave(clave: str) -> dict | None:
    """Busca un acceso del catálogo. Devuelve None si la clave no existe."""
    return next((a for a in catalogo_accesos() if a["clave"] == clave), None)


# ============================================================================
# RESOLUCIÓN DE PERMISOS
# ============================================================================


def resolver_permiso(
    db: Session,
    usuario_id: int,
    modulo: Modulo,
    accion: str,
    recurso: Recurso | None = None,
) -> bool:
    """
    Decide si un usuario puede ejecutar una acción. ÚNICA barrera de acceso
    del sistema: ningún otro punto del código valida permisos.

    Resolución:
      1. Override individual en usuario_permisos (modulo + recurso exacto)
      2. Override individual en usuario_permisos (modulo + recurso=NULL)
      3. Permiso base en rol_permisos (modulo + recurso exacto)
      4. Permiso base en rol_permisos (modulo + recurso=NULL)

    El resultado es el OR de todo lo anterior: los overrides solo agregan
    permisos, nunca los quitan.

    Cuando se pide un recurso específico, el permiso general del módulo
    también habilita (quien puede ver todos los reportes puede ver uno).
    A la inversa no: tener un recurso puntual NO da acceso general.
    """
    if accion not in ACCIONES:
        raise ValueError(f"Acción inválida: {accion!r}. Válidas: {ACCIONES}")

    # Import local: evita un ciclo de imports entre models y core.
    from app.models.usuario import Usuario
    from app.models.permiso import RolPermiso, UsuarioPermiso

    usuario = db.get(Usuario, usuario_id)
    if usuario is None or not usuario.activo:
        return False

    # La Cuenta Maestra tiene acceso total por definición. Se resuelve acá
    # dentro para que siga siendo esta función la única que decide.
    if usuario.rol and usuario.rol.nombre == ROL_CUENTA_MAESTRA:
        return True

    # Un rol desactivado no habilita nada.
    if usuario.rol is None or not usuario.rol.activo:
        return False

    columna = f"puede_{accion}"
    valor_recurso = recurso.value if recurso is not None else None

    # Filtro de filas relevantes: la del módulo completo (recurso IS NULL)
    # y, si se pidió un recurso, también la de ese recurso puntual.
    def _condicion_recurso(modelo):
        if valor_recurso is None:
            return modelo.recurso.is_(None)
        return or_(modelo.recurso.is_(None), modelo.recurso == valor_recurso)

    # Overrides del usuario (pasos 1 y 2).
    override = db.execute(
        select(getattr(UsuarioPermiso, columna)).where(
            UsuarioPermiso.usuario_id == usuario_id,
            UsuarioPermiso.modulo == modulo.value,
            _condicion_recurso(UsuarioPermiso),
            getattr(UsuarioPermiso, columna).is_(True),
        )
    ).first()
    if override is not None:
        return True

    # Permisos del rol (pasos 3 y 4).
    base = db.execute(
        select(getattr(RolPermiso, columna)).where(
            RolPermiso.rol_id == usuario.rol_id,
            RolPermiso.modulo == modulo.value,
            _condicion_recurso(RolPermiso),
            getattr(RolPermiso, columna).is_(True),
        )
    ).first()

    return base is not None


# ============================================================================
# DEPENDENCIES DE FASTAPI
# ============================================================================


def get_current_user(request: Request, db: Session = Depends(get_db)):
    """
    Usuario autenticado a partir del JWT.

    El token se busca primero en el header Authorization (clientes de API,
    Swagger, curl) y, si no está, en la cookie HttpOnly, que es la que
    manda HTMX sola en cada request.

    El header tiene prioridad a propósito: si alguien lo envía de forma
    explícita, esa es la credencial que quiere usar, aunque el navegador
    arrastre una cookie de otra sesión.

    Lanza 401 si no hay token válido o el usuario está inactivo.
    """
    from app.models.usuario import Usuario
    from app.services.auth import TokenInvalido, verificar_token
    from config import settings

    token = None
    autorizacion = request.headers.get("authorization", "")
    if autorizacion.lower().startswith("bearer "):
        token = autorizacion[7:]

    if not token:
        token = request.cookies.get(settings.JWT_COOKIE_NAME)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = verificar_token(token, tipo="access")
    except TokenInvalido as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    usuario = db.get(Usuario, int(payload["sub"]))
    if usuario is None or not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario inactivo o inexistente"
        )

    return usuario


def requiere_permiso(modulo: Modulo, accion: str, recurso: Recurso | None = None):
    """
    Dependency que valida el JWT y consulta `resolver_permiso`. Devuelve 403
    si el usuario no tiene acceso.

    Uso:
        @router.get("/reportes/ventas")
        async def reporte(
            _=Depends(requiere_permiso(Modulo.REPORTES, "ver",
                                       Recurso.REPORTE_VENTAS_DIARIAS))
        ): ...
    """

    def dependencia(
        usuario=Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        if not resolver_permiso(db, usuario.id, modulo, accion, recurso):
            destino = recurso.value if recurso else modulo.value
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Sin permiso para '{accion}' en '{destino}'",
            )
        return usuario

    return dependencia


def requiere_cuenta_maestra(usuario=Depends(get_current_user)):
    """
    Dependency para operaciones exclusivas de la Cuenta Maestra
    (gestión de roles, reseteo de clave especial).
    """
    if usuario.rol is None or usuario.rol.nombre != ROL_CUENTA_MAESTRA:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operación exclusiva de la Cuenta Maestra",
        )
    return usuario
