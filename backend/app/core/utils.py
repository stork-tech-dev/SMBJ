"""
Utilidades transversales del proyecto.

Todo lo que se use en más de un módulo y no tenga un lugar más
específico vive acá (Principio 2: DRY).
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from fastapi import Request

from config import settings


def ahora() -> datetime:
    """
    Fecha y hora actual en la zona horaria del negocio (UTC-03:00),
    con tzinfo.

    Usar para cálculos y para firmar JWT, donde la zona importa. Para
    guardar en la base, usar `ahora_db()`.
    """
    return datetime.now(tz=settings.TZ)


def ahora_db() -> datetime:
    """
    Fecha y hora actual en hora del negocio, SIN tzinfo.

    Todas las columnas del sistema son TIMESTAMP sin zona y guardan hora
    local (UTC-03:00). Si se les asigna un datetime con tzinfo, PostgreSQL
    igual lo almacena sin offset, pero el objeto que queda en memoria sí
    lo tiene: la misma fila se serializaría distinto según venga recién
    creada o leída de la base. Esta función evita esa inconsistencia.
    """
    return datetime.now(tz=settings.TZ).replace(tzinfo=None)


def ip_de_request(request: Request | None) -> str | None:
    """
    IP de origen de un request, respetando X-Forwarded-For cuando la
    aplicación corre detrás de un proxy reverso.
    """
    if request is None:
        return None

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # El primer valor de la cadena es el cliente original.
        return forwarded.split(",")[0].strip()

    return request.client.host if request.client else None


def redondear(valor: Decimal | float | int, decimales: int = 2) -> Decimal:
    """
    Redondeo monetario estándar del sistema (half-up, como espera
    el usuario de negocio, a diferencia del banker's rounding de Python).
    """
    cuantizador = Decimal(1).scaleb(-decimales)
    return Decimal(str(valor)).quantize(cuantizador, rounding=ROUND_HALF_UP)


def normalizar_texto(valor: str | None) -> str | None:
    """Limpia espacios sobrantes; devuelve None si queda vacío."""
    if valor is None:
        return None
    limpio = " ".join(valor.split())
    return limpio or None
