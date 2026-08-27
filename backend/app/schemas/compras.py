"""Schemas de compras a proveedores."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.productos import ProveedorResumen
from app.schemas.stock import PuntoResumen, VarianteEnStock


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class CompraIniciar(BaseModel):
    proveedor_id: int
    punto_de_venta_id: int
    fecha_compra: date | None = None
    notas: str | None = None


class CompraItemAgregar(BaseModel):
    variante_id: int
    cantidad: int = Field(gt=0)
    precio_usd: Decimal = Field(gt=0)
    es_producto_nuevo: bool = False


class CompraItemModificar(BaseModel):
    cantidad: int | None = Field(default=None, gt=0)
    precio_usd: Decimal | None = Field(default=None, gt=0)


class ConfirmacionPrecio(BaseModel):
    confirmar: bool


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class UsuarioResumen(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str


class CompraItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cantidad: int
    precio_usd_anterior: Decimal | None
    precio_usd_nuevo: Decimal
    precio_actualizado: bool
    etiquetas_impresas: int
    es_producto_nuevo: bool
    created_at: datetime
    variante: VarianteEnStock
    # Lo computa el endpoint, no el modelo.
    requiere_confirmacion_precio: bool = False


class CompraResumen(BaseModel):
    """Una fila del listado: sin los ítems."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    estado: str
    fecha_compra: date | None
    fecha_carga: datetime
    fecha_cierre: datetime | None
    proveedor: ProveedorResumen
    punto_de_venta: PuntoResumen
    usuario_carga: UsuarioResumen
    total_items: int = 0


class CompraResponse(CompraResumen):
    """Detalle completo, con ítems."""

    model_config = ConfigDict(from_attributes=True)

    notas: str | None
    created_at: datetime
    updated_at: datetime
    items: list[CompraItemResponse]
