"""
PDF del comprobante de una seña: el papel que se le manda al cliente.

Se arma en cada descarga y no se guarda en disco, como la auditoría y al
revés que el remito. Lo que muestra —monto, medio, vencimiento, nota, fecha
y quién la registró— queda fijo en la fila de `senas` al darla de alta, así
que rearmarlo devuelve el mismo comprobante. Guardar una copia sería tener
el dato en dos lados (Principio 4).
"""

from sqlalchemy.orm import Session

from app.core.utils import ahora_db
from app.reports.pdf import imprimir
from app.services import configuracion as servicio_configuracion


def generar_pdf_sena(db: Session, sena) -> bytes:
    """El PDF en bytes, listo para mandar al navegador."""
    return imprimir(
        "reports/sena.html",
        sena=sena,
        # La letra de la empresa decide el logo, igual que en las pantallas:
        # el mismo sistema atiende a Soleil y a Mallorca.
        letra_empresa=servicio_configuracion.letra_empresa(db),
        emitido=ahora_db(),
    )
