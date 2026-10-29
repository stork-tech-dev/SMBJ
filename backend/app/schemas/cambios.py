"""
Schemas del módulo de cambios de producto.

Los cuatro tipos de cambio comparten la misma estructura de request/response
pero tienen reglas de valuación distintas — eso vive en services/cambios.py.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.cambio import EstadoCambio, TipoCambio


# ────────────────────────────────────────────────────────────────────────────
# Requests
# ────────────────────────────────────────────────────────────────────────────


class IniciarCambioRequest(BaseModel):
    tipo: TipoCambio
    # Los tickets que trae el cliente: uno o más códigos de cambio, cuyo
    # valor devuelto se suma. Obligatorio para comun/promocion/gift_card;
    # vacío para falla.
    codigos_cambio: list[str] = Field(default_factory=list)
    # Solo para falla
    autorizador_id: int | None = None
    # Local donde se hace el cambio (puede diferir del local de compra)
    punto_de_venta_id: int


class ItemDevueltoRequest(BaseModel):
    variante_id: int
    # La unidad de qué ticket: el ítem de la venta o el retiro de
    # mercadería. Sin ninguno, el servicio la busca en los tickets del cambio.
    venta_item_id: int | None = None
    retiro_mercaderia_id: int | None = None


class AgregarOrigenRequest(BaseModel):
    """Otro ticket para el mismo cambio."""

    codigo_cambio: str = Field(min_length=1, max_length=8)


class ItemNuevoRequest(BaseModel):
    variante_id: int


class ConfirmarCambioRequest(BaseModel):
    # Solo si diferencia > 0
    medio_pago_diferencia_id: int | None = None
    plan_cuotas_diferencia_id: int | None = None
    notas: str | None = None


class BuscarVentaCambioRequest(BaseModel):
    fecha_desde: str  # ISO date YYYY-MM-DD
    fecha_hasta: str
    sku: str | None = None
    descripcion: str | None = None


# ────────────────────────────────────────────────────────────────────────────
# Responses
# ────────────────────────────────────────────────────────────────────────────


class ItemDevueltoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variante_id: int
    variante_descripcion: str
    variante_sku: str
    precio_reconocido: Decimal
    en_promocion: bool
    tipo_promo: str | None
    material_id: int | None
    material_nombre: str | None
    foto_url: str | None


class ItemNuevoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variante_id: int
    variante_descripcion: str
    variante_sku: str
    precio_actual: Decimal
    material_id: int | None
    material_nombre: str | None
    foto_url: str | None


class OrigenCambioResponse(BaseModel):
    """Un ticket del cambio: una venta o un retiro de mercadería."""

    venta_id: int | None
    retiro_mercaderia_id: int | None
    codigo: str | None


class CambioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo: TipoCambio
    estado: EstadoCambio
    # Los tickets que trajo el cliente (vacío en un cambio por falla).
    origenes: list[OrigenCambioResponse] = []
    punto_de_venta_id: int
    punto_de_venta_nombre: str
    usuario_id: int
    usuario_nombre: str
    autorizador_id: int | None
    autorizador_nombre: str | None
    diferencia: Decimal
    medio_pago_diferencia_id: int | None
    medio_pago_diferencia_nombre: str | None
    plan_cuotas_diferencia_id: int | None
    contador_cambios_previos: int
    codigo_cambio_nuevo: str | None
    notas: str | None
    items_devueltos: list[ItemDevueltoResponse]
    items_nuevos: list[ItemNuevoResponse]
    created_at: datetime
    updated_at: datetime


class DiferenciaResponse(BaseModel):
    """Resultado del cálculo de diferencia antes de confirmar."""
    diferencia: Decimal
    total_devuelto: Decimal
    total_nuevo: Decimal
    a_favor_cliente: bool  # diferencia < 0
    mensaje: str | None  # aviso de plazo vencido o cambios previos


class VentaParaCambioResponse(BaseModel):
    """Resumen de una venta válida para hacer un cambio."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    numero: str
    fecha: datetime
    total: Decimal
    codigo_cambio: str
    dias_desde_venta: int
    plazo_vencido: bool  # más de 30 días
    items: list[dict]


# ── Productos del ticket (primera pantalla del cambio en el celular) ─────────


class TicketItem(BaseModel):
    """Un producto del ticket del código de cambio."""

    # None si el código es de un retiro de mercadería (no hay venta): ahí
    # va `retiro_mercaderia_id`.
    venta_item_id: int | None
    retiro_mercaderia_id: int | None = None
    variante_id: int
    descripcion: str
    codigo: str
    foto_url: str | None
    precio: Decimal
    # False si esa unidad ya se devolvió en otro cambio no cancelado.
    disponible: bool


class TicketCambioResponse(BaseModel):
    origen: str  # "venta" | "retiro"
    items: list[TicketItem]
