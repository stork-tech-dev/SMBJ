"""
Excel de los Reportes de Productividad: una fila por usuario y la de totales
en negrita, sobre el dict de `services/reportes_productividad.py`.
"""

from app.reports.tabla_excel import generar_xls_tabla


def _periodo(datos: dict) -> str:
    return (f"Total {datos['fecha_desde'].strftime('%d/%m/%Y')} al "
            f"{datos['fecha_hasta'].strftime('%d/%m/%Y')}")


def _con_totales(datos: dict, campos: list[str]) -> tuple[list[list], list[int]]:
    filas = [[f["usuario_nombre"], *(f[c] for c in campos)] for f in datos["filas"]]
    filas.append([_periodo(datos), *(datos["totales"][c] for c in campos)])
    return filas, [len(filas) - 1]


def xls_centro_distribucion(datos: dict) -> bytes:
    campos = ["productos", "remitos", "unidades_remitidas"]
    filas, negrita = _con_totales(datos, campos)
    return generar_xls_tabla(
        "Productividad CD",
        ["Usuario", "Productos", "Remitos", "Unidades remitidas"],
        filas, filas_negrita=negrita, anchos=[34, 12, 12, 20],
    )


def xls_vendedores(datos: dict) -> bytes:
    campos = ["ventas", "unidades", "importe", "senas", "importe_senas", "cambios"]
    filas, negrita = _con_totales(datos, campos)
    return generar_xls_tabla(
        "Productividad vendedores",
        ["Usuario", "Ventas", "Unidades", "Importe", "Señas", "Importe señas", "Cambios"],
        filas, columnas_monto=[3, 5], filas_negrita=negrita,
        anchos=[34, 10, 10, 16, 10, 16, 10],
    )
