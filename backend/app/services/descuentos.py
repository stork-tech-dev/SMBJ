"""
Reglas de descuento de la venta.

Tres reglas gobiernan todo este archivo y ninguna es negociable:

1. **La vendedora elige de una lista, no escribe.** Los porcentajes van de 5
   en 5 hasta 50. Un campo libre convierte cada venta en una negociación y
   hace que el reporte de descuentos no signifique nada.

2. **El tope se controla SUMANDO, el precio se calcula ENCADENANDO.** Son
   dos cuentas distintas a propósito. Sumar 30% + 30% da 60% y se rechaza
   por pasarse del tope; encadenarlos da 51% de descuento real. Si el tope
   se controlara encadenando, un 30+30 pasaría el filtro de "menos de 50" y
   terminaría descontando más de la mitad.

3. **Todo con `Decimal`.** Nunca `float`: 0.1 + 0.2 no da 0.3, y acá cada
   centavo termina en una caja que alguien tiene que cuadrar a fin del día.

El orden de encadenado es el de CLAUDE.md —producto → categoría/material/
proveedor → venta → cliente → empleada—, que en esta venta se reduce a
producto → venta: las demás capas se modelan como motivos de descuento, no
como niveles separados.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.utils import (
    ahora_db,
    normalizar_texto,
    redondear_hacia_abajo,
    sin_tildes,
    sin_tildes_sql,
)
from app.models.usuario import Usuario
from app.models.venta import MotivoDescuento
from app.services.roles import NoEncontrado, ReglaDeNegocio

# Lo único que la vendedora puede elegir. De 5 en 5 y hasta 50: la lista es
# la interfaz, no una validación defensiva sobre un campo libre.
PORCENTAJES_VALIDOS: tuple[int, ...] = (5, 10, 15, 20, 25, 30, 35, 40, 45, 50)

# Tope por producto, sumando TODAS las capas de descuento que le caen encima.
TOPE_DESCUENTO = Decimal("50")

_CIEN = Decimal("100")


def pct(valor: Decimal | int) -> str:
    """
    Un porcentaje escrito como lo escribiría una persona: "50", no "5E+1".

    Hacen falta los dos pasos. `normalize()` saca los ceros sobrantes
    —"40.00" queda en "40"— pero devuelve notación científica para los
    múltiplos de 10, que son justo los valores de la lista de descuentos:
    el tope salía impreso como "5E+1%". El formato `f` la deshace.
    """
    return format(Decimal(str(valor)).normalize(), "f")


def validar_porcentaje(porcentaje: Decimal | int) -> Decimal:
    """
    Acepta el porcentaje solo si está en la lista. Devuelve el Decimal ya
    normalizado, para que quien llame no tenga que convertirlo de nuevo.

    Rechaza un 7%, un 12,5% y un 55% por el mismo motivo: no están en la
    lista que la vendedora ve. Que el 55% además se pase del tope es
    secundario — el punto es que no se puede escribir un número.
    """
    valor = Decimal(str(porcentaje))
    if valor not in (Decimal(p) for p in PORCENTAJES_VALIDOS):
        opciones = ", ".join(f"{p}%" for p in PORCENTAJES_VALIDOS)
        raise ReglaDeNegocio(
            f"El descuento tiene que ser uno de la lista ({opciones}); "
            f"{pct(valor)}% no está entre esos valores"
        )
    return valor


def validar_tope(descuento_producto: Decimal, descuento_venta: Decimal) -> None:
    """
    Control del tope: la SUMA DIRECTA de los porcentajes no puede pasar de 50.

    Suma y no encadenado, aunque el precio se calcule encadenando. Es
    deliberado y es lo que hace que el tope sea un tope: con encadenado,
    30% + 30% daría 51% "efectivo" y quedaría por debajo del límite de 50 en
    la cuenta que se controla, cuando en la práctica el cliente se llevó el
    producto a menos de la mitad.
    """
    total = Decimal(descuento_producto) + Decimal(descuento_venta)
    if total > TOPE_DESCUENTO:
        raise ReglaDeNegocio(
            f"El descuento total no puede superar el {pct(TOPE_DESCUENTO)}% por producto: "
            f"{pct(descuento_producto)}% del producto más {pct(descuento_venta)}% "
            f"de la venta suman {pct(total)}%"
        )


def calcular_descuento_total(
    descuento_producto: Decimal, descuento_venta: Decimal
) -> Decimal:
    """
    El descuento EFECTIVO que resulta de encadenar las dos capas, en
    porcentaje.

    Es el número que se muestra ("35% off") y con el que se explica la
    diferencia entre el precio de lista y el cobrado. NO es el que se compara
    contra el tope: para eso está `validar_tope()`, que suma.

        1 - (1 - dp) × (1 - dv)

    Con 30% y 20% da 44%, no 50%: encadenar siempre descuenta menos que
    sumar, porque la segunda capa se aplica sobre lo que quedó.
    """
    factor = _factor(descuento_producto) * _factor(descuento_venta)
    return (Decimal(1) - factor) * _CIEN


def _factor(porcentaje: Decimal) -> Decimal:
    """La parte del precio que SOBREVIVE a un descuento: 20% → 0.80."""
    return (_CIEN - Decimal(porcentaje)) / _CIEN


def aplicar_descuentos(
    precio_base: Decimal,
    descuento_producto: Decimal,
    descuento_venta: Decimal,
    redondeo: Decimal,
) -> Decimal:
    """
    El precio que se cobra por una unidad, encadenando las dos capas.

    Es el paso 2 de la fórmula de precios del sistema. El paso 1 —pasar de
    dólares a pesos redondeando hacia ARRIBA— ya ocurrió al cargar el
    producto y quedó guardado en `precio_venta`; acá solo se descuenta.

    El redondeo va hacia ABAJO, al revés que el del paso 1, y por el mismo
    motivo de fondo: el redondeo no puede jugar en contra de quien está del
    otro lado. En el paso 1 eso significa que el precio no baje; acá, que el
    descuento prometido se cumpla y no quede en un 19,6%.

    No valida el tope: eso lo hace `aplicar_descuento_item()` antes de tocar
    nada. Esta función es la cuenta, no la regla.
    """
    bruto = Decimal(precio_base) * _factor(descuento_producto) * _factor(descuento_venta)
    final = redondear_hacia_abajo(bruto, redondeo)

    # El redondeo hacia abajo sobre un precio chico puede llevarlo a cero:
    # con múltiplo 100, un producto de $80 al 50% da $40 y el FLOOR lo deja
    # en $0. Regalar el producto no es lo que pidió nadie, así que el piso es
    # un múltiplo, no cero.
    if final <= 0:
        return min(Decimal(redondeo), Decimal(precio_base)) if redondeo > 0 else bruto
    return final


def obtener_motivo(db: Session, motivo_id: int) -> MotivoDescuento:
    motivo = db.get(MotivoDescuento, motivo_id)
    if motivo is None:
        raise NoEncontrado("Motivo de descuento inexistente")
    return motivo


def resolver_porcentaje(
    motivo: MotivoDescuento, porcentaje: Decimal | int | None
) -> tuple[Decimal, bool]:
    """
    Qué porcentaje se aplica y si la vendedora se apartó del sugerido.

    El motivo se elige PRIMERO —es obligatorio antes que el porcentaje— y si
    trae `porcentaje_sugerido`, ese viene preseleccionado. Que ella pueda
    cambiarlo no es un agujero: es el caso "hoy hacemos 30 en vez de 20". Lo
    que no puede es no dejar rastro, y de eso se ocupa el segundo valor que
    devuelve esta función, que termina en `venta_items.porcentaje_modificado`.

    Un motivo sin sugerido obliga a elegir: no hay un default razonable que
    inventar.
    """
    if not motivo.activo:
        raise ReglaDeNegocio(
            f"El motivo '{motivo.nombre}' está inactivo: no se puede usar en "
            "un descuento nuevo"
        )

    if porcentaje is None:
        if motivo.porcentaje_sugerido is None:
            raise ReglaDeNegocio(
                f"El motivo '{motivo.nombre}' no tiene un porcentaje sugerido: "
                "hay que elegir uno de la lista"
            )
        # El sugerido igual pasa por la lista: un motivo cargado con 12% sería
        # un porcentaje libre entrando por la puerta de atrás.
        return validar_porcentaje(motivo.porcentaje_sugerido), False

    elegido = validar_porcentaje(porcentaje)
    modificado = (
        motivo.porcentaje_sugerido is not None
        and elegido != Decimal(motivo.porcentaje_sugerido)
    )
    return elegido, modificado


# ============================================================================
# ABM DEL CATÁLOGO DE MOTIVOS
# ============================================================================


def listar_motivos(
    db: Session,
    nombre: str | None = None,
    activo: bool | None = None,
    habilita_cuotas_sin_interes: bool | None = None,
) -> list[MotivoDescuento]:
    """El catálogo con los filtros del Principio 5. Tabla chica: sin paginar."""
    consulta = select(MotivoDescuento)

    if nombre:
        consulta = consulta.where(
            sin_tildes_sql(MotivoDescuento.nombre).ilike(f"%{sin_tildes(nombre)}%")
        )
    if activo is not None:
        consulta = consulta.where(MotivoDescuento.activo.is_(activo))
    if habilita_cuotas_sin_interes is not None:
        consulta = consulta.where(
            MotivoDescuento.habilita_cuotas_sin_interes.is_(habilita_cuotas_sin_interes)
        )

    return list(db.execute(consulta.order_by(MotivoDescuento.nombre)).scalars().all())


def _validar_nombre_unico(db: Session, nombre: str, excluir_id: int | None = None) -> None:
    """
    Dos motivos con el mismo nombre partirían en dos el reporte de
    descuentos, y al elegir en la lista no habría forma de saber cuál es
    cuál. El UNIQUE de la base también lo impide; esto da el mensaje.
    """
    consulta = select(MotivoDescuento.id).where(
        func.lower(MotivoDescuento.nombre) == nombre.lower()
    )
    if excluir_id is not None:
        consulta = consulta.where(MotivoDescuento.id != excluir_id)
    if db.execute(consulta).scalar_one_or_none():
        raise ReglaDeNegocio(f"Ya existe un motivo de descuento '{nombre}'")


def crear_motivo(
    db: Session,
    autor: Usuario,
    *,
    nombre: str,
    porcentaje_sugerido: Decimal | None = None,
    habilita_cuotas_sin_interes: bool = False,
    ip_origen: str | None = None,
) -> MotivoDescuento:
    limpio = normalizar_texto(nombre)
    if not limpio:
        raise ReglaDeNegocio("El nombre del motivo es obligatorio")
    _validar_nombre_unico(db, limpio)

    # El sugerido pasa por la MISMA lista que la vendedora: un motivo
    # cargado con 12% sería un porcentaje libre entrando por la puerta de
    # atrás, preseleccionado y sin que nadie lo hubiera elegido.
    sugerido = None if porcentaje_sugerido is None else validar_porcentaje(porcentaje_sugerido)

    motivo = MotivoDescuento(
        nombre=limpio,
        porcentaje_sugerido=sugerido,
        habilita_cuotas_sin_interes=habilita_cuotas_sin_interes,
        activo=True,
        created_at=ahora_db(),
    )
    db.add(motivo)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="motivo_descuento.crear",
        entidad="motivos_descuento",
        entidad_id=motivo.id,
        estado_nuevo=motivo,
        ip_origen=ip_origen,
    )
    return motivo


def editar_motivo(
    db: Session,
    autor: Usuario,
    motivo_id: int,
    *,
    nombre: str | None = None,
    porcentaje_sugerido: Decimal | None = None,
    editar_sugerido: bool = False,
    habilita_cuotas_sin_interes: bool | None = None,
    activo: bool | None = None,
    ip_origen: str | None = None,
) -> MotivoDescuento:
    """
    Edita el motivo.

    `editar_sugerido` distingue "no lo mandes" de "sacalo": None es ambiguo
    y acá NULL significa algo concreto —que la vendedora elija el porcentaje
    de la lista, sin preselección—, igual que `editar_precio` en productos.

    Las ventas ya hechas no se tocan: `venta_items` guardó el porcentaje
    aplicado, no una referencia al sugerido de hoy.
    """
    motivo = obtener_motivo(db, motivo_id)
    antes = snapshot(motivo)

    if nombre is not None:
        limpio = normalizar_texto(nombre)
        if not limpio:
            raise ReglaDeNegocio("El nombre del motivo es obligatorio")
        _validar_nombre_unico(db, limpio, excluir_id=motivo.id)
        motivo.nombre = limpio

    if editar_sugerido:
        motivo.porcentaje_sugerido = (
            None if porcentaje_sugerido is None else validar_porcentaje(porcentaje_sugerido)
        )

    if habilita_cuotas_sin_interes is not None:
        motivo.habilita_cuotas_sin_interes = habilita_cuotas_sin_interes

    if activo is not None:
        motivo.activo = activo

    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="motivo_descuento.editar",
        entidad="motivos_descuento",
        entidad_id=motivo.id,
        estado_anterior=antes,
        estado_nuevo=motivo,
        ip_origen=ip_origen,
    )
    return motivo


def cambiar_estado_motivo(
    db: Session, autor: Usuario, motivo_id: int, activo: bool, ip_origen: str | None = None
) -> MotivoDescuento:
    """
    Prende o apaga un motivo. No hay borrado: los ítems con descuento lo
    apuntan, y borrarlo dejaría descuentos sin explicación.
    """
    motivo = obtener_motivo(db, motivo_id)
    antes = snapshot(motivo)

    motivo.activo = activo
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="motivo_descuento.activar" if activo else "motivo_descuento.desactivar",
        entidad="motivos_descuento",
        entidad_id=motivo.id,
        estado_anterior=antes,
        estado_nuevo=motivo,
        ip_origen=ip_origen,
    )
    return motivo
