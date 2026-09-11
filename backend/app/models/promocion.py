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
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TipoPromocion(str, enum.Enum):
    """
    Cómo se arman los grupos o el descuento.

    Para los tipos de grupo (DOS_X_UNO, TRES_X_DOS): el número que importa
    —cuántas unidades entran en el grupo y cuántas se pagan— está en
    `TAMANO_GRUPO` / `PAGAS_POR_GRUPO`, no en el nombre: así agregar un 4x3
    es una línea y no salir a buscar `if` repartidos por el service.

    Para PORCENTAJE: el `porcentaje_descuento` de la promoción se aplica
    sobre cada unidad alcanzada. No hay grupos.
    """

    DOS_X_UNO = "dos_x_uno"
    TRES_X_DOS = "tres_x_dos"
    PORCENTAJE = "porcentaje"


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
    """
    A qué apunta una fila de alcance.

    PRODUCTO / CATEGORIA: referencia_id apunta a un producto o categoría.
    TODOS_PRODUCTOS / TODOS_CATEGORIAS: referencia_id = 0 (sin sentido lógico;
        el service lo ignora y aplica a todo el catálogo).
    PUNTO_DE_VENTA: referencia_id apunta a un PuntoDeVenta; 0 = todos.
    MEDIO_DE_PAGO: referencia_id apunta a un MedioDePago; 0 = todos.
    """

    PRODUCTO = "producto"
    CATEGORIA = "categoria"
    TODOS_PRODUCTOS = "todos_productos"
    TODOS_CATEGORIAS = "todos_categorias"
    PUNTO_DE_VENTA = "punto_de_venta"
    MEDIO_DE_PAGO = "medio_de_pago"


def _enum(tipo, nombre):
    """Enum de PostgreSQL que persiste el .value, no el nombre del miembro."""
    return Enum(tipo, name=nombre, values_callable=lambda e: [i.value for i in e])


class Promocion(Base):
    __tablename__ = "promociones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    nombre: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    # Texto libre con aclaraciones internas (no se muestra a clientes).
    nota: Mapped[str | None] = mapped_column(String(500), nullable=True)

    tipo: Mapped[TipoPromocion] = mapped_column(
        _enum(TipoPromocion, "tipo_promocion"), nullable=False
    )

    activo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", index=True
    )

    # Solo para tipo PORCENTAJE. NULL en los otros tipos.
    # Rango 1-75: el service lo valida; la base pone el piso y el techo.
    porcentaje_descuento: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
        # El porcentaje tiene que estar en rango cuando viene.
        CheckConstraint(
            "porcentaje_descuento IS NULL OR "
            "(porcentaje_descuento >= 1 AND porcentaje_descuento <= 75)",
            name="ck_promociones_porcentaje_rango",
        ),
    )

    @property
    def tamano_grupo(self) -> int | None:
        return TAMANO_GRUPO.get(self.tipo)

    @property
    def pagas_por_grupo(self) -> int | None:
        return PAGAS_POR_GRUPO.get(self.tipo)

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
