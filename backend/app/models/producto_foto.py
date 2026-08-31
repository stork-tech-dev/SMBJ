"""
Modelo de `producto_fotos`.

Hasta 5 fotos por producto (compartidas) y hasta 5 por variante (propias).
Una de cada pool marcada como principal. El tope y la unicidad de la
principal se validan en `/services`: son reglas de negocio, no de forma.

Fallback de visualización: si la variante tiene fotos propias se muestran
esas; si no, se muestran las del producto.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.producto import Producto, Variante

# Tope por pool. Vive acá para que modelo, service y tests hablen del mismo.
MAX_FOTOS_POR_PRODUCTO = 5
MAX_FOTOS_POR_VARIANTE = 5


class ProductoFoto(Base):
    __tablename__ = "producto_fotos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    producto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("productos.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # NULL = foto compartida del producto. Con valor = foto exclusiva de esa
    # variante. El fallback (mostrar las del producto si la variante no tiene
    # propias) lo resuelve el frontend, no el modelo.
    variante_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("producto_variantes.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )

    # Ruta relativa servida por StaticFiles (ej. "/static/productos/ab12.jpg").
    # Relativa y no absoluta: la misma base funciona detrás de cualquier
    # dominio, y mudar el host no invalida las fotos.
    url: Mapped[str] = mapped_column(String(255), nullable=False)

    es_principal: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    orden: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    producto: Mapped["Producto"] = relationship(back_populates="fotos")
    variante: Mapped["Variante | None"] = relationship(back_populates="fotos")

    __table_args__ = (
        CheckConstraint("orden >= 0", name="ck_producto_fotos_orden_no_negativo"),
        # Una sola principal por producto (fotos compartidas, variante_id NULL).
        Index(
            "uq_producto_fotos_principal_producto",
            "producto_id",
            unique=True,
            postgresql_where=text("es_principal AND variante_id IS NULL"),
        ),
        # Una sola principal por variante (fotos propias).
        Index(
            "uq_producto_fotos_principal_variante",
            "variante_id",
            unique=True,
            postgresql_where=text("es_principal AND variante_id IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        v = f" v={self.variante_id}" if self.variante_id else ""
        return f"<ProductoFoto {self.id} p={self.producto_id}{v}{' principal' if self.es_principal else ''}>"
