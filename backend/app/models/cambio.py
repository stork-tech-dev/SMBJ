"""
Modelos del módulo de cambios de producto.

Un cambio registra la devolución de uno o más ítems de una venta y la entrega
de productos nuevos al cliente. Hay cuatro tipos con reglas de valuación
distintas — ver services/cambios.py.

`cambio_origenes` son los tickets que trae el cliente: uno o varios códigos
de cambio (ventas o retiros de mercadería) cuyo valor se suma.
`cambio_items_devueltos` y `cambio_items_nuevos` son los dos lados del
intercambio. La diferencia entre sus totales determina si el cliente paga
(diferencia > 0) o si queda a favor (diferencia < 0, que no se devuelve
en dinero).
"""

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.categoria import Categoria
    from app.models.operaciones_caja import RetiroMercaderia
    from app.models.medio_pago import MedioDePago, PlanCuotas
    from app.models.producto import Variante
    from app.models.punto_de_venta import PuntoDeVenta
    from app.models.usuario import Usuario
    from app.models.venta import Venta, VentaItem


class TipoCambio(str, enum.Enum):
    COMUN = "comun"
    PROMOCION = "promocion"
    FALLA = "falla"
    GIFT_CARD_FISICA = "gift_card_fisica"


class EstadoCambio(str, enum.Enum):
    PENDIENTE = "pendiente"
    CONFIRMADO = "confirmado"
    CANCELADO = "cancelado"


class TipoPromo(str, enum.Enum):
    DOS_X_UNO = "dos_x_uno"
    TRES_X_DOS = "tres_x_dos"


class Cambio(Base):
    __tablename__ = "cambios"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    tipo: Mapped[TipoCambio] = mapped_column(
        Enum(TipoCambio, name="tipo_cambio", values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )

    punto_de_venta_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    usuario_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Solo para tipo='falla': quien autorizó el cambio
    autorizador_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=True,
    )

    estado: Mapped[EstadoCambio] = mapped_column(
        Enum(EstadoCambio, name="estado_cambio", values_callable=lambda e: [x.value for x in e]),
        nullable=False,
        server_default="pendiente",
    )

    # positivo: el cliente paga; negativo: a favor del cliente (se pierde)
    diferencia: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default="0"
    )

    # Solo si diferencia > 0
    medio_pago_diferencia_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("medios_de_pago.id", ondelete="RESTRICT"),
        nullable=True,
    )
    plan_cuotas_diferencia_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("planes_cuotas.id", ondelete="RESTRICT"),
        nullable=True,
    )

    # Código generado para los productos nuevos que se lleva el cliente
    codigo_cambio_nuevo: Mapped[str | None] = mapped_column(
        String(8), nullable=True, unique=True
    )

    # Cuántas veces los ítems devueltos ya habían sido cambiados antes
    contador_cambios_previos: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    notas: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    # Los tickets que trae el cliente (ninguno en un cambio por falla).
    origenes: Mapped[list["CambioOrigen"]] = relationship(
        back_populates="cambio", cascade="all, delete-orphan", order_by="CambioOrigen.id"
    )
    punto_de_venta: Mapped["PuntoDeVenta"] = relationship()
    usuario: Mapped["Usuario"] = relationship(foreign_keys=[usuario_id])
    autorizador: Mapped["Usuario | None"] = relationship(foreign_keys=[autorizador_id])
    medio_pago_diferencia: Mapped["MedioDePago | None"] = relationship(
        foreign_keys=[medio_pago_diferencia_id]
    )
    plan_cuotas_diferencia: Mapped["PlanCuotas | None"] = relationship(
        foreign_keys=[plan_cuotas_diferencia_id]
    )

    items_devueltos: Mapped[list["CambioItemDevuelto"]] = relationship(
        back_populates="cambio", cascade="all, delete-orphan"
    )
    items_nuevos: Mapped[list["CambioItemNuevo"]] = relationship(
        back_populates="cambio", cascade="all, delete-orphan"
    )

    @property
    def ventas_origen(self) -> list["Venta"]:
        return [o.venta for o in self.origenes if o.venta is not None]

    @property
    def retiros_origen(self) -> list["RetiroMercaderia"]:
        return [o.retiro_mercaderia for o in self.origenes if o.retiro_mercaderia is not None]


class CambioOrigen(Base):
    """
    Un ticket que el cliente trae al cambio: el código de cambio de una venta
    o el de un retiro de mercadería de empleada. Un cambio puede juntar
    varios —lo devuelto de todos suma— para llevarse algo de más valor.

    Exactamente uno de los dos orígenes por fila, y el mismo ticket no entra
    dos veces en el mismo cambio.
    """

    __tablename__ = "cambio_origenes"
    __table_args__ = (
        CheckConstraint(
            "(venta_id IS NULL) <> (retiro_mercaderia_id IS NULL)",
            name="ck_cambio_origenes_un_origen",
        ),
        UniqueConstraint("cambio_id", "venta_id", name="uq_cambio_origenes_venta"),
        UniqueConstraint(
            "cambio_id", "retiro_mercaderia_id", name="uq_cambio_origenes_retiro"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cambio_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cambios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    venta_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ventas.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # Retiro de mercadería de empleada (sesión 09): se cambia como un cambio
    # común, al precio de lista.
    retiro_mercaderia_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("retiros_mercaderia.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    cambio: Mapped["Cambio"] = relationship(back_populates="origenes")
    venta: Mapped["Venta | None"] = relationship()
    retiro_mercaderia: Mapped["RetiroMercaderia | None"] = relationship()

    @property
    def codigo(self) -> str | None:
        """El código de cambio del ticket."""
        if self.venta is not None:
            return self.venta.codigo_cambio
        return self.retiro_mercaderia.codigo_cambio if self.retiro_mercaderia else None


class CambioItemDevuelto(Base):
    __tablename__ = "cambio_items_devueltos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    cambio_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cambios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # NULL en tipo='falla' (no hay venta original) y en la unidad de un
    # retiro de mercadería, que va en `retiro_mercaderia_id`.
    venta_item_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("venta_items.id", ondelete="RESTRICT"),
        nullable=True,
    )

    # De qué retiro de mercadería es la unidad devuelta: con varios tickets
    # en el cambio, hace falta saber de cuál salió.
    retiro_mercaderia_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("retiros_mercaderia.id", ondelete="RESTRICT"),
        nullable=True,
    )

    variante_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("producto_variantes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Valor reconocido al cliente (calculado según tipo de cambio)
    precio_reconocido: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    en_promocion: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    tipo_promo: Mapped[TipoPromo | None] = mapped_column(
        Enum(TipoPromo, name="tipo_promocion", create_type=False),
        nullable=True,
    )

    # Nivel 1 del árbol de categorías (Material) del producto devuelto
    material_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("categorias.id", ondelete="SET NULL"),
        nullable=True,
    )

    cambio: Mapped["Cambio"] = relationship(back_populates="items_devueltos")
    variante: Mapped["Variante"] = relationship()
    venta_item: Mapped["VentaItem | None"] = relationship()
    material: Mapped["Categoria | None"] = relationship()


class CambioItemNuevo(Base):
    __tablename__ = "cambio_items_nuevos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    cambio_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cambios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    variante_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("producto_variantes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Precio de venta actual al momento del cambio
    precio_actual: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # Nivel 1 del árbol de categorías (Material) del producto nuevo
    material_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("categorias.id", ondelete="SET NULL"),
        nullable=True,
    )

    cambio: Mapped["Cambio"] = relationship(back_populates="items_nuevos")
    variante: Mapped["Variante"] = relationship()
    material: Mapped["Categoria | None"] = relationship()
