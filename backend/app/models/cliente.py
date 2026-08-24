"""
Modelos de `clientes` y `puntos_cliente`.

El cliente es opcional en la venta: en el mostrador la mayoría compra sin
identificarse y obligar a cargarlo frenaría la caja. Existe para lo que sí
necesita un nombre atrás — los puntos, las señas y las promociones
asignadas.

El SALDO de puntos no es una columna. Se calcula sumando `puntos_cliente`,
que es append-only: cada acumulación, canje y ajuste queda como una fila y
nunca se edita. Un saldo persistido sería un segundo número que puede
quedar viejo, y el historial es justamente lo que permite explicarlo
(Principio 4).
"""

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TipoPunto(str, enum.Enum):
    """Por qué se movieron los puntos de un cliente."""

    ACUMULACION = "acumulacion"  # los sumó una venta
    CANJE = "canje"              # los usó
    AJUSTE = "ajuste"            # corrección manual, con motivo escrito


def _enum(tipo, nombre):
    """Enum de PostgreSQL que persiste el .value, no el nombre del miembro."""
    return Enum(tipo, name=nombre, values_callable=lambda e: [i.value for i in e])


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    nombre: Mapped[str] = mapped_column(String(150), nullable=False)

    # Campo de negocio único con su propio índice (Principio 4). Es
    # NULLABLE porque hay clientes que se cargan solo con nombre y teléfono
    # —el DNI no siempre se pide—, y en Postgres varios NULL conviven sin
    # violar el UNIQUE, que es justo lo que hace falta acá.
    dni: Mapped[str | None] = mapped_column(String(15), nullable=True, unique=True, index=True)

    domicilio: Mapped[str | None] = mapped_column(String(200), nullable=True)
    codigo_postal: Mapped[str | None] = mapped_column(String(10), nullable=True)
    localidad: Mapped[str | None] = mapped_column(String(100), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)

    activo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<Cliente {self.id} {self.nombre}>"


class PuntoCliente(Base):
    """
    Un movimiento de puntos. APPEND-ONLY: no se edita ni se borra.

    Corregir un movimiento mal cargado se hace con otro de tipo `ajuste` y
    signo contrario, igual que los movimientos de stock. Así el saldo de hoy
    siempre se puede reconstruir sumando la historia, y se puede explicar por
    qué es el que es.

    `cantidad` va con signo —a diferencia de `movimientos_stock`, donde el
    tipo decide— porque acá el mismo tipo puede ir para los dos lados: un
    `ajuste` suma o resta según qué se esté corrigiendo.
    """

    __tablename__ = "puntos_cliente"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    cliente_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("clientes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # NULL cuando es un ajuste manual: no todo movimiento de puntos nace de
    # una venta.
    venta_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ventas.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    tipo: Mapped[TipoPunto] = mapped_column(
        _enum(TipoPunto, "tipo_punto_cliente"), nullable=False, index=True
    )

    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)

    # El motivo del ajuste manual, escrito por quien lo hace. Sin esto un
    # ajuste es un número sin explicación.
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)

    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(), index=True
    )

    cliente: Mapped["Cliente"] = relationship()
    usuario: Mapped["Usuario"] = relationship()  # noqa: F821

    __table_args__ = (
        # Un movimiento de cero puntos no movió nada: sería una fila que dice
        # que algo pasó sin que pasara.
        CheckConstraint("cantidad <> 0", name="ck_puntos_cliente_cantidad_no_cero"),
        # La acumulación suma y el canje resta, siempre. El ajuste es el
        # único que puede ir para cualquier lado.
        CheckConstraint(
            "(tipo = 'acumulacion' AND cantidad > 0)"
            " OR (tipo = 'canje' AND cantidad < 0)"
            " OR tipo = 'ajuste'",
            name="ck_puntos_cliente_signo_segun_tipo",
        ),
        # Un ajuste sin motivo escrito es un número que nadie puede explicar
        # después.
        CheckConstraint(
            "tipo <> 'ajuste' OR descripcion IS NOT NULL",
            name="ck_puntos_cliente_ajuste_con_motivo",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<PuntoCliente {self.id} cliente={self.cliente_id} {self.cantidad:+d}>"


class ClientePromocion(Base):
    """
    Promociones a las que este cliente tiene acceso.

    Existe porque hay promociones que no son del catálogo sino de la
    persona: fidelización, un beneficio pactado. Sin esta tabla la única
    forma de darle una promo a alguien puntual sería activarla para todos.
    """

    __tablename__ = "cliente_promociones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    cliente_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clientes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    promocion_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promociones.id", ondelete="CASCADE"), nullable=False, index=True
    )

    __table_args__ = (
        # Asignar dos veces la misma promo al mismo cliente no significa
        # nada distinto de asignarla una: sin el UNIQUE, la lista de la ficha
        # mostraría la promo repetida.
        UniqueConstraint("cliente_id", "promocion_id", name="uq_cliente_promocion"),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<ClientePromocion cliente={self.cliente_id} promo={self.promocion_id}>"
