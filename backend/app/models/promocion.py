"""
Modelos de `promociones` y `promocion_alcance`.

Una promoción es una regla de agrupamiento, no un descuento: en un 2x1 el
más barato de cada par queda en $0 y los demás se cobran enteros. Por eso
no vive junto a los motivos de descuento y por eso un ítem en promoción no
acepta descuento adicional — serían dos beneficios sobre la misma unidad.

El ALCANCE dice sobre qué aplica. Puede ser un producto puntual o una
categoría entera, y se modela con una tabla de filas en vez de dos columnas
opcionales para que una promo pueda combinar las dos cosas.
"""

import enum
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TipoPromocion(str, enum.Enum):
    """
    Cómo se arman los grupos.

    El número que importa —cuántas unidades entran en el grupo y cuántas se
    pagan— no está en el nombre sino en `TAMANO_GRUPO` / `PAGAS_POR_GRUPO`,
    abajo: así agregar un 4x3 es una línea y no salir a buscar `if`
    repartidos por el service.
    """

    DOS_X_UNO = "dos_x_uno"
    TRES_X_DOS = "tres_x_dos"


# Cuántas unidades forman un grupo y cuántas de ellas se cobran. Lo que
# sobra del grupo —lo más barato— queda en $0.
TAMANO_GRUPO: dict[TipoPromocion, int] = {
    TipoPromocion.DOS_X_UNO: 2,
    TipoPromocion.TRES_X_DOS: 3,
}
PAGAS_POR_GRUPO: dict[TipoPromocion, int] = {
    TipoPromocion.DOS_X_UNO: 1,
    TipoPromocion.TRES_X_DOS: 2,
}


class TipoAlcance(str, enum.Enum):
    """A qué apunta una fila de alcance."""

    PRODUCTO = "producto"
    CATEGORIA = "categoria"


def _enum(tipo, nombre):
    """Enum de PostgreSQL que persiste el .value, no el nombre del miembro."""
    return Enum(tipo, name=nombre, values_callable=lambda e: [i.value for i in e])


class Promocion(Base):
    __tablename__ = "promociones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    nombre: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    tipo: Mapped[TipoPromocion] = mapped_column(
        _enum(TipoPromocion, "tipo_promocion"), nullable=False
    )

    activo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", index=True
    )

    # NULL = sin límite de ese lado. Una promo permanente tiene las dos en
    # NULL; una de temporada, las dos cargadas.
    fecha_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_fin: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    alcances: Mapped[list["PromocionAlcance"]] = relationship(
        back_populates="promocion", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Una vigencia que termina antes de empezar no habilita ningún día.
        CheckConstraint(
            "fecha_inicio IS NULL OR fecha_fin IS NULL OR fecha_inicio <= fecha_fin",
            name="ck_promociones_vigencia_coherente",
        ),
    )

    @property
    def tamano_grupo(self) -> int:
        return TAMANO_GRUPO[self.tipo]

    @property
    def pagas_por_grupo(self) -> int:
        return PAGAS_POR_GRUPO[self.tipo]

    def vigente_el(self, dia: date) -> bool:
        """
        Si la promoción rige ese día.

        Vive en el modelo y no en cada consulta: la pantalla que la ofrece y
        el service que la aplica tienen que coincidir, y si cada uno armara su
        propio rango, alcanzaría con que uno se equivocara para regalar
        mercadería un día que la promo ya venció.
        """
        if not self.activo:
            return False
        if self.fecha_inicio is not None and dia < self.fecha_inicio:
            return False
        if self.fecha_fin is not None and dia > self.fecha_fin:
            return False
        return True

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<Promocion {self.id} {self.nombre}>"


class PromocionAlcance(Base):
    """
    Una fila por producto o categoría alcanzada.

    `referencia_id` NO lleva FK y es a propósito: apunta a `productos` o a
    `categorias` según `tipo_alcance`, y una FK solo puede apuntar a una
    tabla. La alternativa —dos columnas opcionales, una por tabla— duplicaría
    la lógica de lectura en todos lados para ganar una restricción que el
    service ya valida al dar de alta el alcance.
    """

    __tablename__ = "promocion_alcance"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    promocion_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promociones.id", ondelete="CASCADE"), nullable=False, index=True
    )

    tipo_alcance: Mapped[TipoAlcance] = mapped_column(
        _enum(TipoAlcance, "tipo_alcance_promocion"), nullable=False
    )

    referencia_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    promocion: Mapped["Promocion"] = relationship(back_populates="alcances")

    __table_args__ = (
        # La misma categoría dos veces en la misma promo no la hace aplicar
        # dos veces: solo duplicaría la fila en la pantalla de edición.
        UniqueConstraint(
            "promocion_id", "tipo_alcance", "referencia_id", name="uq_promocion_alcance"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<PromocionAlcance {self.tipo_alcance.value}={self.referencia_id}>"
