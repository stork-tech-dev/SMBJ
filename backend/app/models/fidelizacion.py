"""
Modelo de `categorias_fidelizacion`.

Una categoría es un rango de puntos: arranca en `puntos_desde` y llega hasta
el `puntos_desde` de la siguiente. El cliente cae en la de mayor umbral que
alcanzan sus puntos acumulados históricos (sin restar canjes: canjear no le
baja la categoría).

La categoría NO se guarda en el cliente (Principio 4): se calcula al
consultarla, así cambiar los rangos en Ajustes reubica a todos al instante
y no hay un campo que se desactualice.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CategoriaFidelizacion(Base):
    __tablename__ = "categorias_fidelizacion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    puntos_desde: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)

    # Descuento que recibe en todas sus compras del mes de su cumpleaños.
    porcentaje_cumpleanos: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("puntos_desde >= 0", name="ck_categorias_fidelizacion_puntos"),
        CheckConstraint(
            "porcentaje_cumpleanos >= 0 AND porcentaje_cumpleanos <= 100",
            name="ck_categorias_fidelizacion_porcentaje",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<CategoriaFidelizacion {self.nombre} desde {self.puntos_desde}>"
