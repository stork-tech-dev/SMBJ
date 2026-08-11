"""
Modelos de `rol_permisos` (permisos base por rol) y `usuario_permisos`
(overrides individuales, siempre aditivos).

Ambas tablas tienen la misma forma a propósito: `resolver_permiso()` las
consulta con la misma lógica. `recurso=NULL` significa "el módulo completo".
"""

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.rol import Rol
    from app.models.usuario import Usuario


class _PermisoMixin:
    """Columnas comunes a los dos modelos de permisos (Principio 2: DRY)."""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Valor del Enum Modulo. Se guarda como VARCHAR y no como ENUM de
    # PostgreSQL: agregar un módulo nuevo no debe requerir ALTER TYPE.
    modulo: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Valor del Enum Recurso. NULL = permiso general del módulo.
    recurso: Mapped[str | None] = mapped_column(String(100), nullable=True)

    puede_ver: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    puede_crear: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    puede_editar: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    puede_eliminar: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class RolPermiso(_PermisoMixin, Base):
    __tablename__ = "rol_permisos"

    rol_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )

    rol: Mapped["Rol"] = relationship(back_populates="permisos")

    # Cada rol tiene una fila general por módulo (recurso=NULL) y N filas por
    # recurso.
    #
    # `nulls_not_distinct` es lo que hace que la general tampoco se pueda
    # repetir. Sin eso, PostgreSQL admite múltiples NULL en un UNIQUE —NULL no
    # es igual a NULL—, y ahí se colaron 45 filas duplicadas que rompían el
    # guardado de accesos con un 500. De paso es lo que hace que el
    # `ON CONFLICT ... DO NOTHING` del seed sirva para algo.
    __table_args__ = (
        UniqueConstraint(
            "rol_id",
            "modulo",
            "recurso",
            name="uq_rol_permisos_rol_modulo_recurso",
            postgresql_nulls_not_distinct=True,
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<RolPermiso rol={self.rol_id} {self.modulo}/{self.recurso}>"


class UsuarioPermiso(_PermisoMixin, Base):
    __tablename__ = "usuario_permisos"

    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )

    usuario: Mapped["Usuario"] = relationship(back_populates="permisos")

    # `nulls_not_distinct` por el mismo motivo que en RolPermiso: sin eso, el
    # permiso general de un módulo (recurso=NULL) se puede duplicar.
    __table_args__ = (
        UniqueConstraint(
            "usuario_id",
            "modulo",
            "recurso",
            name="uq_usuario_permisos_usuario_modulo_recurso",
            postgresql_nulls_not_distinct=True,
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<UsuarioPermiso usuario={self.usuario_id} {self.modulo}/{self.recurso}>"
