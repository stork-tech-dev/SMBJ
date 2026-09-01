"""
Utilidades transversales del proyecto.

Todo lo que se use en más de un módulo y no tenga un lugar más
específico vive acá (Principio 2: DRY).
"""

from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from fastapi import Request
from sqlalchemy import func

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


def redondear_hacia_abajo(valor: Decimal, multiplo: Decimal) -> Decimal:
    """
    El espejo de `redondear_hacia_arriba`: FLOOR sobre el múltiplo configurado.

    Va para el otro lado a propósito. El precio de lista se redondea hacia
    ARRIBA —el redondeo nunca puede hacer que se cobre menos de lo que
    corresponde— pero el precio con descuento se redondea hacia ABAJO, por el
    mismo motivo visto desde el cliente: un 20% que termina descontando 19,6%
    porque el redondeo lo empujó para arriba es un descuento que no se cumplió.

    Un múltiplo de cero o negativo no redondea nada: devuelve el valor tal
    cual en vez de dividir por cero.
    """
    if multiplo is None or multiplo <= 0:
        return valor
    return (Decimal(valor) / multiplo).quantize(Decimal(1), rounding=ROUND_FLOOR) * multiplo


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


# Las dos caras de la misma tabla de reemplazo: la de Python y la de SQL
# tienen que decir exactamente lo mismo, o "café" tipeado sin tilde
# encontraría distinto según de qué lado se limpie el texto. Por eso las
# constantes están una sola vez y las dos funciones las comparten.
#
# Solo las letras del español: la `ü` de "vergüenza" y la `ñ` incluidas.
_CON_TILDE = "áéíóúüñÁÉÍÓÚÜÑ"
_SIN_TILDE = "aeiouunAEIOUUN"
_TABLA_SIN_TILDE = str.maketrans(_CON_TILDE, _SIN_TILDE)


def sin_tildes(valor: str) -> str:
    """
    El texto con las vocales acentuadas y la eñe reemplazadas por su letra
    pelada, para comparar sin que la tilde decida.

    Es la mitad de la operación: el otro lado de la comparación es una
    columna de la base y se limpia con `sin_tildes_sql()`.
    """
    return valor.translate(_TABLA_SIN_TILDE)


def sin_tildes_sql(columna):
    """
    Lo mismo que `sin_tildes()`, pero aplicado a una columna dentro de la
    consulta.

    Se resuelve con `translate()` de Postgres y no con la extensión
    `unaccent` a propósito: `unaccent` hay que instalarla en la base y
    exige permisos de superusuario, y el proyecto se despliega
    self-hosted sin garantía de tenerlos. `translate` es SQL estándar y
    no necesita nada.

    El costo es que la comparación deja de poder usar el índice de la
    columna, así que sirve para búsquedas acotadas (un desplegable de
    sugerencias), no para barrer la tabla entera.
    """
    return func.translate(columna, _CON_TILDE, _SIN_TILDE)
