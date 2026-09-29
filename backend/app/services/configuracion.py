"""
Acceso a `configuracion_sistema`, la tabla de parámetros globales.

Es una tabla de fila única: la aplicación siempre lee y edita ese registro,
nunca crea filas nuevas.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria
from app.core.utils import ahora_db
from app.models.configuracion import ConfiguracionSistema
from app.services.roles import NoEncontrado, ReglaDeNegocio

# Letra por defecto si la configuración todavía no está cargada (por
# ejemplo, antes de correr el seed): evita romper el render del layout.
LETRA_POR_DEFECTO = "S"

# Mismo criterio que la letra: el default de la columna, por si el seed no corrió.
DIAS_VIGENCIA_SENA_POR_DEFECTO = 60


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


def dias_vigencia_sena(db: Session) -> int:
    """Días que dura una seña desde su alta (se fija en `vence_el` al registrarla)."""
    config = obtener_configuracion(db)
    return config.dias_vigencia_sena if config else DIAS_VIGENCIA_SENA_POR_DEFECTO


def cambiar_dias_vigencia_sena(
    db: Session, autor_id: int, dias: int, ip_origen: str | None = None
) -> ConfiguracionSistema:
    """Cambia la vigencia de las señas. Auditado como cualquier parámetro global."""
    if dias <= 0:
        raise ReglaDeNegocio("La vigencia tiene que ser de al menos un día")
    config = obtener_configuracion(db)
    if config is None:
        raise NoEncontrado("La configuración del sistema no está cargada")

    anterior = {"dias_vigencia_sena": config.dias_vigencia_sena}
    config.dias_vigencia_sena = dias
    config.updated_at = ahora_db()
    config.updated_by = autor_id
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor_id,
        accion="configuracion.vigencia_senas",
        entidad="configuracion_sistema",
        entidad_id=config.id,
        estado_anterior=anterior,
        estado_nuevo={"dias_vigencia_sena": dias},
        ip_origen=ip_origen,
    )
    return config
