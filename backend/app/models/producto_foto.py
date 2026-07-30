"""
Modelo de `producto_fotos`.

Hasta 5 fotos por producto, una de ellas marcada como principal (la que se
muestra en el listado y en el punto de venta). El tope y la unicidad de la
principal se validan en `/services`: son reglas de negocio, no de forma.
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
    from app.models.producto import Producto

# Tope por producto. Vive acá para que modelo, service y tests hablen del mismo.
MAX_FOTOS_POR_PRODUCTO = 5


class ProductoFoto(Base):
    __tablename__ = "producto_fotos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    producto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("productos.id", ondelete="CASCADE"), nullable=False, index=True
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

    __table_args__ = (
        CheckConstraint("orden >= 0", name="ck_producto_fotos_orden_no_negativo"),
        # Una sola principal por producto, garantizado por la base y no solo
        # por el service. El índice es PARCIAL: solo alcanza a las filas con
        # es_principal = true, así las secundarias no compiten entre sí (si
        # no fuera parcial, un producto no podría tener dos fotos comunes).
        Index(
            "uq_producto_fotos_una_principal",
            "producto_id",
            unique=True,
            postgresql_where=text("es_principal"),
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<ProductoFoto {self.id} p={self.producto_id}{' principal' if self.es_principal else ''}>"
