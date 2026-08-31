"""
Modelos de `auditorias_inventario` y `auditoria_items`.

Contar la mercadería que hay en una ubicación y compararla contra lo que
dice el sistema. Al finalizar el conteo se generan automáticamente los
movimientos que ajustan el stock a lo contado.

Es distinta de la tabla `auditoria` del Principio 3, que registra QUIÉN hizo
QUÉ en el sistema. Acá se audita la mercadería; allá, las acciones.
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.categoria import Categoria
    from app.models.producto import Variante
    from app.models.punto_de_venta import PuntoDeVenta
    from app.models.usuario import Usuario


class EstadoAuditoria(str, enum.Enum):
    EN_CURSO = "en_curso"
    CERRADA = "cerrada"


def _enum(tipo, nombre):
    """Enum de PostgreSQL que persiste el .value, no el nombre del miembro."""
    return Enum(tipo, name=nombre, values_callable=lambda e: [i.value for i in e])


class AuditoriaInventario(Base):
    __tablename__ = "auditorias_inventario"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    punto_de_venta_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False
    )

    estado: Mapped[EstadoAuditoria] = mapped_column(
        _enum(EstadoAuditoria, "estado_auditoria_inventario"),
        nullable=False,
        server_default=EstadoAuditoria.EN_CURSO.value,
        index=True,
    )

    # Conteo parcial: contar una categoría entera es realista en una jornada,
    # contar el local completo casi nunca lo es. NULL = se cuenta todo.
    filtro_categoria_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("categorias.id", ondelete="RESTRICT")
    )

    fecha_inicio: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    fecha_fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))

    notas: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    punto_de_venta: Mapped["PuntoDeVenta"] = relationship()  # noqa: F821  # type: ignore[name-defined]
    usuario: Mapped["Usuario"] = relationship(foreign_keys=[usuario_id])  # noqa: F821  # type: ignore[name-defined]
    categoria: Mapped["Categoria"] = relationship()  # noqa: F821  # type: ignore[name-defined]
    items: Mapped[list["AuditoriaItem"]] = relationship(
        back_populates="auditoria", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<AuditoriaInventario {self.id} {self.estado.value}>"


class AuditoriaItem(Base):
    """
    Lo que el sistema creía y lo que había, para una variante.

    `cantidad_sistema` se congela al registrar el ítem: es la foto contra la
    que se comparó. Si se recalculara al aprobar, una venta hecha entre el
    conteo y la aprobación aparecería como un faltante de inventario.
    """

    __tablename__ = "auditoria_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    auditoria_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auditorias_inventario.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variante_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("producto_variantes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    cantidad_sistema: Mapped[int] = mapped_column(Integer, nullable=False)
    cantidad_contada: Mapped[int] = mapped_column(Integer, nullable=False)

    # La calcula el motor, no el código: es la resta que decide si se genera
    # un ajuste, y no puede depender de que todos los caminos se acuerden de
    # hacerla igual. `Computed(persisted=True)` es GENERATED ALWAYS AS …
    # STORED en PostgreSQL.
    diferencia: Mapped[int] = mapped_column(
        Integer,
        Computed("cantidad_contada - cantidad_sistema", persisted=True),
        nullable=False,
    )

    auditoria: Mapped["AuditoriaInventario"] = relationship(back_populates="items")
    variante: Mapped["Variante"] = relationship()  # noqa: F821  # type: ignore[name-defined]

    __table_args__ = (
        # Una variante se cuenta una vez por auditoría: dos filas serían dos
        # conteos distintos del mismo estante.
        UniqueConstraint(
            "auditoria_id", "variante_id", name="uq_auditoria_items_variante"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<AuditoriaItem auditoria={self.auditoria_id} dif={self.diferencia}>"
