"""Schemas del módulo de dispositivos."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DispositivoResponse(BaseModel):
    """
    Ficha del dispositivo. Incluye `uuid` como solo lectura; el
    `fingerprint` NO se expone (dato interno de recuperación).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: UUID
    punto_de_venta_id: int | None
    descripcion: str
    activo: bool
    fecha_alta: datetime
    ultimo_acceso: datetime | None
    ultima_ip: str | None
    observaciones: str | None
    # Datos del equipo leídos del User-Agent. Crudos: el frontend
    # decide cómo mostrarlos (Principio 1).
    user_agent: str | None
    sistema_operativo: str | None
    navegador: str | None
    modelo: str | None
    created_at: datetime
    updated_at: datetime


class DispositivoMeResponse(BaseModel):
    """Respuesta del endpoint público de identificación."""

    uuid: UUID
    activo: bool
    punto_de_venta_id: int | None
    descripcion: str


class DispositivoEditar(BaseModel):
    """
    Campos editables por un admin. `uuid` y `fingerprint` no están: son de
    solo lectura. `punto_de_venta_id` usa el sentinel de "no enviado" vs
    "poner en NULL" a través de `model_fields_set`.
    """

    descripcion: str | None = Field(default=None, max_length=150)
    punto_de_venta_id: int | None = None
    observaciones: str | None = None
    activo: bool | None = None
