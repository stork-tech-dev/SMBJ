"""
Generación y validación de los códigos de producto.

Son funciones puras: no tocan la base ni dependen del ORM, así que se
prueban solas y se pueden usar desde un script o una importación masiva.

Hay DOS verificadores en juego y conviene no confundirlos:

- El **módulo 11** de acá viaja en la línea legible del código
  (`AAB0R7`) y protege el TIPEO MANUAL.
- La **corrección de errores Reed-Solomon** de DataMatrix (ISO/IEC 16022)
  va dentro del dibujo de la etiqueta, la calcula la librería al generarlo
  y protege la LECTURA: reconstruye módulos dañados y, si no puede, el
  lector no emite nada. No se persiste.

El módulo 11 es ponderado por posición, que es lo que permite detectar
transposiciones (`AB123` vs `AB213`), el error humano más frecuente.
"""

import re
import string
from dataclasses import dataclass

# Alfabeto base36: los dígitos valen su valor y las letras siguen desde 10.
# Es el mismo criterio que usan los códigos alfanuméricos con módulo 11.
_ALFABETO = string.digits + string.ascii_uppercase
_VALOR = {c: i for i, c in enumerate(_ALFABETO)}

# Sin I ni O: en una etiqueta se confunden con el 1 y el 0.
_LETRAS_SKU = "".join(c for c in string.ascii_uppercase if c not in "IO")
_SUFIJOS = "".join(c for c in _ALFABETO if c not in "IO")

# Formato anterior (2 letras y 3 dígitos). Ya no se genera, pero los productos
# que lo tienen conservan su código porque sus etiquetas están impresas.
_SKU_LEGADO = re.compile(r"[A-Z]{2}(?!000)[0-9]{3}")


class CodigoInvalido(ValueError):
    """El código no tiene la forma esperada."""


@dataclass(frozen=True)
class _FormatoSku:
    """Cómo es el SKU de una empresa: N letras seguidas de un rango de dígitos."""

    letras: int
    digito_minimo: int
    digito_maximo: int

    @property
    def ancho_digitos(self) -> int:
        return len(str(self.digito_maximo))

    @property
    def por_bloque(self) -> int:
        return self.digito_maximo - self.digito_minimo + 1

    @property
    def maximo(self) -> int:
        return len(_LETRAS_SKU) ** self.letras * self.por_bloque


_FORMATOS = {
    "S": _FormatoSku(letras=3, digito_minimo=0, digito_maximo=9),  # Soleil: AAA0 … ZZZ9
    "M": _FormatoSku(letras=2, digito_minimo=1, digito_maximo=99),  # Mallorca: AA01 … ZZ99
}


def _formato(letra_empresa: str) -> _FormatoSku:
    formato = _FORMATOS.get((letra_empresa or "").strip().upper())
    if formato is None:
        raise CodigoInvalido(f"Letra de empresa inválida: '{letra_empresa}'")
    return formato


# ============================================================================
# SKU
# ============================================================================


def sku_maximo(letra_empresa: str) -> int:
    """Cantidad de SKU disponibles: 138.240 en Soleil y 57.024 en Mallorca."""
    return _formato(letra_empresa).maximo


def es_sku_legado(sku: str) -> bool:
    """True si el SKU tiene el formato anterior, que llevaba la letra de empresa."""
    return _SKU_LEGADO.fullmatch(sku or "") is not None


def codificar_sku(n: int, letra_empresa: str) -> str:
    """
    Convierte un entero correlativo en el SKU de la empresa.

    Soleil:   1 → 'AAA0', 10 → 'AAA9', 11 → 'AAB0'.
    Mallorca: 1 → 'AA01', 99 → 'AA99', 100 → 'AB01'.

    El correlativo lo da una SEQUENCE de PostgreSQL, no un MAX()+1: con la
    secuencia dos altas simultáneas obtienen números distintos sin
    bloquearse, y no puede haber SKU repetidos.
    """
    formato = _formato(letra_empresa)
    if not isinstance(n, int) or n < 1:
        raise CodigoInvalido("El correlativo del SKU arranca en 1")
    if n > formato.maximo:
        raise CodigoInvalido(
            f"Se agotaron los SKU disponibles: el máximo es {formato.maximo:,}"
        )

    bloque, resto = divmod(n - 1, formato.por_bloque)
    letras = []
    for _ in range(formato.letras):
        bloque, indice = divmod(bloque, len(_LETRAS_SKU))
        letras.append(_LETRAS_SKU[indice])

    digitos = formato.digito_minimo + resto
    return f"{''.join(reversed(letras))}{digitos:0{formato.ancho_digitos}d}"


