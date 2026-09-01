"""
Schemas de clientes y de su cuenta de puntos.

El saldo de puntos viaja como entero crudo, no como texto armado: el
formato es del frontend (Principio 1).
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ClienteCrear(BaseModel):
    """
    Alta de cliente. Solo el nombre es obligatorio.

    El DNI no lo es a propósito: en el mostrador se carga a alguien con el
    nombre y el teléfono, y exigir el documento haría que la vendedora
    invente uno o directamente no cargue al cliente.
    """

    nombre: str = Field(min_length=1, max_length=150)
    dni: str | None = Field(default=None, max_length=15)
    domicilio: str | None = Field(default=None, max_length=200)
    codigo_postal: str | None = Field(default=None, max_length=10)
    localidad: str | None = Field(default=None, max_length=100)
    telefono: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=150)


class ClienteEditar(BaseModel):
    """
    Edición. Todo opcional: se manda solo lo que cambia.

    `dni` en NULL significa algo concreto —sacarle el documento cargado— y no
    "no lo mandes". Esa diferencia la resuelve el router mirando qué campos
    vinieron en el JSON (`model_fields_set`), que es lo único que distingue
    un NULL explícito de una ausencia.
    """

    nombre: str | None = Field(default=None, min_length=1, max_length=150)
    dni: str | None = Field(default=None, max_length=15)
    domicilio: str | None = Field(default=None, max_length=200)
    codigo_postal: str | None = Field(default=None, max_length=10)
    localidad: str | None = Field(default=None, max_length=100)
    telefono: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=150)


class ClienteEstado(BaseModel):
    activo: bool


class ClienteResumen(BaseModel):
    """
    Lo mínimo para identificar un cliente: lo que devuelve la búsqueda del
    punto de venta y lo que viaja dentro de una venta.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    dni: str | None
    activo: bool


class ClienteResponse(ClienteResumen):
    """La fila del listado, con el saldo de puntos ya resuelto."""

    domicilio: str | None
    codigo_postal: str | None
    localidad: str | None
    telefono: str | None
    email: str | None
    created_at: datetime
    updated_at: datetime

    # Calculado en el service sumando `puntos_cliente`; no es una columna
    # (Principio 4). Lo completa el router.
    puntos: int = 0


class PromocionDeCliente(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    tipo: str
    activo: bool


class SenaDeCliente(BaseModel):
    """Las señas con saldo del cliente, para ofrecerlas al cobrar."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    monto: Decimal
    saldo: Decimal
    descripcion: str | None
    created_at: datetime


class ClienteFicha(ClienteResponse):
    """
    La ficha completa: el cliente más todo lo que cuelga de él.

    Va en una sola respuesta y no en cuatro endpoints porque la pantalla los
    muestra juntos: pedirlos por separado sería dibujar la ficha cuatro
    veces mientras llegan.
    """

    saldo_senas: Decimal = Decimal("0")
    senas: list[SenaDeCliente] = []
    promociones: list[PromocionDeCliente] = []


class PuntoMovimientoResponse(BaseModel):
    """Una línea del historial de puntos."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo: str
    cantidad: int
    descripcion: str | None
    venta_id: int | None
    usuario_id: int
    timestamp: datetime


class PuntosAjuste(BaseModel):
    """
    Corrección manual del saldo.

    `cantidad` va con signo: positivo suma, negativo resta. El motivo es
    obligatorio — un ajuste sin explicación es un número que nadie puede
    justificar después.
    """

    cantidad: int = Field(description="Positivo suma puntos, negativo los resta")
    descripcion: str = Field(min_length=1, description="Por qué se ajusta")


class PuntosCanje(BaseModel):
    """Canje de puntos. La cantidad va en positivo: el signo lo pone el service."""

    cantidad: int = Field(gt=0)
    descripcion: str | None = None
