"""Schemas del módulo de roles."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RolBase(BaseModel):
    nombre: str = Field(min_length=1, max_length=50)
    descripcion: str | None = Field(default=None, max_length=255)


class RolCrear(RolBase):
    pass


class RolEditar(BaseModel):
    """
    Todo opcional: se actualiza solo lo que llega. En roles del sistema,
    mandar un `nombre` distinto al actual devuelve 409.
    """

    nombre: str | None = Field(default=None, min_length=1, max_length=50)
    descripcion: str | None = Field(default=None, max_length=255)


class RolEstado(BaseModel):
    activo: bool


class RolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    descripcion: str | None
    es_sistema: bool
    activo: bool
    created_at: datetime
    updated_at: datetime


class RolListadoResponse(RolResponse):
    """Fila del listado: agrega la cantidad de usuarios (calculada)."""

    cantidad_usuarios: int
