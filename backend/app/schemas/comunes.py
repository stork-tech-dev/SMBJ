"""Schemas compartidos por todos los módulos (Principio 2: DRY)."""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class RespuestaPaginada(BaseModel, Generic[T]):
    """
    Envoltorio estándar de los listados.

    `total` es la cantidad de coincidencias del filtro, no la de la página:
    es lo que las pantallas muestran como "N registros encontrados".
    """

    total: int = Field(description="Cantidad total de registros que cumplen el filtro")
    pagina: int
    tamano: int
    resultados: list[T]


class MensajeResponse(BaseModel):
    """Respuesta genérica de operaciones sin cuerpo propio."""

    mensaje: str
