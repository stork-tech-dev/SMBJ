"""Schemas del router de healthcheck."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Respuesta de GET /api/v1/health."""

    status: str = Field(examples=["ok"])


class HealthDBResponse(BaseModel):
    """Respuesta de GET /api/v1/health/db."""

    status: str = Field(examples=["ok"])
    database: str = Field(examples=["ok"])
    detalle: str | None = None
