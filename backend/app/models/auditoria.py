"""
Modelo de la tabla `auditoria` (Principio 3: auditoría inmutable).

La tabla es append-only. La garantía no vive en este modelo sino en la
base de datos: la migración instala un trigger que aborta cualquier
UPDATE o DELETE sobre la tabla, y revoca esos permisos al rol de la app.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Auditoria(Base):
    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # NULL cuando la acción la ejecuta el sistema y no un usuario.
    # Sin FK a usuarios: la auditoría debe sobrevivir aunque el usuario
    # se elimine, y la tabla existe antes que el módulo de usuarios.
    usuario_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)

    # Acción con formato "<entidad>.<verbo>", ej: "producto.editar"
    accion: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    entidad: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entidad_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Solo se completan cuando la acción modifica datos existentes.
    estado_anterior: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    estado_nuevo: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    ip_origen: Mapped[str | None] = mapped_column(String(45), nullable=True)

    # Timestamp en hora del negocio (UTC-03:00). El default de base cubre
    # inserciones hechas por fuera de la aplicación (scripts, seed).
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    __table_args__ = (
        # Índice compuesto para el filtro más frecuente del endpoint
        # GET /api/v1/auditoria: entidad + su id, ordenado por fecha.
        Index("ix_auditoria_entidad_entidad_id", "entidad", "entidad_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<Auditoria {self.id} {self.accion} {self.entidad}:{self.entidad_id}>"
