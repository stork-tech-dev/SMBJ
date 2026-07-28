"""Schemas del módulo de proveedores."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProveedorCrear(BaseModel):
    razon_social: str = Field(min_length=1, max_length=200)
    dolar_actual: Decimal = Field(gt=0, description="Valor del dólar, mayor a cero")
    direccion: str | None = Field(default=None, max_length=255)
    telefono: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    notas: str | None = None


class ProveedorEditar(BaseModel):
    """Todo opcional. El dólar NO se toca acá: tiene su propio endpoint."""

    razon_social: str | None = Field(default=None, min_length=1, max_length=200)
    direccion: str | None = Field(default=None, max_length=255)
    telefono: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    notas: str | None = None


class ProveedorEstado(BaseModel):
    estado: str = Field(pattern="^(activo|desactivado|inhabilitado)$")
    # Confirma la baja aunque el proveedor tenga productos activos.
    confirmar_con_productos: bool = False


class ProveedorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    razon_social: str
    direccion: str | None
    telefono: str | None
    email: str | None
    notas: str | None
    estado: str
    dolar_actual: Decimal
    created_at: datetime
    updated_at: datetime


class CambioDolarRequest(BaseModel):
    valor_nuevo: Decimal = Field(gt=0, description="Nuevo valor del dólar, mayor a cero")


class DolarHistorialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    proveedor_id: int
    valor_anterior: Decimal
    valor_nuevo: Decimal
    usuario_id: int
    origen: str
    timestamp: datetime


class CambioMasivoRequest(BaseModel):
    # None = todos los proveedores activos.
    proveedor_ids: list[int] | None = None
    modalidad: str = Field(pattern="^(valor|porcentaje)$")
    valor: Decimal = Field(description="Valor absoluto o porcentaje según la modalidad")


class CambioMasivoPreviewItem(BaseModel):
    proveedor_id: int
    razon_social: str
    valor_actual: Decimal
    valor_nuevo: Decimal


class CambioMasivoResultItem(BaseModel):
    proveedor_id: int
    razon_social: str
    valor_nuevo: Decimal


class ImportarErrorItem(BaseModel):
    fila: int
    error: str


class ImportarResultado(BaseModel):
    aplicados: int
    errores: list[ImportarErrorItem]
