"""Schemas de promociones y su alcance."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.promocion import TipoAlcance, TipoPromocion


class AlcanceItem(BaseModel):
    """
    Un producto o una categoría alcanzada.

    Una categoría alcanza también a sus descendientes: quien pone "Plata"
    espera que entren "Plata > Anillos" y "Plata > Cadenas".
    """

    tipo_alcance: TipoAlcance
    referencia_id: int


class AlcanceResponse(AlcanceItem):
    model_config = ConfigDict(from_attributes=True)

    id: int
    # El nombre del producto o de la categoría, para que la pantalla no
    # tenga que resolver un id contra dos endpoints distintos.
    nombre: str | None = None


class PromocionCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    tipo: TipoPromocion
    alcances: list[AlcanceItem] = Field(
        min_length=1,
        description="Al menos uno: una promoción sin alcance no aplica a nada",
    )
    fecha_inicio: date | None = None
    fecha_fin: date | None = None


class PromocionEditar(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    tipo: TipoPromocion | None = None
    alcances: list[AlcanceItem] | None = Field(default=None, min_length=1)
    fecha_inicio: date | None = None
    fecha_fin: date | None = None


class PromocionEstado(BaseModel):
    activo: bool


class PromocionResumen(BaseModel):
    """Lo mínimo para nombrarla: lo que viaja dentro de una venta."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    tipo: TipoPromocion
    activo: bool


class PromocionResponse(PromocionResumen):
    fecha_inicio: date | None
    fecha_fin: date | None
    created_at: datetime
    updated_at: datetime
    alcances: list[AlcanceResponse] = []

    # Derivados que el frontend no debería recalcular (Principio 1): si
    # rige HOY, y cuántas unidades entran y se pagan por grupo.
    vigente: bool = False
    tamano_grupo: int = 0
    pagas_por_grupo: int = 0
    # Si está asignada a clientes puntuales: con al menos uno deja de
    # ofrecerse en las ventas del resto.
    exclusiva_de_clientes: bool = False


class ClientePromocionCrear(BaseModel):
    promocion_id: int
