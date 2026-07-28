"""
Acceso a `configuracion_sistema`, la tabla de parámetros globales.

Es una tabla de fila única: la aplicación siempre lee y edita ese registro,
nunca crea filas nuevas.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.configuracion import ConfiguracionSistema

# Letra por defecto si la configuración todavía no está cargada (por
# ejemplo, antes de correr el seed): evita romper el render del layout.
LETRA_POR_DEFECTO = "S"


def obtener_configuracion(db: Session) -> ConfiguracionSistema | None:
    """Fila única de configuración. None si el seed no corrió todavía."""
    return db.execute(select(ConfiguracionSistema).limit(1)).scalar_one_or_none()


def letra_empresa(db: Session) -> str:
    """
    Letra de la empresa que opera: 'S' (Soleil) o 'M' (Mallorca).

    Define qué logotipo se muestra en el sidebar y en el login.
    """
    config = obtener_configuracion(db)
    return config.letra_empresa if config else LETRA_POR_DEFECTO
