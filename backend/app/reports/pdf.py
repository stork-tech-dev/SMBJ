"""
Motor común de los documentos imprimibles: Jinja2 arma el HTML y WeasyPrint
lo convierte en PDF.

Vive acá y no en cada reporte porque todo lo de abajo —la hoja de estilos de
marca, el silenciado de los logs, el import demorado de WeasyPrint— es igual
para el remito y para la auditoría, y lo será para el próximo (Principio 2).
Lo que cambia de un documento a otro es la plantilla y sus datos.
"""

import logging
from pathlib import Path

from app.core.templates import templates

# La hoja de estilos de la aplicación. Los PDF la cargan por los COLORES: las
# variables de marca viven ahí (`:root` es Mallorca, `[data-empresa="S"]`
# redefine para Soleil), así que los documentos salen con la paleta de la
# empresa instalada sin repetir un solo hexadecimal. El layout de cada
# documento es propio y va en su plantilla.
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

    Sin esto, cada documento generado escupe cien líneas de log que tapan
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


def imprimir(plantilla: str, **contexto) -> bytes:
    """
    Devuelve el PDF de una plantilla de `templates/reports/`, en bytes.

    Bytes y no un archivo: quién los guarda —o si los guarda— es decisión de
    cada documento. El remito se escribe en disco porque el papel que viajó
    con la carga tiene que poder reimprimirse igual; la auditoría se manda
    derecho al navegador porque es un reporte de datos que ya están en la
    base.
    """
    html = templates.get_template(plantilla).render(**contexto)

    # Import local: WeasyPrint carga librerías nativas al importarse (Pango,
    # cairo) y tarda. Adentro de la función, el arranque de la aplicación no
    # lo paga — solo lo paga el primer documento.
    from weasyprint import CSS, HTML

    _silenciar_ruido_de_impresion()

    return HTML(string=html).write_pdf(stylesheets=[CSS(filename=str(_PALETA))])
