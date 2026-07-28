"""
Modelo de `sesiones`: refresh tokens emitidos.

Tabla necesaria fuera del modelo de datos del prompt: un JWT es válido
hasta que expira, así que sin un registro del lado del servidor no hay
forma de que `POST /auth/logout` invalide un refresh token. Se guarda
solo el `jti` (identificador del token), nunca el token completo.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Sesion(Base):
    __tablename__ = "sesiones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Claim `jti` del refresh token. Único: un jti = una sesión.
    jti: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    creada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)

    revocada: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    ip_origen: Mapped[str | None] = mapped_column(String(45), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<Sesion {self.id} u={self.usuario_id} revocada={self.revocada}>"
