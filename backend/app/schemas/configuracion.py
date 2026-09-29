"""Schemas de "Ajustes": los parámetros globales que edita la Cuenta Maestra."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class AjustesResponse(BaseModel):
    """Valores actuales. Datos crudos: el formato (%, $, días) lo pone la pantalla."""

    model_config = ConfigDict(from_attributes=True)

    redondeo: Decimal
    descuento_maximo: Decimal
    tope_descuento_venta: Decimal
    paso_descuento: int
    dias_vigencia_sena: int
    pesos_por_punto: Decimal
    dias_plazo_cambio: int
    # La lista que resulta de paso + tope: lo que verá la vendedora.
    porcentajes_descuento: list[int]


class AjustesEditar(BaseModel):
    """
    Edición parcial: se manda solo lo que cambia. Los rangos de acá son la
    primera barrera; las reglas que cruzan campos (el paso no puede superar
    el tope) las valida el service con los valores combinados.
    """

    redondeo: Decimal | None = Field(default=None, gt=0)
    descuento_maximo: Decimal | None = Field(default=None, ge=0, le=100)
    tope_descuento_venta: Decimal | None = Field(default=None, gt=0, le=100)
    paso_descuento: int | None = Field(default=None, gt=0, le=100)
    dias_vigencia_sena: int | None = Field(default=None, gt=0, le=3650)
    pesos_por_punto: Decimal | None = Field(default=None, gt=0)
    dias_plazo_cambio: int | None = Field(default=None, gt=0, le=3650)
