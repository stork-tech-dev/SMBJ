"""
Acceso a `configuracion_sistema`, la tabla de parámetros globales.

Es una tabla de fila única: la aplicación siempre lee y edita ese registro,
nunca crea filas nuevas.

Los parámetros que la Cuenta Maestra edita desde "Ajustes" pasan todos por
`actualizar_ajustes()`: una sola puerta que valida, audita y deja el antes y
el después de lo que cambió. Leerlos, cada uno con su función: así quien los
usa no tiene que saber que viven en una tabla ni qué valor tomar si el seed
no corrió.
"""

from decimal import Decimal

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

# Los parámetros editables desde "Ajustes" y su valor si la fila no existe
# (el mismo `server_default` de la columna). La letra de la empresa y el
# método de descuento NO están: no se editan desde la pantalla.
AJUSTES_POR_DEFECTO: dict[str, Decimal | int] = {
    "redondeo": Decimal("1"),
    "descuento_maximo": Decimal("100"),
    "tope_descuento_venta": Decimal("50"),
    "paso_descuento": 5,
    "dias_vigencia_sena": DIAS_VIGENCIA_SENA_POR_DEFECTO,
    "pesos_por_punto": Decimal("1000"),
    "dias_plazo_cambio": 30,
}


def obtener_configuracion(db: Session) -> ConfiguracionSistema | None:
    """Fila única de configuración. None si el seed no corrió todavía."""
    return db.execute(select(ConfiguracionSistema).limit(1)).scalar_one_or_none()


def _ajuste(db: Session, campo: str):
    config = obtener_configuracion(db)
    return getattr(config, campo) if config else AJUSTES_POR_DEFECTO[campo]


def letra_empresa(db: Session) -> str:
    """
    Letra de la empresa que opera: 'S' (Soleil) o 'M' (Mallorca).

    Define qué logotipo se muestra en el sidebar y en el login.
    """
    config = obtener_configuracion(db)
    return config.letra_empresa if config else LETRA_POR_DEFECTO


def dias_vigencia_sena(db: Session) -> int:
    """Días que dura una seña desde su alta (se fija en `vence_el` al registrarla)."""
    return int(_ajuste(db, "dias_vigencia_sena"))


def tope_descuento_venta(db: Session) -> Decimal:
    """Tope de la SUMA del descuento del producto y el de la venta."""
    return Decimal(_ajuste(db, "tope_descuento_venta"))


def porcentajes_descuento(db: Session) -> list[int]:
    """
    Los porcentajes que la vendedora puede elegir: paso, 2·paso, … hasta el
    tope de la venta. Con 5 y 50, la lista de siempre (5, 10, …, 50).
    """
    paso = int(_ajuste(db, "paso_descuento"))
    return list(range(paso, int(tope_descuento_venta(db)) + 1, paso))


def pesos_por_punto(db: Session) -> Decimal:
    """Cuántos pesos de venta valen un punto de cliente."""
    return Decimal(_ajuste(db, "pesos_por_punto"))


def dias_plazo_cambio(db: Session) -> int:
    """Plazo habitual para un cambio; pasado, el sistema avisa."""
    return int(_ajuste(db, "dias_plazo_cambio"))


def ajustes(db: Session) -> dict:
    """Todos los parámetros editables, con su valor actual."""
    return {campo: _ajuste(db, campo) for campo in AJUSTES_POR_DEFECTO}


def _validar(valores: dict) -> None:
    """
    Reglas de los ajustes, sobre los valores COMBINADOS (los nuevos más los
    que no cambian): el paso se compara contra el tope que va a quedar, no
    contra el de antes.
    """
    if valores["redondeo"] <= 0:
        raise ReglaDeNegocio("El redondeo tiene que ser mayor a cero")
    if not 0 <= valores["descuento_maximo"] <= 100:
        raise ReglaDeNegocio("El descuento máximo por producto tiene que estar entre 0% y 100%")
    if not 0 < valores["tope_descuento_venta"] <= 100:
        raise ReglaDeNegocio("El tope de descuento en la venta tiene que estar entre 1% y 100%")
    if valores["paso_descuento"] <= 0:
        raise ReglaDeNegocio("El paso de los porcentajes de descuento tiene que ser mayor a cero")
    if valores["paso_descuento"] > valores["tope_descuento_venta"]:
        raise ReglaDeNegocio(
            f"El paso de descuento ({valores['paso_descuento']}%) no puede superar "
            f"el tope de la venta ({valores['tope_descuento_venta']}%): la lista quedaría vacía"
        )
    if valores["dias_vigencia_sena"] <= 0:
        raise ReglaDeNegocio("La vigencia tiene que ser de al menos un día")
    if valores["pesos_por_punto"] <= 0:
        raise ReglaDeNegocio("Los pesos por punto tienen que ser mayores a cero")
    if valores["dias_plazo_cambio"] <= 0:
        raise ReglaDeNegocio("El plazo de cambio tiene que ser de al menos un día")


def actualizar_ajustes(
    db: Session,
    autor_id: int,
    cambios: dict,
    ip_origen: str | None = None,
    accion: str = "configuracion.ajustes",
) -> ConfiguracionSistema:
    """
    Aplica los ajustes que cambiaron y deja UNA auditoría con el antes y el
    después de esos campos. Los que vienen en None o con el mismo valor se
    ignoran: guardar sin cambios no deja rastro.

    Afecta solo lo que pase desde ahora: las ventas, señas y puntos ya
    registrados guardaron su valor en su momento.
    """
    desconocidos = set(cambios) - set(AJUSTES_POR_DEFECTO)
    if desconocidos:
        raise ReglaDeNegocio(f"Ajustes desconocidos: {', '.join(sorted(desconocidos))}")

    config = obtener_configuracion(db)
    if config is None:
        raise NoEncontrado("La configuración del sistema no está cargada")

    nuevos = {
        campo: valor
        for campo, valor in cambios.items()
        if valor is not None and getattr(config, campo) != valor
    }
    if not nuevos:
        return config

    _validar({**ajustes(db), **nuevos})

    anterior = {campo: getattr(config, campo) for campo in nuevos}
    for campo, valor in nuevos.items():
        setattr(config, campo, valor)
    config.updated_at = ahora_db()
    config.updated_by = autor_id
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor_id,
        accion=accion,
        entidad="configuracion_sistema",
        entidad_id=config.id,
        estado_anterior=anterior,
        estado_nuevo=nuevos,
        ip_origen=ip_origen,
    )
    return config


def cambiar_dias_vigencia_sena(
    db: Session, autor_id: int, dias: int, ip_origen: str | None = None
) -> ConfiguracionSistema:
    """Cambia la vigencia de las señas (endpoint histórico; misma puerta que Ajustes)."""
    return actualizar_ajustes(
        db, autor_id, {"dias_vigencia_sena": dias},
        ip_origen=ip_origen, accion="configuracion.vigencia_senas",
    )
