"""Schemas de consulta de auditoría (solo lectura)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditoriaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    usuario_id: int | None
    accion: str
    entidad: str
    entidad_id: int | None
    estado_anterior: dict | None
    estado_nuevo: dict | None
    ip_origen: str | None
    timestamp: datetime
