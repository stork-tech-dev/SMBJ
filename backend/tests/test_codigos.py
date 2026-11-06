"""
Tests de la generación y validación de códigos de producto.

Son funciones puras, así que no necesitan base ni fixtures.
"""

import pytest

from app.core.codigos import (
    CodigoInvalido,
    armar_codigo_completo,
    codificar_sku,
    codigo_es_valido,
    decodificar_sku,
    digito_verificador,
    es_sku_legado,
    sku_maximo,
)
from app.core.utils import redondear_hacia_arriba
from decimal import Decimal


# ============================================================================
# SKU
# ============================================================================


@pytest.mark.parametrize(
    "letra,n,esperado",
    [
        ("S", 1, "AAA0"),
        ("S", 10, "AAA9"),
        ("S", 11, "AAB0"),
        # Después de la H viene la J, y después de la N, la P.
        ("S", 7 * 10 + 1, "AAH0"),
        ("S", 8 * 10 + 1, "AAJ0"),
        ("S", 13 * 10 + 1, "AAP0"),
        ("S", 138240, "ZZZ9"),
        ("M", 1, "AA01"),
        ("M", 99, "AA99"),
        ("M", 100, "AB01"),
        ("M", 7 * 99 + 99, "AH99"),
        ("M", 8 * 99 + 1, "AJ01"),
        ("M", 24 * 99 + 1, "BA01"),
        ("M", 57024, "ZZ99"),
    ],
)
def test_el_sku_avanza_en_orden(letra, n, esperado):
    assert codificar_sku(n, letra) == esperado


@pytest.mark.parametrize("letra,maximo", [("S", 138240), ("M", 57024)])
def test_la_capacidad_de_cada_empresa(letra, maximo):
    assert sku_maximo(letra) == maximo


@pytest.mark.parametrize("letra", ["S", "M"])
def test_el_sku_recorre_todo_el_espacio_sin_repetir_ni_usar_i_u_o(letra):
    """Si `decodificar` no invirtiera a `codificar`, el correlativo mentiría."""
    vistos = set()
    for n in range(1, sku_maximo(letra) + 1):
        sku = codificar_sku(n, letra)
        assert "I" not in sku and "O" not in sku
        assert decodificar_sku(sku, letra) == n
        vistos.add(sku)
    assert len(vistos) == sku_maximo(letra)


@pytest.mark.parametrize("letra", ["S", "M"])
def test_el_sku_rechaza_correlativos_fuera_de_rango(letra):
    for invalido in (0, -1, sku_maximo(letra) + 1):
        with pytest.raises(CodigoInvalido):
            codificar_sku(invalido, letra)


@pytest.mark.parametrize(
    "letra,invalido",
    [
        ("S", ""), ("S", "AAA"), ("S", "AA01"), ("S", "AAI0"), ("S", "AOA0"), ("S", "AB123"),
        ("M", ""), ("M", "AA00"), ("M", "AAA0"), ("M", "AI01"), ("M", "OA01"), ("M", "AB123"),
    ],
)
def test_decodificar_rechaza_formatos_invalidos(letra, invalido):
    with pytest.raises(CodigoInvalido):
        decodificar_sku(invalido, letra)


@pytest.mark.parametrize("letra", ["", "X", "SM", None])
def test_el_sku_rechaza_una_empresa_desconocida(letra):
    with pytest.raises(CodigoInvalido):
        codificar_sku(1, letra)


@pytest.mark.parametrize(
    "sku,esperado",
    [("AA001", True), ("ZZ999", True), ("AA000", False), ("AAA0", False), ("AA01", False), ("", False)],
)
def test_reconoce_el_sku_del_formato_anterior(sku, esperado):
    assert es_sku_legado(sku) is esperado


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
        assert len(digito_verificador(codificar_sku(n, "S"))) == 1


def test_el_verificador_usa_X_para_el_diez():
    """Como el CUIT: cuando da 10 se escribe 'X', no dos caracteres."""
    vistos = {digito_verificador(codificar_sku(n, "S")) for n in range(1, 2000)}
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


@pytest.mark.parametrize(
    "letra,sku,sufijo,esperado",
    [
        ("S", "AAB0", "R", "AAB0R"),
        ("S", "AAB0", None, "AAB0"),
        ("M", "AA01", "M", "AA01M"),
        ("M", "AA01", None, "AA01"),
        ("m", "aa01", "m", "AA01M"),
    ],
)
def test_el_codigo_nuevo_no_lleva_letra_de_empresa(letra, sku, sufijo, esperado):
    assert armar_codigo_completo(letra, sku, sufijo) == esperado


@pytest.mark.parametrize(
    "letra,sku,sufijo,esperado",
    [
        ("S", "AB123", "R", "SAB123R"),
        ("S", "AB123", None, "SAB123"),
        ("M", "AA005", "M", "MAA005M"),
        ("s", "ab123", "r", "SAB123R"),
    ],
)
def test_el_sku_del_formato_anterior_conserva_la_letra(letra, sku, sufijo, esperado):
    assert armar_codigo_completo(letra, sku, sufijo) == esperado


@pytest.mark.parametrize(
    "letra,sku,sufijo",
    [("", "AAB0", None), ("SM", "AAB0", None), ("1", "AB123", None),
     ("S", "MAL", None), ("S", "AA01", None), ("M", "AAB0", None),
     ("S", "AAB0", "RR"), ("S", "AAB0", "-")],
)
def test_el_codigo_completo_rechaza_partes_invalidas(letra, sku, sufijo):
    with pytest.raises(CodigoInvalido):
        armar_codigo_completo(letra, sku, sufijo)


@pytest.mark.parametrize("sku", ["AAB0", "AB123"])
@pytest.mark.parametrize("sufijo", ["I", "O", "i", "o"])
def test_el_sufijo_no_admite_i_ni_o(sku, sufijo):
    with pytest.raises(CodigoInvalido):
        armar_codigo_completo("S", sku, sufijo)


@pytest.mark.parametrize("sufijo", ["0", "1", "R"])
def test_el_sufijo_admite_numeros_y_las_demas_letras(sufijo):
    assert armar_codigo_completo("S", "AAB0", sufijo) == f"AAB0{sufijo}"


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
