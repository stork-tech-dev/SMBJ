"""Schemas del árbol de categorías."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CategoriaCrear(BaseModel):
    """
    `nivel` no está a propósito: lo deriva el backend del padre. Si el
    cliente pudiera mandarlo, podría crear un nivel 3 colgando de un
    nivel 1 y el árbol quedaría mintiendo sobre su propia forma.
    """

    nombre: str = Field(min_length=1, max_length=150)
    parent_id: int | None = None
    orden: int = Field(default=0, ge=0)


class CategoriaEditar(BaseModel):
    """Nombre y orden. Cambiar de padre tiene su propio endpoint."""

    nombre: str | None = Field(default=None, min_length=1, max_length=150)
    orden: int | None = Field(default=None, ge=0)


class CategoriaMover(BaseModel):
    """`None` mueve la categoría al primer nivel."""

    parent_id: int | None = None


class CategoriaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    nivel: int
    parent_id: int | None
    orden: int
    created_at: datetime
    updated_at: datetime


class CategoriaNodo(BaseModel):
    """
    Nodo del árbol, con sus hijos anidados.

    Se declara recursivo para que OpenAPI documente la forma real de la
    respuesta en lugar de un `dict` opaco.
    """

    id: int
    nombre: str
    nivel: int
    parent_id: int | None
    orden: int
    hijos: list["CategoriaNodo"] = []
