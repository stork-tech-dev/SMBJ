"""Schemas del módulo de puntos de venta."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PuntoCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    tipo: str = Field(pattern="^(cd|local|online)$")
    # Solo se usa cuando tipo == 'local'.
    codigo_confirmacion: str | None = Field(default=None, min_length=4, max_length=4)


class PuntoEditar(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=150)
    tipo: str | None = Field(default=None, pattern="^(cd|local|online)$")
    codigo_confirmacion: str | None = Field(default=None, min_length=4, max_length=4)


class PuntoEstado(BaseModel):
    activo: bool
    # Confirma la baja aunque tenga dispositivos activos o stock.
    confirmar: bool = False


class PuntoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    tipo: str
    codigo_confirmacion: str | None
    activo: bool
    created_at: datetime
    updated_at: datetime
