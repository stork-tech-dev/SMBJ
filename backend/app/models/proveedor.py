"""
Modelos de `proveedores` y `proveedor_dolar_historial`.

Cada proveedor maneja su propio valor de dólar (`dolar_actual`), que es la
base del cálculo del precio de venta de sus productos (módulo 04). Cada
cambio de ese valor queda registrado en el historial append-only.
"""

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.usuario import Usuario


class EstadoProveedor(str, enum.Enum):
    """
    Estado de un proveedor.

    El modelo del prompt trae `activo BOOLEAN`, pero las reglas de negocio
    distinguen dos tipos de baja con permisos distintos —un `desactivado`
    se reactiva libremente, un `inhabilitado` requiere Cuenta Maestra o
    Dueño—, así que un booleano no alcanza y se usa este enum de 3 estados.
    """

    ACTIVO = "activo"
    DESACTIVADO = "desactivado"
    INHABILITADO = "inhabilitado"


class OrigenCambioDolar(str, enum.Enum):
    """De dónde vino un cambio de valor del dólar."""

    MANUAL = "manual"
    MASIVO_VALOR = "masivo_valor"
    MASIVO_PORCENTAJE = "masivo_porcentaje"
    IMPORTACION_EXCEL = "importacion_excel"


def _enum(tipo, nombre):
    """Enum de PostgreSQL que persiste el .value, no el nombre del miembro."""
    return Enum(tipo, name=nombre, values_callable=lambda e: [i.value for i in e])


class Proveedor(Base):
    __tablename__ = "proveedores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    nombre: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    # Dónde está el proveedor. Opcional: al dar de alta suele conocerse la
    # empresa antes que su domicilio. Los largos vienen de cuando estos dos
    # campos eran `contacto` y `direccion` (migración 0023): sobran para un
    # país y una provincia, y achicarlos obligaría a truncar lo ya cargado.
    pais: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provincia: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)

    estado: Mapped[EstadoProveedor] = mapped_column(
        _enum(EstadoProveedor, "estado_proveedor"),
        nullable=False,
        server_default=EstadoProveedor.ACTIVO.value,
        index=True,
    )

    # Valor de dólar vigente del proveedor. No es un campo calculable: se
    # fija a mano y es la fuente del precio de venta de sus productos.
    dolar_actual: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    historial_dolar: Mapped[list["ProveedorDolarHistorial"]] = relationship(
        back_populates="proveedor", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("dolar_actual > 0", name="ck_proveedores_dolar_positivo"),
    )

    @property
    def activo(self) -> bool:
        """Conveniencia: True solo cuando el proveedor está operativo."""
        return self.estado == EstadoProveedor.ACTIVO

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<Proveedor {self.id} {self.nombre} ({self.estado.value})>"


class ProveedorDolarHistorial(Base):
    """
    Registro de cada cambio del valor del dólar de un proveedor.

    Append-only: la migración instala un trigger que bloquea UPDATE y
    DELETE. Es distinto de la tabla `auditoria`: acá se guarda la serie de
    valores para poder reconstruir el precio histórico de un producto.
    """

    __tablename__ = "proveedor_dolar_historial"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proveedor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proveedores.id", ondelete="CASCADE"), nullable=False, index=True
    )

    valor_anterior: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    valor_nuevo: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False
    )
    origen: Mapped[OrigenCambioDolar] = mapped_column(
        _enum(OrigenCambioDolar, "origen_cambio_dolar"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(), index=True
    )

    proveedor: Mapped["Proveedor"] = relationship(back_populates="historial_dolar")
    usuario: Mapped["Usuario"] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return (
            f"<ProveedorDolarHistorial {self.id} prov={self.proveedor_id} "
            f"{self.valor_anterior}->{self.valor_nuevo}>"
        )
