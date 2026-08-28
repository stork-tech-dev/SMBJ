"""
PDF de etiquetas de código de barras para la impresora Zebra GC420t.

Genera un documento con las etiquetas listas para imprimir. No se guarda en
disco: las etiquetas son efímeras y se pueden regenerar en cualquier momento.

Dos tipos de etiqueta:
  - rectangular: 3,5 cm × 1 cm, tres por renglón.
  - colita:      3,5 cm × 3 cm (1 cm + 2 cm de cola), una por página.
"""

from sqlalchemy.orm import Session

from app.reports.pdf import imprimir
from app.services.productos import barcode_svg_para_etiqueta


def generar_etiquetas(
    db: Session,
    items: list[tuple[int, int]],
    tipo: str,
) -> bytes:
    """
    *items*: lista de ``(variante_id, cantidad)``.
    *tipo*: ``"rectangular"`` o ``"colita"``.

    Devuelve los bytes del PDF.
    """
    # Expandir: cada variante se repite según su cantidad.
    etiquetas: list[dict[str, str]] = []
    for variante_id, cantidad in items:
        svg, codigo = barcode_svg_para_etiqueta(db, variante_id)
        for _ in range(cantidad):
            etiquetas.append({"svg": svg, "codigo": codigo})

    contexto: dict = {"tipo": tipo, "etiquetas": etiquetas}

    if tipo == "rectangular":
        # Agrupar de a 3 por renglón.
        contexto["filas"] = [
            etiquetas[i : i + 3] for i in range(0, len(etiquetas), 3)
        ]

    return imprimir("reports/etiquetas.html", **contexto)
