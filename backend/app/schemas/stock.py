"""
Schemas del control de stock: existencias, movimientos y mínimos.

Los remitos y las auditorías de inventario tienen sus propios archivos: son
flujos con estado, no consultas.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.productos import ProductoResumen


class PuntoResumen(BaseModel):
    """
    Lo mínimo para identificar una ubicación. `tipo` viaja porque decide
    cuál de los dos mínimos aplica, y la pantalla lo usa para rotularlo.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    nombre: str
    tipo: str


class VarianteEnStock(BaseModel):
    """
    La variante vista desde el stock: el código que se escanea y de qué
    producto es. No trae sus hermanas ni el pool completo de fotos: acá
    la fila es la variante EN una ubicación. Solo viaja la URL de la foto
    principal (con fallback variante → producto) para el thumbnail.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo_completo: str
    verificador: str
    sufijo: str | None
    descripcion_sufijo: str | None
    es_base: bool
    foto_url: str | None = None
    producto: ProductoResumen


class StockResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cantidad: int
    # Los dos que se cargan y el que efectivamente rige acá. Cuál de los dos
    # aplica lo decide el tipo del punto de venta, y lo resuelve el backend:
    # es una regla de negocio, no formato de pantalla (Principio 1).
    stock_minimo_cd: int
    stock_minimo_local: int
    stock_minimo: int
    bajo_minimo: bool
    updated_at: datetime
    variante: VarianteEnStock
    punto_de_venta: PuntoResumen


class StockMinimos(BaseModel):
    """
    Lo único editable a mano de una fila de stock.

    La CANTIDAD no está, y no es un olvido: se mueve con movimientos, que son
    los que dejan registro de por qué cambió. Para corregir un número que
    quedó mal hay una auditoría de inventario o una baja, no un UPDATE.
    """

    stock_minimo_cd: int | None = Field(default=None, ge=0)
    stock_minimo_local: int | None = Field(default=None, ge=0)


class IngresoCrear(BaseModel):
    """Mercadería nueva que entra al depósito, sin remito de origen."""

    variante_id: int
    punto_de_venta_id: int
    cantidad: int = Field(gt=0)
    notas: str | None = None


class BajaCrear(BaseModel):
    """Rotura, robo, muestra o merma: mercadería que deja de estar."""

    variante_id: int
    punto_de_venta_id: int
    cantidad: int = Field(gt=0)
    motivo_baja_id: int
    notas: str | None = None


class MovimientoResponse(BaseModel):
    """
    Una línea del historial.

    Las dos puntas viajan como resumen y no como id suelto: el historial se
    lee, y un número no dice de qué local se trata.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo: str
    cantidad: int
    timestamp: datetime
    notas: str | None
    variante: VarianteEnStock
    origen: PuntoResumen | None
    destino: PuntoResumen | None
    usuario_id: int
    remito_id: int | None
    motivo_baja_id: int | None
    auditoria_id: int | None
    referencia_venta_id: int | None


class MotivoBajaCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)


class MotivoBajaEditar(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    activo: bool | None = None


class MotivoBajaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    activo: bool


class ResumenStock(BaseModel):
    """
    Los números del encabezado de la pantalla: cuántas filas hay, cuántas
    unidades suman, cuántas están por reponerse y cuánto vale lo que hay.

    `valorizado` va crudo: el formato de moneda lo pone el frontend
    (Principio 1).
    """

    filas: int
    unidades: int
    alertas: int
    valorizado: Decimal
