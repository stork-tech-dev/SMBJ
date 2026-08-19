"""Schemas de la auditoría de inventario: contar la mercadería y ajustar."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.stock import PuntoResumen, VarianteEnStock


class AuditoriaIniciar(BaseModel):
    punto_de_venta_id: int
    # Contar una categoría entera es realista en una jornada; el local
    # completo casi nunca. Es informativo: no restringe qué se puede contar.
    filtro_categoria_id: int | None = None
    notas: str | None = None


class ItemContado(BaseModel):
    variante_id: int
    cantidad_contada: int = Field(ge=0)


class ItemsCargar(BaseModel):
    items: list[ItemContado] = Field(min_length=1)


class AuditoriaRechazar(BaseModel):
    """El motivo del rechazo queda con el conteo, no lo reemplaza."""

    notas: str | None = None


class AuditoriaItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cantidad_sistema: int
    cantidad_contada: int
    # La calcula el motor (GENERATED ALWAYS AS): es la resta que decide si se
    # genera un ajuste, y no puede depender de que cada camino la haga igual.
    diferencia: int
    variante: VarianteEnStock


class AuditoriaResumen(BaseModel):
    """Una fila del listado: sin los ítems, que son del detalle."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    estado: str
    fecha_inicio: datetime
    fecha_fin: datetime | None
    fecha_aprobacion: datetime | None
    punto_de_venta: PuntoResumen
    usuario_id: int
    aprobada_por: int | None


class AuditoriaResponse(AuditoriaResumen):
    model_config = ConfigDict(from_attributes=True)

    filtro_categoria_id: int | None
    notas: str | None
    created_at: datetime
    updated_at: datetime
    items: list[AuditoriaItemResponse]
