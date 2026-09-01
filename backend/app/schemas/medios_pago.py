"""
Schemas de medios de pago y planes de cuotas.

Los dos porcentajes viajan por separado y con nombres distintos —
`recargo_cliente` y `costo_medio` — para que ningún consumidor de la API
pueda confundirlos: uno cambia lo que paga el cliente y el otro no.
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PlanCuotasCrear(BaseModel):
    cuotas: int = Field(ge=1, le=99)
    recargo_cliente: Decimal = Field(
        ge=0, le=100, description="% que se le suma al cliente. 0 = sin interés"
    )
    costo_medio: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        le=100,
        description="% que cobra la terminal. Solo para reportes: NO afecta el precio",
    )
    monto_minimo: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Monto de venta a partir del cual se ofrece. 0 = siempre",
    )


class PlanCuotasEditar(BaseModel):
    cuotas: int | None = Field(default=None, ge=1, le=99)
    recargo_cliente: Decimal | None = Field(default=None, ge=0, le=100)
    costo_medio: Decimal | None = Field(default=None, ge=0, le=100)
    monto_minimo: Decimal | None = Field(default=None, ge=0)
    activo: bool | None = None


class PlanCuotasResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    medio_de_pago_id: int
    cuotas: int
    recargo_cliente: Decimal
    costo_medio: Decimal
    monto_minimo: Decimal
    activo: bool
    sin_interes: bool


class MedioDePagoCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=60)
    soporta_cuotas: bool = False
    es_sena: bool = Field(
        default=False,
        description="Marca el medio con el que se descuentan las señas. Solo uno",
    )


class MedioDePagoEditar(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=60)
    soporta_cuotas: bool | None = None
    es_sena: bool | None = None
    activo: bool | None = None


class EstadoCambio(BaseModel):
    """Cuerpo de los PATCH `/estado`, compartido por medios y planes."""

    activo: bool


class MedioDePagoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    soporta_cuotas: bool
    es_sena: bool
    activo: bool
    planes: list[PlanCuotasResponse] = []


class MedioDisponible(BaseModel):
    """
    Un medio como lo ve el punto de venta, con los planes que ESTE monto
    habilita.

    Es distinto de `MedioDePagoResponse`: aquel es el catálogo completo para
    Configuración, y este ya viene filtrado. La vendedora no tiene que
    conocer las reglas — solo elegir entre lo que se le ofrece.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    soporta_cuotas: bool
    es_sena: bool
    planes: list[PlanCuotasResponse] = []
