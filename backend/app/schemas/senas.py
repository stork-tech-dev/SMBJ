"""Schemas de señas."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.clientes import ClienteResumen


class ClienteNuevoEnSena(BaseModel):
    """
    El cliente que se crea en el momento de dejar la seña. Lo mínimo del
    mostrador: el nombre, y el DNI para encontrarlo al cobrar.
    """

    nombre: str = Field(min_length=1, max_length=150)
    dni: str | None = Field(default=None, max_length=15)
    telefono: str | None = Field(default=None, max_length=30)


class SenaCrear(BaseModel):
    """
    Alta de seña. El cliente es obligatorio: una seña sin cliente sería
    plata de nadie, y al cobrar no habría a quién ofrecérsela. Va uno
    existente (`cliente_id`) o uno nuevo (`cliente_nuevo`), nunca los dos.

    `medio_de_pago_id` es con qué pagó: la plata entra a la caja del turno
    abierto del local desde el que se registra.
    """

    cliente_id: int | None = None
    cliente_nuevo: ClienteNuevoEnSena | None = None
    medio_de_pago_id: int
    monto: Decimal = Field(gt=0)
    descripcion: str | None = None

    @model_validator(mode="after")
    def _un_solo_cliente(self):
        if (self.cliente_id is None) == (self.cliente_nuevo is None):
            raise ValueError("Indicá un cliente existente o los datos de uno nuevo")
        return self


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
    medio_de_pago_id: int | None
    punto_de_venta_id: int | None
    vence_el: date
    created_at: datetime
    updated_at: datetime
    cliente: ClienteResumen


class MedioParaSena(BaseModel):
    """Un medio con el que el cliente puede dejar la seña."""

    id: int
    nombre: str


class UsoDeSena(BaseModel):
    """Una venta donde se usó la seña, para el historial de su ficha."""

    venta_id: int
    numero: str
    monto: Decimal
    fecha: datetime


class SenaDetalle(SenaResponse):
    usos: list[UsoDeSena] = []


class VigenciaSenas(BaseModel):
    """Días que dura una seña desde su alta (`configuracion_sistema`)."""

    dias: int = Field(gt=0, le=3650)
