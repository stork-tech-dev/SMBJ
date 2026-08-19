"""
PDF de una auditoría de inventario: la planilla de lo contado.

Se arma en cada descarga y no se guarda en disco, al revés que el remito. Los
dos motivos:

1. No hay nada que congelar. `auditoria_items` ya guarda `cantidad_sistema`
   —la foto contra la que se comparó— junto con lo contado, así que rearmar
   el documento dentro de un año devuelve exactamente el mismo papel.
2. Guardar una copia sería tener el mismo dato en dos lados (Principio 4),
   con el archivo pudiendo quedar viejo respecto de la base.

El remito es distinto porque es el papel que VIAJÓ con la mercadería: ese sí
es un documento de un momento, y se reimprime tal cual salió.
"""

from sqlalchemy.orm import Session

from app.core.utils import ahora_db
from app.reports.pdf import imprimir
from app.services import configuracion as servicio_configuracion


def generar_pdf_auditoria(db: Session, auditoria) -> bytes:
    """El PDF en bytes, listo para mandar al navegador."""
    return imprimir(
        "reports/auditoria_inventario.html",
        auditoria=auditoria,
        # La letra de la empresa decide la marca, igual que en las pantallas:
        # el mismo sistema atiende a Soleil y a Mallorca.
        letra_empresa=servicio_configuracion.letra_empresa(db),
        # Cuándo se imprimió ESTA copia. Sirve para ordenar dos impresiones
        # de la misma auditoría, que es lo único que las distingue.
        emitido=ahora_db(),
    )
