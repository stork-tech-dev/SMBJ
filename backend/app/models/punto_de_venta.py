"""
Modelo de `puntos_de_venta`.

Ubicaciones donde existe stock y desde donde operan los usuarios: el Centro
de Distribución (único), los locales físicos y las tiendas online. Es
prerequisito de stock, remitos y dispositivos.
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.dispositivo import Dispositivo


class TipoPuntoVenta(str, enum.Enum):
    CD = "cd"
    LOCAL = "local"
    ONLINE = "online"


class PuntoDeVenta(Base):
    __tablename__ = "puntos_de_venta"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False, index=True)

    tipo: Mapped[TipoPuntoVenta] = mapped_column(
        Enum(TipoPuntoVenta, name="tipo_punto_venta", values_callable=lambda e: [i.value for i in e]),
        nullable=False,
        index=True,
    )

    # Código de 4 dígitos con el que un local confirma la recepción de un
    # envío del CD. Solo tiene sentido en los locales; NULL en CD y online.
    codigo_confirmacion: Mapped[str | None] = mapped_column(String(4), nullable=True)

    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    dispositivos: Mapped[list["Dispositivo"]] = relationship(back_populates="punto_de_venta")

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<PuntoDeVenta {self.id} {self.nombre} ({self.tipo.value})>"
