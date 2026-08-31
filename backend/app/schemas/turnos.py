"""Schemas de request/response para turnos, retiros y arqueo."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# ── Turno ──────────────────────────────────────────────────────────────────


class TurnoAbrirRequest(BaseModel):
    efectivo_apertura: Decimal = Field(..., ge=0)
    notas: str | None = None


class TurnoUnirseRequest(BaseModel):
    pass  # No requiere body: el usuario se infiere del token


class VendedoraEnTurno(BaseModel):
    id: int
    nombre: str
    ingreso: datetime

    model_config = {"from_attributes": True}


class RetiroResumen(BaseModel):
    id: int
    monto: Decimal
    motivo: str
    autorizado_por_nombre: str
    realizado_por_nombre: str
    timestamp: datetime

    model_config = {"from_attributes": True}


class TurnoResponse(BaseModel):
    id: int
    punto_de_venta_id: int
    punto_de_venta_nombre: str
    estado: str
    efectivo_apertura: Decimal
    fecha_apertura: datetime
    fecha_cierre: datetime | None
    notas: str | None
    usuario_apertura_nombre: str
    usuario_cierre_nombre: str | None
    vendedoras: list[VendedoraEnTurno]

    model_config = {"from_attributes": True}


class TurnoResumen(BaseModel):
    id: int
    punto_de_venta_id: int
    punto_de_venta_nombre: str
    estado: str
    fecha_apertura: datetime
    fecha_cierre: datetime | None
    usuario_apertura_nombre: str

    model_config = {"from_attributes": True}


# ── Retiro de efectivo ─────────────────────────────────────────────────────


class RetiroRequest(BaseModel):
    monto: Decimal = Field(..., gt=0)
    motivo: str = Field(..., min_length=1, max_length=255)
    # ID del usuario Dueño que autoriza el retiro.
    autorizado_por_id: int


class RetiroResponse(BaseModel):
    id: int
    turno_id: int
    monto: Decimal
    motivo: str
    autorizado_por_id: int
    realizado_por_id: int
    timestamp: datetime

    model_config = {"from_attributes": True}


# ── Arqueo ─────────────────────────────────────────────────────────────────


class ArqueoItemEsperado(BaseModel):
    """Un renglón del arqueo calculado por el sistema."""
    medio_de_pago_id: int | None
    medio_nombre: str
    grupo_terminal: str | None
    monto_esperado: Decimal
    es_informativo: bool

    model_config = {"from_attributes": True}


class ArqueoEsperadoResponse(BaseModel):
    turno_id: int
    items: list[ArqueoItemEsperado]
    total_esperado: Decimal


class ArqueoItemDeclarado(BaseModel):
    """Lo que la vendedora declara para un renglón del arqueo."""
    medio_de_pago_id: int | None = None
    grupo_terminal: str | None = None
    monto_declarado: Decimal = Field(..., ge=0)
    es_informativo: bool = False


class ArqueoRegistrarRequest(BaseModel):
    items: list[ArqueoItemDeclarado]
    total_declarado: Decimal = Field(..., ge=0)


class ArqueoItemResponse(BaseModel):
    id: int
    medio_de_pago_id: int | None
    grupo_terminal: str | None
    monto_esperado: Decimal
    monto_declarado: Decimal
    diferencia: Decimal
    es_informativo: bool

    model_config = {"from_attributes": True}


class ArqueoResponse(BaseModel):
    id: int
    turno_id: int
    total_esperado: Decimal
    total_declarado: Decimal
    diferencia: Decimal
    notificacion_enviada: bool
    created_at: datetime
    items: list[ArqueoItemResponse]

    model_config = {"from_attributes": True}


# ── Plataformas gift card ──────────────────────────────────────────────────


class PlataformaGiftCardRequest(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=100)


class PlataformaGiftCardResponse(BaseModel):
    id: int
    nombre: str
    activo: bool

    model_config = {"from_attributes": True}
