"""
Filtros de consulta que comparten varios endpoints.

`rango_de_fechas` es el filtro Desde/Hasta de los reportes por período
(Novedades de caja, Productividad): mismos nombres de parámetro, mismos
valores por defecto y la misma validación en todos (Principio 2).
"""

from datetime import date

from fastapi import HTTPException, Query, status

from app.core.utils import ahora_db


def rango_de_fechas(
    fecha_desde: date | None = Query(default=None, description="Vacío = inicio del mes"),
    fecha_hasta: date | None = Query(default=None, description="Vacío = hoy"),
) -> tuple[date, date]:
    """
    Desde/hasta inclusive. Lo que falte se completa con el período que se
    mira por defecto: del primer día del mes en curso a hoy.
    """
    hasta = fecha_hasta or ahora_db().date()
    desde = fecha_desde or hasta.replace(day=1)
    if desde > hasta:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La fecha desde no puede ser posterior a la fecha hasta",
        )
    return desde, hasta
