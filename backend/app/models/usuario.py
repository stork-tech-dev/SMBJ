"""Modelos de `usuarios` y `historial_accesos`."""

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.permiso import UsuarioPermiso
    from app.models.punto_de_venta import PuntoDeVenta
    from app.models.rol import Rol


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Identificador de login. Único e indexado por ser campo de negocio.
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)

    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)

    rol_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    # --- Datos personales (opcionales, capas "Nuevo/Editar Usuario") ---

    # Fecha sin hora: no interesa el momento, solo el día. El formato
    # dd/mm/yyyy es de presentación y vive en el frontend (Principio 1).
    fecha_nacimiento: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Teléfono como texto y no como número: conserva ceros a la izquierda,
    # admite el prefijo internacional del diseño y nunca se usa para hacer
    # cuentas. Guardarlo como entero obligaría a migrar la columna.
    celular: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Local donde opera el usuario. ondelete SET NULL: si se elimina el
    # punto de venta el usuario sobrevive y solo queda sin asignación,
    # a diferencia del rol, que es obligatorio y usa RESTRICT.
    local_asignado_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("puntos_de_venta.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # NULL para todos excepto la Cuenta Maestra.
    # NUNCA se expone en un schema Pydantic de respuesta: solo se valida
    # o se resetea mediante endpoints específicos.
    clave_especial_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    # NULL = nunca ingresó. Es la señal de "debe cambiar la contraseña
    # en el primer login" para el usuario que crea el seed.
    ultimo_acceso: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )

    # lazy="joined": el rol se necesita en casi toda validación de permisos,
    # traerlo en la misma query evita el N+1 en los listados.
    rol: Mapped["Rol"] = relationship(back_populates="usuarios", lazy="joined")

    # lazy="joined" por el mismo motivo que el rol: el listado muestra el
    # local de cada usuario y sin esto habría un N+1 por fila.
    local_asignado: Mapped["PuntoDeVenta | None"] = relationship(lazy="joined")
    permisos: Mapped[list["UsuarioPermiso"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan"
    )
    accesos: Mapped[list["HistorialAcceso"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<Usuario {self.id} {self.username}>"


class ResultadoAcceso(str, enum.Enum):
    """Resultado de un intento de login."""

    EXITOSO = "exitoso"
    FALLIDO = "fallido"


class HistorialAcceso(Base):
    """
    Registro de intentos de acceso. Append-only: no hay endpoints de
    edición ni eliminación.

    Es distinto de la tabla `auditoria`: esta responde "¿quién intentó
    entrar y cuándo?", la otra "¿quién cambió qué?".
    """

    __tablename__ = "historial_accesos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(), index=True
    )
    ip_origen: Mapped[str | None] = mapped_column(String(45), nullable=True)
    resultado: Mapped[ResultadoAcceso] = mapped_column(
        Enum(ResultadoAcceso, name="resultado_acceso", values_callable=lambda e: [i.value for i in e]),
        nullable=False,
    )
    # Motivo del fallo cuando aplica: "contraseña incorrecta", "usuario inactivo".
    detalle: Mapped[str | None] = mapped_column(String(255), nullable=True)

    usuario: Mapped["Usuario"] = relationship(back_populates="accesos")

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<HistorialAcceso {self.id} u={self.usuario_id} {self.resultado}>"
