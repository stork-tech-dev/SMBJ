"""
Modelos de `stock` y `movimientos_stock`.

La regla que gobierna todo el módulo: **el stock nunca se modifica
directamente**. Cada entrada, salida, transferencia o ajuste se inserta en
`movimientos_stock` y ese movimiento actualiza la fila de `stock` en la
MISMA transacción. Si algo falla, no queda ni el movimiento ni el cambio.

Y no existe "stock global": el stock es siempre de una variante EN una
ubicación. Un producto puede tener 12 unidades en Patio Olmos y 0 en el
resto, y esos son dos hechos distintos, no un total de 12.
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    case,
    func,
    literal,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.punto_de_venta import PuntoDeVenta, TipoPuntoVenta

if TYPE_CHECKING:
    from app.models.motivo_baja import MotivoBaja
    from app.models.producto import Variante
    from app.models.usuario import Usuario


class TipoMovimiento(str, enum.Enum):
    """
    Por qué se movió el stock. El tipo es lo que define si el movimiento
    SUMA o RESTA: la cantidad siempre se guarda en positivo, para que un
    signo mal puesto no pueda invertir el sentido de un movimiento.
    """

    INGRESO_PROVEEDOR = "ingreso_proveedor"      # mercadería nueva al CD
    ENVIO_CD_LOCAL = "envio_cd_local"            # transferencia CD → local
    DEVOLUCION_LOCAL_CD = "devolucion_local_cd"  # transferencia local → CD
    VENTA = "venta"                              # descuento por venta
    DEVOLUCION_VENTA = "devolucion_venta"        # reingreso por devolución
    BAJA = "baja"                                # rotura, robo, muestra, merma
    AJUSTE_AUDITORIA = "ajuste_auditoria"        # aprobado por el Dueño
    RETIRO_MERCADERIA = "retiro_mercaderia"      # una empleada se lleva un producto


def _enum(tipo, nombre):
    """Enum de PostgreSQL que persiste el .value, no el nombre del miembro."""
    return Enum(tipo, name=nombre, values_callable=lambda e: [i.value for i in e])


# Mínimo con el que nace toda fila de stock.
MINIMO_POR_DEFECTO = 1

# Qué mínimo rige en cada tipo de ubicación. Las Ubicaciones Especiales no
# están: no son stock vendible, no se reponen y su mínimo es 0 (sin alerta).
COLUMNA_MINIMO = {
    TipoPuntoVenta.CD: "stock_minimo_cd",
    TipoPuntoVenta.ONLINE: "stock_minimo_online",
    TipoPuntoVenta.LOCAL: "stock_minimo_local",
}


class Stock(Base):
    """
    Cuántas unidades de una variante hay en una ubicación.

    Es la ÚNICA verdad sobre el stock: `producto_variantes` no guarda
    cantidad. El listado de productos suma esta tabla, y esa suma es un
    dato derivado que no se persiste (Principio 4).
    """

    __tablename__ = "stock"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    variante_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("producto_variantes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    punto_de_venta_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    cantidad: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Tres mínimos y no uno: el mismo artículo necesita un colchón muy
    # distinto en el CD —que abastece a todos los locales—, en la tienda
    # online y en un local, que solo repone su propia góndola. Cuál aplica lo
    # decide el TIPO del punto de venta (`COLUMNA_MINIMO`), no quien carga el
    # dato. Nacen en 1: todo producto avisa cuando falta en una sucursal.
    stock_minimo_cd: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=str(MINIMO_POR_DEFECTO)
    )
    stock_minimo_local: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=str(MINIMO_POR_DEFECTO)
    )
    stock_minimo_online: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=str(MINIMO_POR_DEFECTO)
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    variante: Mapped["Variante"] = relationship()  # noqa: F821  # type: ignore[name-defined]
    punto_de_venta: Mapped["PuntoDeVenta"] = relationship()  # noqa: F821  # type: ignore[name-defined]

    __table_args__ = (
        # Una sola fila por variante y ubicación: dos filas para el mismo par
        # serían dos respuestas distintas a "cuánto hay".
        UniqueConstraint(
            "variante_id", "punto_de_venta_id", name="uq_stock_variante_punto_de_venta"
        ),
        # El CHECK `cantidad >= 0` estuvo acá hasta la migración 0024 y se
        # fue con la llegada de las ventas. La venta no pide permiso: la
        # vendedora tiene el producto en la mano, y si el sistema dice 0, el
        # que está mal es el sistema. Un negativo es la señal de que ese
        # artículo necesita una auditoría de inventario.
        #
        # La garantía no se perdió, se mudó a `aplicar_movimiento()`, que
        # sigue rechazando el faltante para todo salvo la confirmación de una
        # venta — un remito no puede mandar mercadería que no está.
        CheckConstraint(
            "stock_minimo_cd >= 0 AND stock_minimo_local >= 0 AND stock_minimo_online >= 0",
            name="ck_stock_minimos_no_negativos",
        ),
    )

    @property
    def stock_minimo(self) -> int:
        """
        El mínimo que aplica acá, según el tipo de ubicación.

        La regla vive en el modelo y no en cada consulta: el listado, las
        alertas y el panel del dashboard tienen que coincidir, y si cada uno
        eligiera la columna por su cuenta, alcanzaría con que uno se
        equivocara para avisar de una falta que no existe.
        """
        columna = COLUMNA_MINIMO.get(self.punto_de_venta.tipo)
        return getattr(self, columna) if columna else 0

    @property
    def bajo_minimo(self) -> bool:
        return self.cantidad <= self.stock_minimo

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return (
            f"<Stock variante={self.variante_id} pdv={self.punto_de_venta_id} "
            f"cantidad={self.cantidad}>"
        )



def minimo_aplicable_sql():
    """
    La regla de `Stock.stock_minimo` para usar dentro de una query (necesita
    `PuntoDeVenta` en el FROM). Especiales y cualquier tipo sin mínimo: 0.
    """
    return case(
        *[
            (PuntoDeVenta.tipo == tipo, getattr(Stock, columna))
            for tipo, columna in COLUMNA_MINIMO.items()
        ],
        else_=literal(0),
    )

class MovimientoStock(Base):
    """
    El registro de por qué el stock es el que es.

    Append-only en la práctica: un movimiento no se edita ni se borra: si
    estuvo mal, se corrige con otro movimiento que lo compense. Así el stock
    de hoy siempre se puede reconstruir sumando la historia.

    Las FK opcionales (`remito_id`, `motivo_baja_id`, …) son las que dan el
    contexto de cada tipo. No se juntan en una sola columna polimórfica a
    propósito: cada una tiene su FK real y la base garantiza que apunte a
    algo que existe.
    """

    __tablename__ = "movimientos_stock"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    tipo: Mapped[TipoMovimiento] = mapped_column(
        _enum(TipoMovimiento, "tipo_movimiento_stock"), nullable=False, index=True
    )

    variante_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("producto_variantes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # De dónde sale y a dónde va. En un ingreso del proveedor no hay origen;
    # en una venta o una baja no hay destino. Los dos NULL a la vez no
    # tendrían sentido, y lo ata un CHECK.
    punto_venta_origen_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"), index=True
    )
    punto_venta_destino_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"), index=True
    )

    # Siempre positiva: el TIPO decide si suma o resta.
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)

    remito_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("remitos.id", ondelete="RESTRICT"), index=True
    )
    motivo_baja_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("motivos_baja.id", ondelete="RESTRICT")
    )
    auditoria_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("auditorias_inventario.id", ondelete="RESTRICT")
    )

    compra_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("compras.id", ondelete="RESTRICT"), index=True
    )

    retiro_mercaderia_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("retiros_mercaderia.id", ondelete="RESTRICT"), index=True
    )

    # Sin FK todavía: la tabla `ventas` llega en el módulo 06. La columna se
    # crea ahora porque el tipo `venta` ya existe y el dato hay que poder
    # guardarlo; la restricción se agrega cuando exista a qué apuntar.
    referencia_venta_id: Mapped[int | None] = mapped_column(BigInteger, index=True)

    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(), index=True
    )

    notas: Mapped[str | None] = mapped_column(Text)

    variante: Mapped["Variante"] = relationship()  # noqa: F821  # type: ignore[name-defined]
    origen: Mapped["PuntoDeVenta"] = relationship(  # noqa: F821  # type: ignore[name-defined]
        foreign_keys=[punto_venta_origen_id]
    )
    destino: Mapped["PuntoDeVenta"] = relationship(  # noqa: F821  # type: ignore[name-defined]
        foreign_keys=[punto_venta_destino_id]
    )
    usuario: Mapped["Usuario"] = relationship()  # noqa: F821  # type: ignore[name-defined]
    motivo_baja: Mapped["MotivoBaja"] = relationship()  # noqa: F821  # type: ignore[name-defined]

    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_movimientos_stock_cantidad_positiva"),
        # Un movimiento que no sale de ningún lado ni va a ninguno no movió
        # nada: sería una fila que dice que algo pasó sin decir dónde.
        CheckConstraint(
            "punto_venta_origen_id IS NOT NULL OR punto_venta_destino_id IS NOT NULL",
            name="ck_movimientos_stock_tiene_ubicacion",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<MovimientoStock {self.id} {self.tipo.value} x{self.cantidad}>"
