"""
Modelo de la tabla `roles`.

Los roles son configurables desde la UI. Los 6 roles del sistema
(es_sistema=TRUE) se cargan en el seed, no se pueden eliminar ni renombrar
y se referencian SIEMPRE por `nombre`, nunca por id.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.permiso import RolPermiso
    from app.models.usuario import Usuario


class Rol(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    descripcion: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # TRUE en los 6 roles base: protegidos contra borrado y renombrado.
    es_sistema: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    usuarios: Mapped[list["Usuario"]] = relationship(back_populates="rol")
    permisos: Mapped[list["RolPermiso"]] = relationship(
        back_populates="rol", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<Rol {self.id} {self.nombre}>"
