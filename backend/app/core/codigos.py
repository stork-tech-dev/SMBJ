"""
Generación y validación de los códigos de producto.

Son funciones puras: no tocan la base ni dependen del ORM, así que se
prueban solas y se pueden usar desde un script o una importación masiva.

Hay DOS verificadores en juego y conviene no confundirlos:

- El **módulo 11** de acá viaja en la línea legible del código
  (`SAB123R7`) y protege el TIPEO MANUAL.
- El **módulo 103** de Code128 (ISO/IEC 15417) va codificado en el patrón
  de barras, lo calcula el encoder al generar la imagen y protege la
  LECTURA: si no coincide, el lector no emite nada. No se persiste.

Los dos son ponderados por posición, que es lo que permite detectar
transposiciones (`AB123` vs `AB213`), el error humano más frecuente.
"""

import string

# Alfabeto base36: los dígitos valen su valor y las letras siguen desde 10.
# Es el mismo criterio que usan los códigos alfanuméricos con módulo 11.
_ALFABETO = string.digits + string.ascii_uppercase
_VALOR = {c: i for i, c in enumerate(_ALFABETO)}

# Un SKU son 2 letras y 3 dígitos: AA001 … ZZ999.
_LETRAS = string.ascii_uppercase
_DIGITOS_POR_BLOQUE = 999
SKU_MAXIMO = len(_LETRAS) * len(_LETRAS) * _DIGITOS_POR_BLOQUE  # 675.324


class CodigoInvalido(ValueError):
    """El código no tiene la forma esperada."""


# ============================================================================
# SKU
# ============================================================================


def codificar_sku(n: int) -> str:
    """
    Convierte un entero correlativo en un SKU de 5 caracteres.

    1 → 'AA001', 999 → 'AA999', 1000 → 'AB001', 675324 → 'ZZ999'.

    El correlativo lo da una SEQUENCE de PostgreSQL, no un MAX()+1: con la
    secuencia dos altas simultáneas obtienen números distintos sin
    bloquearse, y no puede haber SKU repetidos.
    """
    if not isinstance(n, int) or n < 1:
        raise CodigoInvalido("El correlativo del SKU arranca en 1")
    if n > SKU_MAXIMO:
        raise CodigoInvalido(
            f"Se agotaron los SKU disponibles: el máximo es {SKU_MAXIMO:,}"
        )

    indice = n - 1
    bloque, digitos = divmod(indice, _DIGITOS_POR_BLOQUE)
    primera, segunda = divmod(bloque, len(_LETRAS))

    return f"{_LETRAS[primera]}{_LETRAS[segunda]}{digitos + 1:03d}"


def decodificar_sku(sku: str) -> int:
    """Inverso de `codificar_sku`. Útil para validar y para los tests."""
    sku = (sku or "").strip().upper()
    if len(sku) != 5 or not sku[:2].isalpha() or not sku[2:].isdigit():
        raise CodigoInvalido(f"SKU con formato inválido: '{sku}'")

    primera = _LETRAS.index(sku[0])
    segunda = _LETRAS.index(sku[1])
    digitos = int(sku[2:])
    if digitos < 1:
        raise CodigoInvalido("Los tres dígitos del SKU arrancan en 001")

    return (primera * len(_LETRAS) + segunda) * _DIGITOS_POR_BLOQUE + digitos


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
    Código de la variante: letra de la empresa + SKU + sufijo.

    Ej.: 'S' + 'AB123' + 'R' → 'SAB123R'. La variante BASE no lleva
    sufijo, así que queda 'SAB123'.

    Se calcula UNA vez, al crear la variante, y después no se recalcula
    nunca: la etiqueta ya está impresa y pegada a la mercadería. Si la
    empresa cambia de letra, los productos viejos conservan su código.
    """
    letra = (letra_empresa or "").strip().upper()
    if len(letra) != 1 or letra not in _LETRAS:
        raise CodigoInvalido(f"Letra de empresa inválida: '{letra_empresa}'")

    sku_limpio = (sku or "").strip().upper()
    decodificar_sku(sku_limpio)  # valida el formato

    if sufijo is None:
        return f"{letra}{sku_limpio}"

    sufijo_limpio = sufijo.strip().upper()
    if len(sufijo_limpio) != 1 or sufijo_limpio not in _ALFABETO:
        raise CodigoInvalido(f"Sufijo de variante inválido: '{sufijo}'")

    return f"{letra}{sku_limpio}{sufijo_limpio}"
