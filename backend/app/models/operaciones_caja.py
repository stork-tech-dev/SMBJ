"""
Operaciones de caja que ocurren durante un turno además de las ventas
(sesión 09): novedades de caja, retiros de mercadería de empleadas y cobros de
joyero. Los retiros de efectivo viven en `models/turno.py` (`RetiroEfectivo`).

Cómo afecta cada una a la caja:
- Novedad de caja: ajusta el efectivo esperado del arqueo (suma o resta).
- Retiro de mercadería: sale stock, NO toca la caja ni el arqueo, NO es venta.
- Cobro de joyero: entra plata al medio de pago elegido, NO es venta.
"""

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
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
    from app.models.medio_pago import MedioDePago
    from app.models.producto import Variante
    from app.models.punto_de_venta import PuntoDeVenta
    from app.models.turno import Turno
    from app.models.usuario import Usuario
    from app.models.venta import MotivoDescuento


class TipoNovedad(str, enum.Enum):
    """Entrada suma al efectivo esperado; salida lo resta."""

    ENTRADA = "entrada"
    SALIDA = "salida"


def _enum_tipo_novedad():
    return Enum(
        TipoNovedad,
        name="tipo_novedad",
        values_callable=lambda e: [i.value for i in e],
        create_type=False,
    )


class ConceptoNovedad(Base):
    """
    Catálogo de novedades de caja ('Pago electricista', 'Falla del sistema').
    El tipo lo define la Cuenta Maestra acá: quien carga la novedad no lo elige.
    """

    __tablename__ = "conceptos_novedad"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    tipo: Mapped[TipoNovedad] = mapped_column(_enum_tipo_novedad(), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<ConceptoNovedad {self.id} {self.nombre} ({self.tipo.value})>"


class NovedadCaja(Base):
    """
    Ajuste legítimo del efectivo esperado, con un responsable que lo autorizó.

    `tipo` se COPIA del concepto al registrar (desnormalización justificada):
    si después alguien cambia el concepto, la novedad ya registrada tiene que
    seguir sumando o restando lo mismo que cuando se cargó.
    """

    __tablename__ = "novedades_caja"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    turno_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("turnos.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    punto_de_venta_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    concepto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conceptos_novedad.id", ondelete="RESTRICT"), nullable=False
    )
    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    tipo: Mapped[TipoNovedad] = mapped_column(_enum_tipo_novedad(), nullable=False)
    autorizador_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False
    )
    registrado_por_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)

    turno: Mapped["Turno"] = relationship()
    punto_de_venta: Mapped["PuntoDeVenta"] = relationship()
    concepto: Mapped["ConceptoNovedad"] = relationship()
    autorizador: Mapped["Usuario"] = relationship(foreign_keys=[autorizador_id])
    registrado_por: Mapped["Usuario"] = relationship(foreign_keys=[registrado_por_id])

    __table_args__ = (
        CheckConstraint("monto > 0", name="ck_novedades_caja_monto_positivo"),
    )


class RetiroMercaderia(Base):
    """
    Una empleada se lleva un producto que se descuenta del sueldo.

    No es venta: no toca la caja, ni el arqueo, ni los reportes de ventas. Sí
    descuenta stock y genera un código de cambio, porque el producto puede ser
    para regalo.

    `precio_lista` es el precio al momento del retiro (desnormalización
    justificada, igual que en `venta_items`): es el valor con el que después se
    reconoce un cambio, y el precio del producto puede cambiar.
    """

    __tablename__ = "retiros_mercaderia"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    turno_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("turnos.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    punto_de_venta_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Empleada de esta empresa: se vincula el usuario. De la otra empresa:
    # NULL, y los datos van a mano en nombre y DNI.
    empleada_usuario_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    empleada_nombre: Mapped[str | None] = mapped_column(String(150), nullable=True)
    empleada_dni: Mapped[str | None] = mapped_column(String(15), nullable=True)
    es_empresa_propia: Mapped[bool] = mapped_column(Boolean, nullable=False)
    variante_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("producto_variantes.id", ondelete="RESTRICT"), nullable=False
    )
    precio_lista: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    motivo_descuento_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("motivos_descuento.id", ondelete="RESTRICT"), nullable=False
    )
    descuento_aplicado: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    # Lo que se descuenta del sueldo.
    precio_con_descuento: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    codigo_cambio: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    registrado_por_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)

    punto_de_venta: Mapped["PuntoDeVenta"] = relationship()
    empleada: Mapped["Usuario | None"] = relationship(foreign_keys=[empleada_usuario_id])
    variante: Mapped["Variante"] = relationship()
    motivo_descuento: Mapped["MotivoDescuento"] = relationship()
    registrado_por: Mapped["Usuario"] = relationship(foreign_keys=[registrado_por_id])

    __table_args__ = (
        CheckConstraint(
            "(es_empresa_propia AND empleada_usuario_id IS NOT NULL)"
            " OR (NOT es_empresa_propia AND empleada_usuario_id IS NULL"
            " AND empleada_nombre IS NOT NULL)",
            name="ck_retiros_mercaderia_empleada",
        ),
        CheckConstraint(
            "precio_lista >= 0 AND precio_con_descuento >= 0",
            name="ck_retiros_mercaderia_precios",
        ),
        CheckConstraint(
            "descuento_aplicado >= 0 AND descuento_aplicado <= 100",
            name="ck_retiros_mercaderia_descuento",
        ),
    )

    @property
    def nombre_empleada(self) -> str:
        """El nombre a mostrar: el del usuario si es de esta empresa."""
        if self.empleada is not None:
            return self.empleada.nombre
        return self.empleada_nombre or ""


class CobroJoyero(Base):
    """
    El cliente paga en el local un arreglo del joyero; esa plata después se le
    entrega al joyero (la salida no la registra el sistema).

    Afecta el arqueo en el medio de pago elegido, pero no es venta: no genera
    código de cambio, no descuenta stock, no entra en reportes de ventas.
    """

    __tablename__ = "cobros_joyero"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    turno_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("turnos.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    punto_de_venta_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Los dos precios que ve la vendedora: se cobra uno u otro según el medio.
    monto_efectivo: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default="0"
    )
    monto_otros: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default="0"
    )
    medio_de_pago_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("medios_de_pago.id", ondelete="RESTRICT"), nullable=False
    )
    monto_cobrado: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    numero_reclamo: Mapped[str | None] = mapped_column(String(50), nullable=True)
    registrado_por_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False
    )
    # Los cobros de joyero no admiten cuotas: queda documentado en el modelo.
    sin_cuotas: Mapped[bool] = mapped_column(Boolean, Computed("TRUE", persisted=True))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)

    punto_de_venta: Mapped["PuntoDeVenta"] = relationship()
    medio_de_pago: Mapped["MedioDePago"] = relationship()
    registrado_por: Mapped["Usuario"] = relationship(foreign_keys=[registrado_por_id])

    __table_args__ = (
        CheckConstraint(
            "monto_efectivo >= 0 AND monto_otros >= 0", name="ck_cobros_joyero_montos"
        ),
        CheckConstraint("monto_cobrado > 0", name="ck_cobros_joyero_cobrado_positivo"),
    )
