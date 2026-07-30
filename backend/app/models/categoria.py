"""
Modelo de `categorias`.

Árbol de hasta 5 niveles para clasificar productos. Cada nodo cuelga de su
padre por `parent_id`; los de nivel 1 son las raíces y no tienen padre.

`nivel` está desnormalizado a propósito: se podría deducir recorriendo la
cadena de padres, pero eso obligaría a una consulta recursiva en cada
validación y en cada listado. Se guarda y el service lo mantiene coherente
(es la única forma de escribirlo).
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# Profundidad máxima del árbol. Vive acá y no como número suelto en el
# service para que el modelo, la validación y los tests hablen del mismo.
NIVEL_MAXIMO = 5


class Categoria(Base):
    __tablename__ = "categorias"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    nombre: Mapped[str] = mapped_column(String(150), nullable=False, index=True)

    nivel: Mapped[int] = mapped_column(SmallInteger, nullable=False, index=True)

    # RESTRICT y no CASCADE: borrar un padre no puede llevarse en silencio
    # toda su descendencia, con los productos que cuelguen de ella.
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("categorias.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # Orden entre hermanos. No es único: dos nodos de padres distintos
    # pueden compartir el mismo orden sin ambigüedad.
    orden: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    # remote_side apunta al lado "uno" de la autoreferencia: sin eso
    # SQLAlchemy no puede saber cuál de las dos puntas es el padre.
    padre: Mapped["Categoria | None"] = relationship(
        back_populates="hijos", remote_side="Categoria.id"
    )
    hijos: Mapped[list["Categoria"]] = relationship(
        back_populates="padre", order_by="Categoria.orden, Categoria.nombre"
    )

    __table_args__ = (
        CheckConstraint(
            f"nivel BETWEEN 1 AND {NIVEL_MAXIMO}", name="ck_categorias_nivel_rango"
        ),
        # La regla que define el árbol: solo las raíces no tienen padre.
        # En la base y no solo en el service, para que ningún script ni
        # carga masiva pueda dejar el árbol inconsistente.
        CheckConstraint(
            "(nivel = 1 AND parent_id IS NULL) OR (nivel > 1 AND parent_id IS NOT NULL)",
            name="ck_categorias_raiz_sin_padre",
        ),
        # No puede haber dos hermanos con el mismo nombre. Los nombres sí se
        # repiten entre ramas distintas ("Verano" bajo Calzado y bajo Ropa).
        Index(
            "uq_categorias_hermanos",
            "parent_id",
            "nombre",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<Categoria {self.id} {self.nombre} (nivel {self.nivel})>"
