"""
Excel de los Reportes de Caja. Cada función recibe el dict que devuelve su
función en `services/reportes_caja.py` y lo baja a filas para
`generar_xls_tabla`. Los subtotales van como filas en negrita, igual que en
pantalla.
"""

from app.reports.tabla_excel import generar_xls_tabla


def _hora(dt) -> str:
    return dt.strftime("%H:%M") if dt else ""


def _turno(t: dict) -> str:
    """"Local HH:MM – HH:MM" (o "en curso") para rotular un turno."""
    hasta = _hora(t["fecha_cierre"]) if t["fecha_cierre"] else "en curso"
    return f"{t['punto_de_venta_nombre']} {_hora(t['fecha_apertura'])} – {hasta}"


class _Tabla:
    """Acumula filas y recuerda cuáles van en negrita o en rojo."""

    def __init__(self):
        self.filas: list[list] = []
        self.negrita: list[int] = []
        self.rojo: list[int] = []

    def fila(self, valores: list, *, negrita: bool = False, rojo: bool = False) -> None:
        if negrita:
            self.negrita.append(len(self.filas))
        if rojo:
            self.rojo.append(len(self.filas))
        self.filas.append(valores)

    def xls(self, titulo: str, encabezados: list[str], montos, anchos=None) -> bytes:
        return generar_xls_tabla(
            titulo, encabezados, self.filas,
            columnas_monto=montos, filas_negrita=self.negrita,
            filas_destacadas=self.rojo, anchos=anchos,
        )


def xls_novedades(datos: dict) -> bytes:
    t = _Tabla()
    for turno in datos["turnos"]:
        for n in turno["novedades"]:
            t.fila([_turno(turno), _hora(n["timestamp"]), n["concepto"],
                    n["tipo"].capitalize(), n["monto"], n["autorizador_nombre"], n["notas"] or ""])
        t.fila([_turno(turno), "", "Subtotal (entradas − salidas)", "", turno["neto"], "", ""],
               negrita=True)
    t.fila(["Total del día", "", "Entradas", "", datos["total_entradas"], "", ""], negrita=True)
    t.fila(["Total del día", "", "Salidas", "", datos["total_salidas"], "", ""], negrita=True)
    t.fila(["Total del día", "", "Neto", "", datos["neto"], "", ""], negrita=True)
    return t.xls("Novedades de caja",
                 ["Turno", "Hora", "Concepto", "Tipo", "Monto", "Autorizó", "Notas"],
                 montos=[4], anchos=[34, 8, 30, 10, 14, 22, 30])


def xls_arqueos(datos: dict) -> bytes:
    columnas = datos["columnas"]
    encabezados = ["Turno", "Cerró"]
    for c in columnas:
        encabezados += [f"{c} sistema", f"{c} contado", f"{c} diferencia"]
    encabezados += ["Total sistema", "Total contado", "Diferencia"]

    t = _Tabla()
    for fila in datos["filas"]:
        por_columna = {i["columna"]: i for i in fila["items"]}
        valores = [_turno(fila), fila["usuario_nombre"]]
        for c in columnas:
            item = por_columna.get(c)
            valores += (
                [item["monto_esperado"], item["monto_declarado"], item["diferencia"]]
                if item else ["", "", ""]
            )
        valores += [fila["total_esperado"], fila["total_declarado"], fila["diferencia"]]
        t.fila(valores, rojo=fila["diferencia"] != 0)
    return t.xls("Arqueos de caja", encabezados, montos=range(2, len(encabezados)),
                 anchos=[34, 20] + [14] * (len(encabezados) - 2))


def xls_movimientos(datos: dict) -> bytes:
    t = _Tabla()
    for turno in datos["turnos"]:
        for m in turno["movimientos"]:
            t.fila([_turno(turno), _hora(m["timestamp"]), m["detalle"],
                    m["medio_de_pago"] or "", m["ingreso"] or "", m["egreso"] or ""])
        t.fila([_turno(turno), "", "Totales del turno", "",
                turno["total_ingresos"], turno["total_egresos"]], negrita=True)
        t.fila([_turno(turno), "", "Efectivo esperado en caja", "",
                turno["efectivo_esperado"], ""], negrita=True)
    return t.xls("Movimientos de caja",
                 ["Turno", "Hora", "Detalle", "Medio de pago", "Ingreso", "Egreso"],
                 montos=[4, 5], anchos=[34, 8, 40, 20, 14, 14])


def xls_retiros_efectivo(datos: dict) -> bytes:
    t = _Tabla()
    for r in datos["filas"]:
        t.fila([_hora(r["timestamp"]), r["punto_de_venta_nombre"], r["usuario_nombre"],
                r["registrado_por_nombre"], r["monto"]])
    t.fila(["Total", "", "", "", datos["total"]], negrita=True)
    return t.xls("Retiros de efectivo",
                 ["Hora", "Local", "Retiró", "Registró", "Monto"],
                 montos=[4], anchos=[8, 24, 24, 24, 14])


def xls_cobros_joyero(datos: dict) -> bytes:
    t = _Tabla()
    for c in datos["filas"]:
        t.fila([_hora(c["timestamp"]), c["punto_de_venta_nombre"], c["vendedora_nombre"],
                c["numero_reclamo"] or "", c["medio_de_pago"], c["monto"]])
    for total in datos["totales_por_medio"]:
        t.fila([f"Total {total['medio_de_pago']}", "", "", "", "", total["monto"]], negrita=True)
    t.fila(["Total", "", "", "", "", datos["total"]], negrita=True)
    return t.xls("Cobros de joyero",
                 ["Hora", "Local", "Vendedora", "N° reclamo", "Medio de pago", "Monto"],
                 montos=[5], anchos=[8, 24, 24, 14, 20, 14])


def xls_senas(datos: dict) -> bytes:
    t = _Tabla()
    for s in datos["filas"]:
        t.fila([s["created_at"].strftime("%d/%m/%Y %H:%M"), s["cliente_nombre"], s["monto"],
                s["saldo"], s["fecha_vencimiento"].strftime("%d/%m/%Y"), s["estado"].capitalize()],
               rojo=s["estado"] == "vencida")
    t.fila(["Total", "", datos["total_monto"], datos["total_saldo"], "", ""], negrita=True)
    return t.xls("Señas",
                 ["Alta", "Cliente", "Monto", "Saldo restante", "Vence", "Estado"],
                 montos=[2, 3], anchos=[18, 30, 14, 16, 12, 12])


def xls_retiros_mercaderia(datos: dict) -> bytes:
    t = _Tabla()
    for g in datos["empleadas"]:
        empresa = "Esta empresa" if g["es_empresa_propia"] else "Otra empresa"
        for r in g["retiros"]:
            t.fila([g["empleada_nombre"], empresa, _hora(r.timestamp), r.punto_de_venta.nombre,
                    r.variante.codigo_con_verificador, r.precio_lista,
                    r.descuento_aplicado, r.precio_con_descuento])
        t.fila([g["empleada_nombre"], empresa, "", "", "Subtotal a descontar",
                g["subtotal_lista"], "", g["subtotal"]], negrita=True)
    t.fila(["Total", "", "", "", "", datos["total_lista"], "", datos["total"]], negrita=True)
    return t.xls("Retiros de mercadería",
                 ["Empleada", "Empresa", "Hora", "Local", "Código",
                  "Precio lista", "% desc.", "A descontar"],
                 montos=[5, 6, 7], anchos=[28, 14, 8, 22, 22, 14, 10, 14])
