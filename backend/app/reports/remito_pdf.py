"""
PDF del remito, el papel que viaja con la mercadería.

Se genera UNA vez, al despachar, y se guarda en disco. No se rearma en cada
descarga a propósito: el remito que acompañó la carga es un documento de ese
momento, y si se reconstruyera con los datos de hoy podría mostrar otros
precios, otro nombre de local o una descripción corregida. Reimprimir tiene
que devolver exactamente el mismo papel.

El HTML se arma con el mismo Jinja2 que las pantallas —una plantilla en
`templates/reports/`— y WeasyPrint lo convierte (`reports/pdf.py`). Así el
diseño del documento se edita como cualquier otra vista, sin tocar código
Python.
"""

from pathlib import Path

from sqlalchemy.orm import Session

from app.reports.pdf import imprimir
from app.services import configuracion as servicio_configuracion

# Mismo criterio que las fotos de producto (`producto_fotos.py`): la ruta se
# resuelve desde este archivo y no relativa al CWD, porque una ruta relativa
# que falla lo hace en silencio. El directorio lo sirve el StaticFiles que
# monta main.py.
_DIRECTORIO = Path(__file__).resolve().parents[1] / "static" / "remitos"
_URL_BASE = "/static/remitos"


def generar_pdf_remito(db: Session, remito) -> str:
    """
    Escribe el PDF y devuelve su URL relativa, que es lo que se guarda en
    `remitos.pdf_url`.

    Si el archivo ya existía se sobreescribe: pasa solo si se despacha dos
    veces el mismo remito, que el service no permite, y es preferible a
    dejar dos papeles con el mismo número.
    """
    _DIRECTORIO.mkdir(parents=True, exist_ok=True)

    pdf = imprimir(
        "reports/remito.html",
        remito=remito,
        # La letra de la empresa decide el logotipo, igual que en las
        # pantallas: el mismo sistema atiende a Soleil y a Mallorca.
        letra_empresa=servicio_configuracion.letra_empresa(db),
    )

    archivo = _DIRECTORIO / f"{remito.numero}.pdf"
    archivo.write_bytes(pdf)

    return f"{_URL_BASE}/{archivo.name}"
