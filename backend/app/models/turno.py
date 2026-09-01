"""
Modelos de caja: turnos, arqueos, retiros, gift cards y notificaciones.

Un turno es el período de trabajo de un local en un día. Solo puede haber
un turno abierto por local. Si un turno del día anterior quedó sin cerrar,
toda operación del local queda bloqueada hasta cerrarlo (bloqueo duro).

El arqueo compara lo esperado (según venta_pagos del turno) contra lo
declarado por la vendedora. Las columnas `diferencia` son GENERATED ALWAYS AS
en la base de datos: nunca se escriben, solo se leen.
"""

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.medio_pago import MedioDePago
    from app.models.punto_de_venta import PuntoDeVenta
    from app.models.usuario import Usuario
    from app.models.venta import Venta


class EstadoTurno(str, enum.Enum):
    ABIERTO = "abierto"
    CERRADO = "cerrado"


class TipoNotificacion(str, enum.Enum):
    DIFERENCIA_ARQUEO = "diferencia_arqueo"


class Turno(Base):
    __tablename__ = "turnos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    punto_de_venta_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    estado: Mapped[EstadoTurno] = mapped_column(
        Enum(EstadoTurno, name="estado_turno"), nullable=False,
        server_default=EstadoTurno.ABIERTO.value
    )
    efectivo_apertura: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    usuario_apertura_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False
    )
    # NULL hasta que se cierre el turno.
    usuario_cierre_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=True
    )
    fecha_apertura: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    fecha_cierre: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    punto_de_venta: Mapped["PuntoDeVenta"] = relationship(
        "PuntoDeVenta", foreign_keys=[punto_de_venta_id]
    )
    usuario_apertura: Mapped["Usuario"] = relationship(
        "Usuario", foreign_keys=[usuario_apertura_id]
    )
    usuario_cierre: Mapped["Usuario | None"] = relationship(
        "Usuario", foreign_keys=[usuario_cierre_id]
    )
    vendedoras: Mapped[list["TurnoVendedora"]] = relationship(
        "TurnoVendedora", back_populates="turno"
    )
    retiros: Mapped[list["RetiroEfectivo"]] = relationship(
        "RetiroEfectivo", back_populates="turno"
    )
    arqueo: Mapped["Arqueo | None"] = relationship(
        "Arqueo", back_populates="turno", uselist=False
    )


class TurnoVendedora(Base):
    """
    Registro de qué vendedoras participaron en el turno.
    Se inserta al abrir turno (vendedora que abre) y al unirse a uno existente.
    """
    __tablename__ = "turno_vendedoras"
    __table_args__ = (UniqueConstraint("turno_id", "usuario_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    turno_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("turnos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False
    )
    ingreso: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)

    turno: Mapped["Turno"] = relationship("Turno", back_populates="vendedoras")
    usuario: Mapped["Usuario"] = relationship("Usuario", foreign_keys=[usuario_id])


class RetiroEfectivo(Base):
    __tablename__ = "retiros_efectivo"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    turno_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("turnos.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    motivo: Mapped[str] = mapped_column(String, nullable=False)
    # Solo puede autorizar alguien con rol dueño.
    autorizado_por: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False
    )
    realizado_por: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)

    turno: Mapped["Turno"] = relationship("Turno", back_populates="retiros")
    usuario_autoriza: Mapped["Usuario"] = relationship(
        "Usuario", foreign_keys=[autorizado_por]
    )
    usuario_realiza: Mapped["Usuario"] = relationship(
        "Usuario", foreign_keys=[realizado_por]
    )


class MedioPagoArqueoConfig(Base):
    """
    Extiende medios_de_pago con configuración de arqueo.
    Determina si un medio se arquea individualmente, agrupado en terminal,
    o solo es informativo (no suma al total del arqueo).
    """
    __tablename__ = "medios_pago_arqueo_config"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    medio_de_pago_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("medios_de_pago.id", ondelete="CASCADE"),
        nullable=False, unique=True
    )
    # TRUE = se arquea junto con otros medios del mismo grupo (ej: Clover/Payway)
    agrupa_en_terminal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # Nombre del grupo si agrupa_en_terminal=TRUE. NULL si se arquea individual.
    grupo_terminal: Mapped[str | None] = mapped_column(String, nullable=True)
    # TRUE = aparece en arqueo pero no suma al conteo (ej: gift cards virtuales)
    es_informativo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    medio_de_pago: Mapped["MedioDePago"] = relationship(
        "MedioDePago", foreign_keys=[medio_de_pago_id]
    )


