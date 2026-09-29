"""
Modelo de `senas`.

Una seña es plata que el cliente ya entregó y todavía no gastó. Por eso
tiene dos importes y no uno: `monto` es lo que entregó —que no cambia
nunca, es el hecho— y `saldo` es lo que le queda por usar.

Es la única excepción de este módulo a "los campos calculables no se
persisten" (Principio 4), y está justificada: el saldo se consulta en cada
venta del cliente y se descuenta dentro de la transacción que la confirma.
Recalcularlo sumando pagos en cada lectura convertiría la pantalla de cobro
—la más caliente del sistema— en un agregado sobre todo el historial. El
detalle de en qué se usó igual queda: cada uso deja su fila en
`venta_pagos` apuntando a la seña.

Uso total: una seña se gasta entera en una sola venta. Si la compra es por
menos, la diferencia se pierde (el saldo queda en 0 igual). Lo que se
descontó queda en `venta_pagos.sena_consumido`, para que la anulación la
devuelva completa.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.cliente import Cliente
    from app.models.medio_pago import MedioDePago
    from app.models.punto_de_venta import PuntoDeVenta
    from app.models.turno import Turno
    from app.models.usuario import Usuario


class Sena(Base):
    __tablename__ = "senas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Obligatorio: una seña sin cliente sería plata de nadie, y al cobrar no
    # habría forma de saber a quién ofrecérsela.
    cliente_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clientes.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    saldo: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)

    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # Con qué pagó el cliente, en qué turno y en qué local: la plata de la
    # seña entra a la caja ese día y el arqueo la suma a ese medio. NULL solo
    # en las señas registradas antes de la migración 0040, que no entraban
    # a la caja.
    medio_de_pago_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("medios_de_pago.id", ondelete="RESTRICT"), nullable=True
    )
    turno_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("turnos.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    punto_de_venta_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # Se persiste aunque sea "alta + vigencia" (Principio 4): la vigencia es
    # configurable, y cambiarla no tiene que alargar ni acortar las señas que
    # el cliente ya dejó con otra regla.
    vence_el: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Se apaga sola cuando el saldo llega a 0. Una seña gastada no se ofrece
    # más al cobrar, pero sigue explicando las ventas donde se usó.
    activo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    cliente: Mapped["Cliente"] = relationship()  # noqa: F821
    usuario: Mapped["Usuario"] = relationship()  # noqa: F821
    medio_de_pago: Mapped["MedioDePago | None"] = relationship()  # noqa: F821
    turno: Mapped["Turno | None"] = relationship()  # noqa: F821
    punto_de_venta: Mapped["PuntoDeVenta | None"] = relationship()  # noqa: F821

    __table_args__ = (
        CheckConstraint("monto > 0", name="ck_senas_monto_positivo"),
        # El saldo no puede pasarse del monto entregado ni quedar negativo:
        # las dos cosas significarían haber usado plata que no existe. Es la
        # última barrera —el service valida antes y con mejor mensaje—, pero
        # si un camino nuevo se olvidara, la base no lo deja pasar igual.
        CheckConstraint("saldo >= 0 AND saldo <= monto", name="ck_senas_saldo_en_rango"),
    )

    @property
    def usado(self) -> Decimal:
        """Cuánto de la seña ya se aplicó a ventas."""
        return Decimal(self.monto) - Decimal(self.saldo)

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<Sena {self.id} cliente={self.cliente_id} saldo={self.saldo}>"
