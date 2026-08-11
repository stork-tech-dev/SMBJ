"""
Utilidades transversales del proyecto.

Todo lo que se use en más de un módulo y no tenga un lugar más
específico vive acá (Principio 2: DRY).
"""

from datetime import datetime
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

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


def redondear_hacia_arriba(valor: Decimal, multiplo: Decimal) -> Decimal:
    """
    Redondeo comercial hacia arriba al múltiplo configurado.

    Es distinto de `redondear()`: aquel es half-up sobre decimales y este
    es CEIL sobre un múltiplo. Con `multiplo = 100`, un precio de 1401
    queda en 1500 y no en 1400 — el precio de venta nunca baja por efecto
    del redondeo.

    Un múltiplo de cero o negativo no redondea nada: devuelve el valor
    tal cual en vez de dividir por cero.
    """
    if multiplo is None or multiplo <= 0:
        return valor
    return (Decimal(valor) / multiplo).quantize(Decimal(1), rounding=ROUND_CEILING) * multiplo


def normalizar_texto(valor: str | None) -> str | None:
    """Limpia espacios sobrantes; devuelve None si queda vacío."""
    if valor is None:
        return None
    limpio = " ".join(valor.split())
    return limpio or None


def capitalizar_inicial(valor: str) -> str:
    """
    Primera letra en mayúscula, **sin tocar el resto**.

    No es `.capitalize()` ni `.title()`: esos bajan todo lo demás y
    arruinarían "Anillo de PLATA 925" o "Cadena 18K", donde las mayúsculas
    son parte del dato.

    Si el texto arranca con un número —"925 plata"— queda igual, porque
    `upper()` sobre un dígito no hace nada.

    La migración 0015 hace exactamente esto en SQL
    (`upper(left(x,1)) || substr(x,2)`); si cambia una, tiene que cambiar
    la otra.
    """
    # `valor[:1]` y no `valor[0]`: con string vacío devuelve "" en vez de
    # reventar con IndexError.
    return valor[:1].upper() + valor[1:]
