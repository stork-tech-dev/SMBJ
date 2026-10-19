"""
Respuestas de los Reportes de Productividad (`/api/v1/reportes/productividad`).

Datos crudos (Principio 1): cantidades enteras e importes en Decimal; el
formato de pesos y fechas lo pone la pantalla.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.stock import PuntoResumen


class _Periodo(BaseModel):
    # El rango que se usó: si no se pidió, del primer día del mes a hoy.
    fecha_desde: date
    fecha_hasta: date


# --- Centro de Distribución ---


class ValoresCD(BaseModel):
    # Variantes vendibles dadas de alta (un producto sin talles cuenta 1).
    productos: int
    # Remitos enviados desde el CD y unidades que llevaban.
    remitos: int
    unidades_remitidas: int


class FilaCD(ValoresCD):
    usuario_id: int
    usuario_nombre: str


class ReporteProductividadCD(_Periodo):
    filas: list[FilaCD]
    totales: ValoresCD


# --- Vendedores ---


class ValoresVendedor(BaseModel):
    # Ventas confirmadas: cantidad, unidades (una por ítem) e importe.
    ventas: int
    unidades: int
    importe: Decimal
    senas: int
    importe_senas: Decimal
    # Cambios confirmados.
    cambios: int


class FilaVendedor(ValoresVendedor):
    usuario_id: int
    usuario_nombre: str


class ReporteProductividadVendedores(_Periodo):
    filas: list[FilaVendedor]
    totales: ValoresVendedor
    opciones_locales: list[PuntoResumen]
