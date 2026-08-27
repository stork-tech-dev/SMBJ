"""
Modelos de `compras` y `compra_items`.

Una compra registra la mercadería que llega de un proveedor. Se crea como
borrador (guardado automático), se le agregan ítems a medida que se cargan,
y al cerrarse actualiza el stock y, opcionalmente, los precios.

Solo puede haber UNA compra en borrador por usuario a la vez.
"""

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EstadoCompra(str, enum.Enum):
    BORRADOR = "borrador"
    CERRADA = "cerrada"
    ELIMINADA = "eliminada"


def _enum(tipo, nombre):
    """Enum de PostgreSQL que persiste el .value, no el nombre del miembro."""
    return Enum(tipo, name=nombre, values_callable=lambda e: [i.value for i in e])


class Compra(Base):
    """
    Cabecera de una compra a un proveedor.

    En estado `borrador` es un trabajo en curso del operador: se auto-guarda
    y se puede retomar. Al cerrarse, los ítems generan movimientos de stock
    y, si el precio cambió, actualizan el precio de la variante.
    """

    __tablename__ = "compras"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    proveedor_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("proveedores.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    punto_de_venta_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    estado: Mapped[EstadoCompra] = mapped_column(
        _enum(EstadoCompra, "estado_compra"),
        nullable=False,
        server_default=EstadoCompra.BORRADOR.value,
        index=True,
    )

    # Fecha de la factura/remito del proveedor. Opcional: la llena el operador.
    fecha_compra: Mapped[date | None] = mapped_column(Date)

    # Cuándo se empezó a cargar en el sistema.
    fecha_carga: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    # Se completa al cerrar la compra.
    fecha_cierre: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))

    usuario_carga_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    notas: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    proveedor: Mapped["Proveedor"] = relationship()  # noqa: F821
    punto_de_venta: Mapped["PuntoDeVenta"] = relationship()  # noqa: F821
    usuario_carga: Mapped["Usuario"] = relationship()  # noqa: F821
    items: Mapped[list["CompraItem"]] = relationship(
        back_populates="compra", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<Compra {self.id} {self.estado.value}>"


class CompraItem(Base):
    """
    Una línea de la compra: qué variante, cuánta, y a qué precio.

    `precio_usd_anterior` es NULL cuando el producto se creó durante esta
    compra (no había precio previo). `precio_actualizado` indica si al cerrar
    se debe aplicar el precio nuevo a la variante.
    """

    __tablename__ = "compra_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    compra_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("compras.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variante_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("producto_variantes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)

    # Precio en USD de la variante ANTES de esta compra. NULL = producto nuevo.
    precio_usd_anterior: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    # Precio cargado en esta compra (puede ser igual al anterior).
    precio_usd_nuevo: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )

    precio_actualizado: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    etiquetas_impresas: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    es_producto_nuevo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    compra: Mapped["Compra"] = relationship(back_populates="items")
    variante: Mapped["Variante"] = relationship(lazy="selectin")  # noqa: F821

    __table_args__ = (
        # La misma variante dos veces en una compra serían dos líneas para lo
        # mismo: si llega más, se suma la cantidad en la línea existente.
        UniqueConstraint("compra_id", "variante_id", name="uq_compra_items_variante"),
        CheckConstraint("cantidad > 0", name="ck_compra_items_cantidad_positiva"),
        CheckConstraint(
            "precio_usd_nuevo > 0", name="ck_compra_items_precio_positivo"
        ),
        CheckConstraint(
            "etiquetas_impresas >= 0", name="ck_compra_items_etiquetas_no_negativas"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<CompraItem compra={self.compra_id} variante={self.variante_id}>"
