"""
Tests de la generación y validación de códigos de producto.

Son funciones puras, así que no necesitan base ni fixtures.
"""

import pytest

from app.core.codigos import (
    SKU_MAXIMO,
    CodigoInvalido,
    armar_codigo_completo,
    codificar_sku,
    codigo_es_valido,
    decodificar_sku,
    digito_verificador,
)
from app.core.utils import redondear_hacia_arriba
from decimal import Decimal


# ============================================================================
# SKU
# ============================================================================


@pytest.mark.parametrize(
    "n,esperado",
    [
        (1, "AA001"),
        (999, "AA999"),
        (1000, "AB001"),
        (1001, "AB002"),
        (25 * 999 + 1, "AZ001"),
        (26 * 999 + 1, "BA001"),
        (SKU_MAXIMO, "ZZ999"),
    ],
)
def test_el_sku_avanza_en_orden(n, esperado):
    assert codificar_sku(n) == esperado


def test_el_sku_es_reversible():
    """Si `decodificar` no invirtiera a `codificar`, el correlativo mentiría."""
    for n in (1, 42, 999, 1000, 12345, SKU_MAXIMO):
        assert decodificar_sku(codificar_sku(n)) == n


def test_el_sku_no_se_repite_en_todo_el_espacio():
    """Muestra amplia: cada correlativo da un código distinto."""
    muestra = list(range(1, 3000)) + [100000, 400000, SKU_MAXIMO]
    codigos = {codificar_sku(n) for n in muestra}
    assert len(codigos) == len(muestra)


@pytest.mark.parametrize("invalido", [0, -1, SKU_MAXIMO + 1])
def test_el_sku_rechaza_correlativos_fuera_de_rango(invalido):
    with pytest.raises(CodigoInvalido):
        codificar_sku(invalido)


@pytest.mark.parametrize("invalido", ["", "ABC12", "A1234", "AB12", "AB0000", "AB000"])
def test_decodificar_rechaza_formatos_invalidos(invalido):
    with pytest.raises(CodigoInvalido):
        decodificar_sku(invalido)


# ============================================================================
# DÍGITO VERIFICADOR
# ============================================================================


def test_el_verificador_es_estable():
    """El mismo código da siempre el mismo dígito."""
    assert digito_verificador("SAB123R") == digito_verificador("SAB123R")


def test_el_verificador_detecta_un_caracter_cambiado():
    assert digito_verificador("SAB123R") != digito_verificador("SAB124R")


def test_el_verificador_detecta_transposiciones():
    """
    Su razón de ser: una suma sin ponderar daría lo mismo para los dos, y
    cambiar dos dígitos de lugar es el error de tipeo más común.
    """
    assert digito_verificador("SAB123R") != digito_verificador("SAB213R")
    assert digito_verificador("AB123") != digito_verificador("AB132")


def test_el_verificador_devuelve_un_solo_caracter():
    """Tiene que entrar en la columna CHAR(1)."""
    for n in range(1, 500):
        assert len(digito_verificador(codificar_sku(n))) == 1


def test_el_verificador_usa_X_para_el_diez():
    """Como el CUIT: cuando da 10 se escribe 'X', no dos caracteres."""
    vistos = {digito_verificador(codificar_sku(n)) for n in range(1, 2000)}
    assert "X" in vistos, "en 2000 códigos debería aparecer al menos un 10"
    assert vistos <= set("0123456789X")


def test_validar_acepta_el_codigo_correcto():
    codigo = "SAB123R"
    assert codigo_es_valido(codigo + digito_verificador(codigo))


def test_validar_rechaza_un_codigo_mal_tipeado():
    codigo = "SAB123R"
    completo = codigo + digito_verificador(codigo)
    # Se transponen dos caracteres del cuerpo, dejando el verificador.
    roto = "SAB213R" + completo[-1]
    assert not codigo_es_valido(roto)


@pytest.mark.parametrize("invalido", ["", "A", None])
def test_validar_rechaza_basura(invalido):
    assert not codigo_es_valido(invalido)


def test_el_verificador_rechaza_caracteres_no_admitidos():
    with pytest.raises(CodigoInvalido):
        digito_verificador("SAB-123")


# ============================================================================
# CÓDIGO COMPLETO
# ============================================================================


def test_el_codigo_completo_concatena_empresa_sku_y_sufijo():
    assert armar_codigo_completo("S", "AB123", "R") == "SAB123R"


def test_la_variante_base_no_lleva_sufijo():
    assert armar_codigo_completo("S", "AB123", None) == "SAB123"


def test_el_codigo_completo_normaliza_a_mayusculas():
    assert armar_codigo_completo("s", "ab123", "r") == "SAB123R"


@pytest.mark.parametrize(
    "letra,sku,sufijo",
    [("", "AB123", None), ("SM", "AB123", None), ("1", "AB123", None),
     ("S", "MAL", None), ("S", "AB123", "RR"), ("S", "AB123", "-")],
)
def test_el_codigo_completo_rechaza_partes_invalidas(letra, sku, sufijo):
    with pytest.raises(CodigoInvalido):
        armar_codigo_completo(letra, sku, sufijo)


# ============================================================================
# REDONDEO COMERCIAL
# ============================================================================


@pytest.mark.parametrize(
    "valor,multiplo,esperado",
    [
        ("1401", "100", "1500"),   # nunca baja
        ("1400", "100", "1400"),   # el múltiplo exacto no se mueve
        ("1400.01", "100", "1500"),
        ("1", "100", "100"),
        ("1234.56", "10", "1240"),
        ("999.99", "0.50", "1000.00"),
    ],
)
def test_el_precio_redondea_siempre_hacia_arriba(valor, multiplo, esperado):
    assert redondear_hacia_arriba(Decimal(valor), Decimal(multiplo)) == Decimal(esperado)


def test_un_multiplo_de_cero_no_redondea():
    """Evita la división por cero si la configuración queda mal cargada."""
    assert redondear_hacia_arriba(Decimal("1401"), Decimal("0")) == Decimal("1401")
