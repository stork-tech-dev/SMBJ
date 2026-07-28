"""
Modelo de la tabla `configuracion_sistema`.

Tabla de fila única: guarda los parámetros globales del ERP. El seed
inserta el registro inicial y la aplicación siempre lo edita, nunca
crea filas nuevas.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ConfiguracionSistema(Base):
    __tablename__ = "configuracion_sistema"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Múltiplo al que se redondean los precios finales.
    redondeo: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # Tope de descuento permitido, en porcentaje (0 a 100).
    descuento_maximo: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    # 'encadenado' (se aplican uno sobre otro) o 'sumado'.
    metodo_descuento: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="encadenado"
    )

    # Letra de la empresa que factura: 'S' (Soleil) o 'M' (Mallorca).
    letra_empresa: Mapped[str] = mapped_column(String(1), nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    # Nullable porque en el arranque (seed inicial) todavía no hay usuarios.
    # La FK se agregó en la migración 0002, cuando nació la tabla usuarios.
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("usuarios.id", ondelete="SET NULL", name="fk_configuracion_updated_by_usuarios"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint("letra_empresa IN ('S', 'M')", name="ck_config_letra_empresa"),
        CheckConstraint(
            "metodo_descuento IN ('encadenado', 'sumado')",
            name="ck_config_metodo_descuento",
        ),
        CheckConstraint(
            "descuento_maximo >= 0 AND descuento_maximo <= 100",
            name="ck_config_descuento_maximo",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<ConfiguracionSistema {self.id} letra={self.letra_empresa}>"
