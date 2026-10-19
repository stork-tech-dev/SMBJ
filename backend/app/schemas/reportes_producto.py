"""
Respuestas del reporte "Historial del Producto"
(`/api/v1/reportes/historial-producto`).

Datos crudos (Principio 1): fechas, Decimal y los valores de los enums
(`tipo` de movimiento, `campo` de precio); los textos para mostrar los pone
la pantalla.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProductoEncontrado(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    descripcion: str
    activo: bool
    # La foto principal (o la primera), para reconocerlo en el buscador.
    foto_url: str | None = Field(default=None, validation_alias="foto_principal_url")


class Ficha(BaseModel):
    producto_id: int
    sku: str
    descripcion: str
    categoria: str
    proveedor: str
    precio_usd: Decimal
    precio_venta: Decimal
    stock_total: int
    activo: bool
    created_at: datetime
    variantes: list[str]


class FilaCarga(BaseModel):
    fecha: datetime
    tipo: str  # "alta" | "ingreso"
    variante: str | None
    cantidad: int | None
    punto_de_venta: str | None
    usuario: str | None


class FilaMovimiento(BaseModel):
    fecha: datetime
    tipo: str  # TipoMovimiento.value
    variante: str
    cantidad: int
    origen: str | None
    destino: str | None
    usuario: str
    referencia: str | None


class FilaVenta(BaseModel):
    fecha: datetime
    venta_id: int
    numero: str
    punto_de_venta: str
    variante: str
    precio: Decimal


class VentasPorLocal(BaseModel):
    punto_de_venta: str
    unidades: int
    importe: Decimal


class Ventas(BaseModel):
    detalle: list[FilaVenta]
    por_local: list[VentasPorLocal]
    unidades: int
    importe: Decimal


class FilaFalla(BaseModel):
    fecha: datetime
    tipo: str  # "cambio_falla" | "baja"
    variante: str
    cantidad: int
    punto_de_venta: str | None
    # Motivo de la baja, o quién autorizó el cambio por falla.
    detalle: str | None
    usuario: str


class FilaPrecio(BaseModel):
    fecha: datetime
    # "precio_usd" | "precio_venta" | "descuento_producto" | "dolar_proveedor"
    campo: str
    variante: str | None
    anterior: Decimal | None
    nuevo: Decimal | None
    usuario: str | None
    # Solo en los cambios de dólar: manual o masivo.
    origen: str | None = None


class HistorialProducto(BaseModel):
    ficha: Ficha
    carga: list[FilaCarga]
    movimientos: list[FilaMovimiento]
    ventas: Ventas
    fallas: list[FilaFalla]
    precios: list[FilaPrecio]
