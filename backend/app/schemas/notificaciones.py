"""Schemas de notificaciones para usuarios Dueño."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class NotificacionResponse(BaseModel):
    id: int
    tipo: str
    titulo: str
    cuerpo: str
    leida: bool
    metadata_: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
