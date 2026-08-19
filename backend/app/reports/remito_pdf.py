"""
PDF del remito, el papel que viaja con la mercadería.

Se genera UNA vez, al despachar, y se guarda en disco. No se rearma en cada
descarga a propósito: el remito que acompañó la carga es un documento de ese
momento, y si se reconstruyera con los datos de hoy podría mostrar otros
precios, otro nombre de local o una descripción corregida. Reimprimir tiene
que devolver exactamente el mismo papel.

El HTML se arma con el mismo Jinja2 que las pantallas —una plantilla en
`templates/reports/`— y WeasyPrint lo convierte. Así el diseño del documento
se edita como cualquier otra vista, sin tocar código Python.
"""

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.templates import templates
from app.services import configuracion as servicio_configuracion

# Mismo criterio que las fotos de producto (`producto_fotos.py`): la ruta se
# resuelve desde este archivo y no relativa al CWD, porque una ruta relativa
# que falla lo hace en silencio. El directorio lo sirve el StaticFiles que
# monta main.py.
_DIRECTORIO = Path(__file__).resolve().parents[1] / "static" / "remitos"
_URL_BASE = "/static/remitos"

# La hoja de estilos de la aplicación. El PDF la carga por los COLORES: las
# variables de marca viven ahí (`:root` es Mallorca, `[data-empresa="S"]`
# redefine para Soleil), así que el remito sale con la paleta de la empresa
# instalada sin repetir un solo hexadecimal. El layout del documento es
# propio y va embebido en la plantilla.
_PALETA = Path(__file__).resolve().parents[1] / "static" / "css" / "custom.css"

def _silenciar_ruido_de_impresion() -> None:
    """
    Baja el nivel de los loggers de WeasyPrint y fontTools.

    `custom.css` está escrita para pantalla, así que tiene reglas que un motor
    de impresión no implementa: `box-shadow`, `::-webkit-scrollbar`, media
    queries de puntero. WeasyPrint avisa de cada una, y son avisos correctos
    pero esperados y no accionables: esas reglas no tienen sentido en papel y
    no cambian el documento. fontTools, por su lado, narra en DEBUG cada tabla
    de la tipografía que recorta.

    Sin esto, cada remito generado escupe cien líneas de log que tapan
    cualquier error de verdad.

    Se llama DESPUÉS de importar WeasyPrint, no antes: la librería arma su
    propio logger al importarse y pisaría el nivel que se le ponga acá.
    """
    logging.getLogger("weasyprint").setLevel(logging.ERROR)

    # fontTools le pone nivel a cada sub-logger suyo (`fontTools.subset`,
    # `fontTools.subset.timer`, `fontTools.ttLib.ttFont`), así que bajarle el
    # nivel al padre no alcanza: hay que recorrer los que ya existen.
    for nombre in list(logging.root.manager.loggerDict):
        if nombre == "fontTools" or nombre.startswith("fontTools."):
            logging.getLogger(nombre).setLevel(logging.WARNING)


def generar_pdf_remito(db: Session, remito) -> str:
    """
    Escribe el PDF y devuelve su URL relativa, que es lo que se guarda en
    `remitos.pdf_url`.

    Si el archivo ya existía se sobreescribe: pasa solo si se despacha dos
    veces el mismo remito, que el service no permite, y es preferible a
    dejar dos papeles con el mismo número.
    """
    _DIRECTORIO.mkdir(parents=True, exist_ok=True)

    html = templates.get_template("reports/remito.html").render(
        remito=remito,
        # La letra de la empresa decide el logotipo, igual que en las
        # pantallas: el mismo sistema atiende a Soleil y a Mallorca.
        letra_empresa=servicio_configuracion.letra_empresa(db),
    )

    # Import local: WeasyPrint carga librerías nativas al importarse (Pango,
    # cairo) y tarda. Adentro de la función, el arranque de la aplicación no
    # lo paga — solo lo paga el primer despacho.
    from weasyprint import CSS, HTML

    _silenciar_ruido_de_impresion()

    archivo = _DIRECTORIO / f"{remito.numero}.pdf"
    HTML(string=html).write_pdf(str(archivo), stylesheets=[CSS(filename=str(_PALETA))])

    return f"{_URL_BASE}/{archivo.name}"
