"""
Modelos de `medios_de_pago` y `planes_cuotas`.

Lo delicado de este módulo son DOS porcentajes que se parecen y significan
cosas opuestas:

  - `recargo_cliente`: lo que se le suma al cliente por financiar. Cambia
    lo que paga.
  - `costo_medio`: lo que la terminal le cobra al comercio. NO cambia lo que
    paga el cliente; existe para los reportes de costo.

Confundirlos es cobrarle de más a alguien o creer que se ganó menos de lo
que se ganó, así que nunca se suman ni se combinan en ningún cálculo. El
service de ventas solo mira `recargo_cliente`.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MedioDePago(Base):
    """
    Con qué se paga: Efectivo, Débito, una tarjeta puntual, Gift Card.

    El catálogo lo administra la Cuenta Maestra. No se borra ninguno: se
    desactiva, porque las ventas viejas lo apuntan y borrarlo dejaría pagos
    sin decir con qué se hicieron.
    """

    __tablename__ = "medios_de_pago"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    nombre: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)

    # Si admite planes. En False el medio se cobra siempre en un pago y la
    # pantalla no ofrece selector de cuotas.
    soporta_cuotas: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    # La seña no es un medio más: descuenta de un saldo que ya se cobró, así
    # que el pago tiene que apuntar a QUÉ seña. La marca vive en el catálogo
    # y no en un nombre reservado ("Seña") porque comparar por texto haría
    # que renombrar el medio rompiera el flujo en silencio.
    es_sena: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    activo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    planes: Mapped[list["PlanCuotas"]] = relationship(
        back_populates="medio_de_pago",
        cascade="all, delete-orphan",
        order_by="PlanCuotas.cuotas",
    )

    __table_args__ = (
        # Una seña se descuenta de un saldo ya cobrado: financiarla en cuotas
        # no significa nada.
        CheckConstraint(
            "NOT (es_sena AND soporta_cuotas)", name="ck_medios_de_pago_sena_sin_cuotas"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<MedioDePago {self.id} {self.nombre}>"


class PlanCuotas(Base):
    """
    Un plan concreto de un medio: "6 cuotas con 15% de recargo desde $50.000".

    `monto_minimo` es lo que hace que la vendedora no tenga que conocer las
    reglas: el sistema le muestra solo los planes que el monto de la venta
    habilita. Con 0 el plan está siempre disponible.
    """

    __tablename__ = "planes_cuotas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    medio_de_pago_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("medios_de_pago.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    cuotas: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # Lo que paga el cliente de más. 0 = sin interés.
    recargo_cliente: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default="0"
    )

    # Lo que cobra la terminal. SOLO para reportes de costo: no entra en
    # ningún cálculo del precio (ver el encabezado del módulo).
    costo_medio: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default="0"
    )

    monto_minimo: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default="0"
    )

    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    medio_de_pago: Mapped["MedioDePago"] = relationship(back_populates="planes")

    __table_args__ = (
        # El mismo medio puede tener "6 cuotas al 0%" y "6 cuotas al 15%"
        # —uno promocional y otro no—, así que la unicidad incluye el
        # recargo. Lo que no puede haber son dos planes idénticos: al elegir
        # en la lista no habría forma de saber cuál se está eligiendo.
        UniqueConstraint(
            "medio_de_pago_id", "cuotas", "recargo_cliente", name="uq_plan_cuotas"
        ),
        CheckConstraint("cuotas >= 1", name="ck_planes_cuotas_cantidad_positiva"),
        CheckConstraint(
            "recargo_cliente >= 0 AND recargo_cliente <= 100",
            name="ck_planes_cuotas_recargo_rango",
        ),
        CheckConstraint(
            "costo_medio >= 0 AND costo_medio <= 100", name="ck_planes_cuotas_costo_rango"
        ),
        CheckConstraint("monto_minimo >= 0", name="ck_planes_cuotas_minimo_no_negativo"),
    )

    def disponible_para(self, monto: Decimal) -> bool:
        """
        Si este plan se le puede ofrecer a una venta de ese monto.

        La regla vive acá y no en la consulta para que la pantalla del punto
        de venta y el service de confirmación decidan igual: si cada uno
        filtrara por su cuenta, se podría ofrecer un plan que después el
        backend rechaza.
        """
        return self.activo and Decimal(monto) >= Decimal(self.monto_minimo)

    @property
    def sin_interes(self) -> bool:
        return Decimal(self.recargo_cliente) == 0

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<PlanCuotas {self.id} {self.cuotas}x {self.recargo_cliente}%>"
