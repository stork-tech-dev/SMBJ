"""
Modelo de la tabla `motivos_baja`.

Tabla de catálogo mínima (Rotura, Robo, Muestra, Merma). Se crea acá,
en la infraestructura base, porque el seed inicial de la sesión 01 la
necesita; su ABM y su uso real viven en el módulo de stock.
"""

from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MotivoBaja(Base):
    __tablename__ = "motivos_baja"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<MotivoBaja {self.id} {self.nombre}>"