class Arqueo(Base):
    """
    Arqueo de cierre de turno. Las columnas `diferencia` son GENERATED ALWAYS AS
    en PostgreSQL: no se escriben nunca desde el ORM, solo se leen.
    """
    __tablename__ = "arqueos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Un turno tiene como mucho un arqueo.
    turno_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("turnos.id", ondelete="RESTRICT"),
        nullable=False, unique=True
    )
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False
    )
    total_esperado: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total_declarado: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # GENERATED ALWAYS AS (total_declarado - total_esperado) STORED
    # Se define solo en la migración; el ORM solo la lee.
    diferencia: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    notificacion_enviada: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    turno: Mapped["Turno"] = relationship("Turno", back_populates="arqueo")
    usuario: Mapped["Usuario"] = relationship("Usuario", foreign_keys=[usuario_id])
    items: Mapped[list["ArqueoItem"]] = relationship("ArqueoItem", back_populates="arqueo")


class ArqueoItem(Base):
    """
    Detalle del arqueo por medio de pago o grupo de terminal.
    La columna `diferencia` también es GENERATED ALWAYS AS.
    """
    __tablename__ = "arqueo_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    arqueo_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("arqueos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Para medios individuales: FK a medios_de_pago. NULL para grupos.
    medio_de_pago_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("medios_de_pago.id", ondelete="RESTRICT"), nullable=True
    )
    # Para grupos de terminal: nombre del grupo. NULL si es individual.
    grupo_terminal: Mapped[str | None] = mapped_column(String, nullable=True)
    monto_esperado: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    monto_declarado: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # GENERATED ALWAYS AS (monto_declarado - monto_esperado) STORED
    diferencia: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # TRUE = solo informativo, no suma al total del arqueo.
    es_informativo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    arqueo: Mapped["Arqueo"] = relationship("Arqueo", back_populates="items")
    medio_de_pago: Mapped["MedioDePago | None"] = relationship(
        "MedioDePago", foreign_keys=[medio_de_pago_id]
    )


class PlataformaGiftCard(Base):
    """
    Plataformas externas de gift cards virtuales (ej: Naranja X, Mercado Pago).
    Configurables por Cuenta Maestra.
    """
    __tablename__ = "plataformas_gift_card"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    usos: Mapped[list["GiftCardVirtualUso"]] = relationship(
        "GiftCardVirtualUso", back_populates="plataforma"
    )


class GiftCardVirtualUso(Base):
    """
    Registro de cada uso de gift card virtual en una venta.
    El saldo restante en la plataforma externa no se registra acá.
    """
    __tablename__ = "gift_cards_virtuales_uso"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    plataforma_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("plataformas_gift_card.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    venta_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ventas.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    # Solo el monto consumido en esta operación.
    monto_consumido: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False
    )

    plataforma: Mapped["PlataformaGiftCard"] = relationship(
        "PlataformaGiftCard", back_populates="usos"
    )
    venta: Mapped["Venta"] = relationship("Venta", foreign_keys=[venta_id])
    usuario: Mapped["Usuario"] = relationship("Usuario", foreign_keys=[usuario_id])


class Notificacion(Base):
    """
    Notificaciones para usuarios Dueño.
    Se genera una fila por cada Dueño cuando el arqueo tiene diferencia != 0.
    """
    __tablename__ = "notificaciones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Destinatario (un registro por Dueño).
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    tipo: Mapped[TipoNotificacion] = mapped_column(
        Enum(TipoNotificacion, name="tipo_notificacion"), nullable=False
    )
    titulo: Mapped[str] = mapped_column(String, nullable=False)
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False)
    leida: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # JSON estructurado: turno_id, diferencia, punto_de_venta, vendedoras, etc.
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    usuario: Mapped["Usuario"] = relationship("Usuario", foreign_keys=[usuario_id])
