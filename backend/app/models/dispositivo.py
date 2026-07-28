"""
Modelo de `dispositivos`.

Identificación persistente de los celulares corporativos. El identificador
principal es un UUID guardado en una cookie de larga vida; el fingerprint
del navegador es solo un mecanismo secundario de recuperación.
"""

import uuid as uuid_lib
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.punto_de_venta import PuntoDeVenta


class Dispositivo(Base):
    __tablename__ = "dispositivos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Identificador principal. Único e inmutable: nunca se edita desde
    # ningún endpoint. El default de base cubre inserciones externas.
    uuid: Mapped[uuid_lib.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        unique=True,
        index=True,
        server_default=func.gen_random_uuid(),
    )

    # Fingerprint del navegador (FingerprintJS). Solo para recuperar la
    # identidad cuando no hay cookie. Nunca es el identificador principal.
    fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    # Local al que pertenece el celular. NULL hasta que un admin lo asigne.
    # Solo puede apuntar a un punto de venta de tipo 'local'.
    punto_de_venta_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("puntos_de_venta.id", ondelete="SET NULL"), nullable=True, index=True
    )

    descripcion: Mapped[str] = mapped_column(String(150), nullable=False, server_default="Sin asignar")

    # Arranca inactivo: un admin lo activa manualmente tras identificarlo.
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    fecha_alta: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    ultimo_acceso: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    ultima_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    punto_de_venta: Mapped["PuntoDeVenta"] = relationship(back_populates="dispositivos")

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<Dispositivo {self.id} {str(self.uuid)[:8]} activo={self.activo}>"
