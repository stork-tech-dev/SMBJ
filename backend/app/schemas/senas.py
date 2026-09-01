"""Schemas de señas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.clientes import ClienteResumen


class SenaCrear(BaseModel):
    """
    Alta de seña. El cliente es obligatorio: una seña sin cliente sería
    plata de nadie, y al cobrar no habría a quién ofrecérsela.
    """

    cliente_id: int
    monto: Decimal = Field(gt=0)
    descripcion: str | None = None


class SenaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    monto: Decimal
    saldo: Decimal
    # Cuánto ya se aplicó a ventas. Lo calcula el modelo: es `monto - saldo`,
    # y hacerlo en el frontend sería repetir la resta en cada pantalla.
    usado: Decimal
    descripcion: str | None
    usuario_id: int
    activo: bool
    created_at: datetime
    updated_at: datetime
    cliente: ClienteResumen


class UsoDeSena(BaseModel):
    """Una venta donde se usó la seña, para el historial de su ficha."""

    venta_id: int
    numero: str
    monto: Decimal
    fecha: datetime


class SenaDetalle(SenaResponse):
    usos: list[UsoDeSena] = []
