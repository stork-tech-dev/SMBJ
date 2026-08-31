"""
Modelos de `remitos` y `remito_items`.

El remito es el papel que viaja con la mercadería y, a la vez, el estado de
una transferencia entre dos ubicaciones. Su `numero` cumple las dos
funciones: identifica el envío y es lo que el local tipea para confirmar la
recepción — lo tiene impreso adelante, así que pedirlo prueba que la
mercadería llegó a destino.
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
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.producto import Variante
    from app.models.punto_de_venta import PuntoDeVenta
    from app.models.usuario import Usuario


class EstadoRemito(str, enum.Enum):
    """
    Dónde está la mercadería.

    `pendiente` ya descontó el stock del origen: la mercadería salió de la
    estantería aunque todavía no haya salido del edificio. Es lo que evita
    que dos envíos comprometan las mismas unidades.
    """

    PENDIENTE = "pendiente"
    EN_CAMINO = "en_camino"
    CONFIRMADO = "confirmado"
    CON_DIFERENCIA = "con_diferencia"


def _enum(tipo, nombre):
    """Enum de PostgreSQL que persiste el .value, no el nombre del miembro."""
    return Enum(tipo, name=nombre, values_callable=lambda e: [i.value for i in e])


class Remito(Base):
    __tablename__ = "remitos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Correlativo generado por el sistema desde una SEQUENCE, con el formato
    # R-000001. Es campo de negocio único, así que lleva su propio índice
    # (Principio 4), y es además el código que se pide al confirmar la
    # recepción.
    numero: Mapped[str] = mapped_column(
        String(12), nullable=False, unique=True, index=True
    )

    punto_venta_origen_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    punto_venta_destino_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    estado: Mapped[EstadoRemito] = mapped_column(
        _enum(EstadoRemito, "estado_remito"),
        nullable=False,
        server_default=EstadoRemito.PENDIENTE.value,
        index=True,
    )

    usuario_envio_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False
    )
    # Se completa al confirmar: hasta entonces nadie lo recibió.
    usuario_recepcion_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT")
    )

    fecha_envio: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    fecha_recepcion: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))

    # Ruta del PDF ya generado. Se guarda para poder reimprimirlo sin volver
    # a armarlo: el remito que viajó con la mercadería tiene que poder
    # reproducirse igual meses después, aunque los precios o los nombres
    # hayan cambiado.
    pdf_url: Mapped[str | None] = mapped_column(String(255))

    notas: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    origen: Mapped["PuntoDeVenta"] = relationship(  # noqa: F821  # type: ignore[name-defined]
        foreign_keys=[punto_venta_origen_id]
    )
    destino: Mapped["PuntoDeVenta"] = relationship(  # noqa: F821  # type: ignore[name-defined]
        foreign_keys=[punto_venta_destino_id]
    )
    usuario_envio: Mapped["Usuario"] = relationship(  # noqa: F821  # type: ignore[name-defined]
        foreign_keys=[usuario_envio_id]
    )
    usuario_recepcion: Mapped["Usuario"] = relationship(  # noqa: F821  # type: ignore[name-defined]
        foreign_keys=[usuario_recepcion_id]
    )
    items: Mapped[list["RemitoItem"]] = relationship(
        back_populates="remito", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        # Un remito de un lugar a sí mismo no mueve nada.
        CheckConstraint(
            "punto_venta_origen_id <> punto_venta_destino_id",
            name="ck_remitos_origen_distinto_destino",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<Remito {self.numero} {self.estado.value}>"


class RemitoItem(Base):
    """
    Una línea del remito: qué variante y cuánta.

    `cantidad_recibida` queda en NULL hasta que alguien confirma. NULL y 0
    no son lo mismo: NULL es "todavía no se contó", 0 es "se contó y no
    llegó nada".
    """

    __tablename__ = "remito_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    remito_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("remitos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variante_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("producto_variantes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    cantidad_enviada: Mapped[int] = mapped_column(Integer, nullable=False)
    cantidad_recibida: Mapped[int | None] = mapped_column(Integer)

    remito: Mapped["Remito"] = relationship(back_populates="items")
    variante: Mapped["Variante"] = relationship()  # noqa: F821  # type: ignore[name-defined]

    __table_args__ = (
        # La misma variante dos veces en un remito serían dos respuestas a
        # "cuántas mandaste de esto".
        UniqueConstraint("remito_id", "variante_id", name="uq_remito_items_variante"),
        CheckConstraint("cantidad_enviada > 0", name="ck_remito_items_enviada_positiva"),
        CheckConstraint(
            "cantidad_recibida IS NULL OR cantidad_recibida >= 0",
            name="ck_remito_items_recibida_no_negativa",
        ),
    )

    @property
    def diferencia(self) -> int | None:
        """Lo que falta (negativo) o sobra (positivo). None si no se contó."""
        if self.cantidad_recibida is None:
            return None
        return self.cantidad_recibida - self.cantidad_enviada

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<RemitoItem remito={self.remito_id} variante={self.variante_id}>"
