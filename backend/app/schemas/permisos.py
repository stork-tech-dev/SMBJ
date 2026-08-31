"""
Schemas del árbol de permisos, compartidos por roles y usuarios.

`None` en un `puede_*` significa "la acción no aplica a este recurso" y el
frontend lo pinta como "—". Es distinto de `False`, que es "aplica pero no
lo tiene".
"""

from collections.abc import Sequence

from pydantic import BaseModel, Field


class RecursoPermiso(BaseModel):
    """Hoja del árbol: un recurso específico dentro de un módulo."""

    recurso: str
    label: str
    puede_ver: bool | None = None
    puede_crear: bool | None = None
    puede_editar: bool | None = None
    puede_eliminar: bool | None = None


class ModuloPermiso(BaseModel):
    """Nodo del árbol: un módulo con sus recursos."""

    modulo: str
    label: str
    puede_ver: bool | None = None
    puede_crear: bool | None = None
    puede_editar: bool | None = None
    puede_eliminar: bool | None = None
    recursos: Sequence[RecursoPermiso] = []


class RecursoPermisoEfectivo(RecursoPermiso):
    """
    Igual que RecursoPermiso pero distinguiendo herencia de override, que
    es lo que la pantalla necesita para pintar gris vs. azul.
    """

    heredado_ver: bool | None = None
    heredado_crear: bool | None = None
    heredado_editar: bool | None = None
    heredado_eliminar: bool | None = None
    override_ver: bool | None = None
    override_crear: bool | None = None
    override_editar: bool | None = None
    override_eliminar: bool | None = None


class ModuloPermisoEfectivo(ModuloPermiso):
    heredado_ver: bool | None = None
    heredado_crear: bool | None = None
    heredado_editar: bool | None = None
    heredado_eliminar: bool | None = None
    override_ver: bool | None = None
    override_crear: bool | None = None
    override_editar: bool | None = None
    override_eliminar: bool | None = None
    recursos: list[RecursoPermisoEfectivo] = []


class PermisoEntrada(BaseModel):
    """Una fila de permisos a guardar. `recurso=None` = módulo completo."""

    modulo: str
    recurso: str | None = None
    puede_ver: bool = False
    puede_crear: bool = False
    puede_editar: bool = False
    puede_eliminar: bool = False


class ActualizarPermisosRequest(BaseModel):
    permisos: list[PermisoEntrada] = Field(
        description="Filas a guardar. Las no incluidas quedan como estaban."
    )


class AccesoResponse(BaseModel):
    """
    Un casillero de la sección "Accesos permitidos" del formulario de usuario.

    Es la vista plana de los permisos: sin árbol y con una sola acción por
    ítem, que es lo que necesita el alta/edición rápida.
    """

    clave: str = Field(description="Identificador estable: modulo:recurso:accion")
    label: str
    heredado: bool = Field(description="Lo otorga el rol: no se puede desmarcar acá")
    override: bool = Field(description="Otorgado individualmente a este usuario")
    permitido: bool = Field(description="Efectivo: heredado OR override")


class ActualizarAccesosRequest(BaseModel):
    accesos: list[str] = Field(
        description="Claves de los accesos marcados. Las ausentes se quitan."
    )
