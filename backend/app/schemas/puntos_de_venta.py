"""Schemas del módulo de puntos de venta."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PuntoCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    tipo: str = Field(pattern="^(cd|local|online)$")
    # Abreviatura del punto de venta ("MPO"). Obligatoria y de cualquier tipo:
    # el servicio la normaliza a mayúsculas y controla que no se repita.
    codigo: str = Field(min_length=2, max_length=6)


class PuntoEditar(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=150)
    tipo: str | None = Field(default=None, pattern="^(cd|local|online)$")
    codigo: str | None = Field(default=None, min_length=2, max_length=6)


class PuntoEstado(BaseModel):
    activo: bool
    # Confirma la baja aunque tenga dispositivos activos o stock.
    confirmar: bool = False


class PuntoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    nombre: str
    tipo: str
    activo: bool
    created_at: datetime
    updated_at: datetime
