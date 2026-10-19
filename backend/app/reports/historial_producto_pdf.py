"""
PDF del "Historial del Producto".

Se arma en cada descarga sobre el dict de `services/reportes_producto.py`,
como la auditoría: todo lo que muestra ya está registrado en la base, no hay
nada que congelar (Principio 4).
"""

from sqlalchemy.orm import Session

from app.core.utils import ahora_db
from app.reports.pdf import imprimir
from app.services import configuracion as servicio_configuracion

# Cómo se nombra cada tipo de movimiento, cada campo de precio y cada origen
# de un cambio de dólar. Lo usan el PDF y la pantalla (la ruta se los pasa
# al JS), así un nombre se corrige en un solo lugar (Principio 2).
TIPOS_MOVIMIENTO = {
    "ingreso_proveedor": "Ingreso de proveedor",
    "envio_cd_local": "Envío CD → local",
    "devolucion_local_cd": "Devolución local → CD",
    "venta": "Venta",
    "devolucion_venta": "Devolución de venta",
    "baja": "Baja",
    "ajuste_auditoria": "Ajuste de auditoría",
    "retiro_mercaderia": "Retiro de empleada",
}
CAMPOS_PRECIO = {
    "precio_usd": "Precio USD",
    "precio_venta": "Precio de venta",
    "descuento_producto": "Descuento (%)",
    "dolar_proveedor": "Dólar del proveedor",
}
ORIGENES_DOLAR = {
    "manual": "",
    "masivo_valor": "cambio masivo",
    "masivo_porcentaje": "cambio masivo por %",
    "importacion_excel": "importación de Excel",
}
NOMBRES = {
    "tipos_movimiento": TIPOS_MOVIMIENTO,
    "campos_precio": CAMPOS_PRECIO,
    "origenes_dolar": ORIGENES_DOLAR,
}


def generar_pdf_historial(db: Session, datos: dict) -> bytes:
    """El PDF en bytes, listo para mandar al navegador."""
    return imprimir(
        "reports/historial_producto.html",
        h=datos,
        **NOMBRES,
        letra_empresa=servicio_configuracion.letra_empresa(db),
        emitido=ahora_db(),
    )