def decodificar_sku(sku: str, letra_empresa: str) -> int:
    """Inverso de `codificar_sku`. Útil para validar y para los tests."""
    formato = _formato(letra_empresa)
    sku = (sku or "").strip().upper()
    partes = re.fullmatch(
        rf"([{_LETRAS_SKU}]{{{formato.letras}}})([0-9]{{{formato.ancho_digitos}}})", sku
    )
    if partes is None:
        raise CodigoInvalido(f"SKU con formato inválido: '{sku}'")

    digitos = int(partes.group(2))
    if digitos < formato.digito_minimo:
        raise CodigoInvalido(f"SKU con formato inválido: '{sku}'")

    bloque = 0
    for letra in partes.group(1):
        bloque = bloque * len(_LETRAS_SKU) + _LETRAS_SKU.index(letra)

    return bloque * formato.por_bloque + digitos - formato.digito_minimo + 1


# ============================================================================
# DÍGITO VERIFICADOR (módulo 11)
# ============================================================================


def digito_verificador(codigo: str) -> str:
    """
    Dígito verificador módulo 11 sobre un código alfanumérico.

    Cada carácter se pondera por su posición desde la derecha con pesos
    que ciclan de 2 a 7. **La ponderación es lo que hace útil al dígito**:
    una suma simple daría lo mismo para 'AB123' y 'AB213', que es
    justamente el error que se busca detectar.

    Devuelve un carácter: '0'-'9' o 'X' cuando el resultado es 10, igual
    que el CUIT y el CBU. Por eso la columna es CHAR(1) y no un entero.
    """
    codigo = (codigo or "").strip().upper()
    if not codigo:
        raise CodigoInvalido("El código no puede estar vacío")

    total = 0
    peso = 2
    for caracter in reversed(codigo):
        if caracter not in _VALOR:
            raise CodigoInvalido(f"Carácter no admitido en el código: '{caracter}'")
        total += _VALOR[caracter] * peso
        peso = 2 if peso == 7 else peso + 1

    resto = total % 11
    if resto == 0:
        return "0"
    verificador = 11 - resto
    if verificador == 10:
        return "X"
    return str(verificador)


def codigo_es_valido(codigo_con_verificador: str) -> bool:
    """
    Valida un código tipeado a mano: separa el último carácter y lo
    compara con el que corresponde al resto.

    Es la contraparte de `digito_verificador` y lo que hace que el dígito
    sirva para algo: sin esta validación en el punto de entrada, el
    verificador es un adorno.
    """
    codigo = (codigo_con_verificador or "").strip().upper()
    if len(codigo) < 2:
        return False

    cuerpo, verificador = codigo[:-1], codigo[-1]
    try:
        return digito_verificador(cuerpo) == verificador
    except CodigoInvalido:
        return False


# ============================================================================
# CÓDIGO COMPLETO
# ============================================================================


def armar_codigo_completo(letra_empresa: str, sku: str, sufijo: str | None) -> str:
    """
    Código de la variante: SKU + sufijo. La variante BASE no lleva sufijo.

    Ej.: 'AAB0' + 'R' → 'AAB0R'; la base queda 'AAB0'.

    Un SKU legado lleva además la letra de la empresa adelante ('S' + 'AB123'
    + 'R' → 'SAB123R'), para que una variante nueva quede igual a las demás
    de su producto.

    Se calcula UNA vez, al crear la variante, y después no se recalcula
    nunca: la etiqueta ya está impresa y pegada a la mercadería.
    """
    letra = (letra_empresa or "").strip().upper()
    _formato(letra)  # valida la letra

    sku_limpio = (sku or "").strip().upper()
    if es_sku_legado(sku_limpio):
        prefijo = f"{letra}{sku_limpio}"
    else:
        decodificar_sku(sku_limpio, letra)  # valida el formato
        prefijo = sku_limpio

    if sufijo is None:
        return prefijo

    sufijo_limpio = sufijo.strip().upper()
    if len(sufijo_limpio) != 1 or sufijo_limpio not in _SUFIJOS:
        raise CodigoInvalido(
            f"Sufijo de variante inválido: '{sufijo}'. "
            "Tiene que ser una letra (salvo I y O) o un número"
        )

    return f"{prefijo}{sufijo_limpio}"
