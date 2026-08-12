"""
Modelos de `productos` y `variantes`.

Todo producto tiene al menos una variante: los que no manejan variantes
reales reciben una BASE automática al crearse. Así el stock siempre cuelga
de una variante y no hay dos caminos según el tipo de producto.
"""

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.categoria import Categoria
    from app.models.producto_foto import ProductoFoto
    from app.models.proveedor import Proveedor


class Temporada(str, enum.Enum):
    """
    Cómo se compra la mercadería, que es en dos temporadas y no en cuatro
    estaciones: el rubro reposiciona por Otoño-Invierno y Primavera-Verano.

    Antes eran las cinco estaciones sueltas (`permanente`, `verano`,
    `invierno`, `otoño`, `primavera`), que obligaban a elegir entre dos
    valores que en la práctica significan lo mismo —¿un buzo es de otoño o
    de invierno?— y a filtrar dos veces para ver una temporada entera.
    """

    ATEMPORAL = "atemporal"
    OTONIO_INVIERNO = "otoño_invierno"
    PRIMAVERA_VERANO = "primavera_verano"


def _enum(tipo, nombre):
    """Enum de PostgreSQL que persiste el .value, no el nombre del miembro."""
    return Enum(tipo, name=nombre, values_callable=lambda e: [i.value for i in e])


class Producto(Base):
    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Campo de negocio único: lleva su propio índice, independiente de la PK
    # (Principio 4). Lo genera el sistema desde una SEQUENCE.
    sku: Mapped[str] = mapped_column(String(5), nullable=False, unique=True, index=True)

    # Código con el que el proveedor identifica el producto. Opcional y sin
    # unicidad: dos proveedores pueden usar el mismo.
    sku_proveedor: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)

    # Obligatoria: es la columna por la que se lee y se ordena el catálogo.
    # Sin ella la fila solo se identifica por el SKU, que no dice qué es.
    # Tiene un índice sobre `lower(descripcion)` —la misma expresión del
    # ORDER BY del listado— creado en la migración 0012.
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)

    categoria_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("categorias.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    proveedor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proveedores.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    precio_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # DESNORMALIZACIÓN JUSTIFICADA (Principio 4).
    # Es `precio_usd × proveedor.dolar_actual`, redondeado hacia arriba al
    # múltiplo configurado. Se persiste para no recalcularlo en cada fila
    # del listado ni en cada lectura del punto de venta, que es la consulta
    # más caliente del sistema. Lo mantiene el service: se recalcula al
    # cambiar `precio_usd` y en cascada cuando cambia el dólar del
    # proveedor, desde `_aplicar_cambio_dolar()`.
    precio_venta: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    descuento_producto: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default="0"
    )

    peso_gramos: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)

    # `atemporal` por defecto: es lo que corresponde a la mayoría del
    # catálogo de una bijouterie, y hace que el alta no obligue a decidir
    # una temporada para un producto que no la tiene.
    temporada: Mapped[Temporada] = mapped_column(
        _enum(Temporada, "temporada_producto"),
        nullable=False,
        server_default=Temporada.ATEMPORAL.value,
        index=True,
    )

    # El producto no descuenta stock: servicios, productos a pedido.
    stock_infinito: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    # Si maneja variantes reales. En False el producto tiene solo la BASE.
    tiene_variantes: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    categoria: Mapped["Categoria"] = relationship(lazy="joined")
    proveedor: Mapped["Proveedor"] = relationship(lazy="joined")

    # cascade: las variantes no tienen sentido sin su producto.
    variantes: Mapped[list["Variante"]] = relationship(
        back_populates="producto", cascade="all, delete-orphan", order_by="Variante.sufijo"
    )
    fotos: Mapped[list["ProductoFoto"]] = relationship(
        back_populates="producto",
        cascade="all, delete-orphan",
        order_by="ProductoFoto.orden, ProductoFoto.id",
    )

    __table_args__ = (
        CheckConstraint("precio_usd > 0", name="ck_productos_precio_usd_positivo"),
        CheckConstraint("precio_venta >= 0", name="ck_productos_precio_venta_no_negativo"),
        CheckConstraint(
            "descuento_producto >= 0 AND descuento_producto <= 100",
            name="ck_productos_descuento_rango",
        ),
        CheckConstraint(
            "peso_gramos IS NULL OR peso_gramos > 0", name="ck_productos_peso_positivo"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<Producto {self.id} {self.sku}>"


class Variante(Base):
    """
    Unidad que efectivamente tiene stock y código de barras.

    `codigo_completo` es `letra_empresa + sku + sufijo` y se congela al
    crearse: las etiquetas se imprimen y se pegan a la mercadería, así que
    recalcularlo invalidaría lo que ya está en el depósito.
    """

    __tablename__ = "variantes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    producto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("productos.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # NULL en la variante BASE, un carácter en las reales.
    sufijo: Mapped[str | None] = mapped_column(String(1), nullable=True)

    # Cómo se llama esta variante en pantalla: "Rojo", "Talle 42". El sufijo
    # es el carácter que entra en el código y viaja en la etiqueta; esto es
    # solo el nombre legible, y va donde antes decía "variante R".
    # NULL en la BASE, obligatoria en las reales (lo ata el CHECK de abajo).
    descripcion_sufijo: Mapped[str | None] = mapped_column(String(60), nullable=True)

    es_base: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    codigo_completo: Mapped[str] = mapped_column(
        String(16), nullable=False, unique=True, index=True
    )

    # Dígito módulo 11 sobre `codigo_completo`, para detectar errores de
    # tipeo manual. NO es el checksum de Code128: ese es módulo 103, lo
    # calcula el encoder al generar la imagen y no se persiste.
    verificador: Mapped[str] = mapped_column(String(1), nullable=False)

    # Precio propio de la variante. NULL = usa el del producto.
    #
    # `precio_venta` es derivado, igual que en el producto: se calcula con
    # `calcular_precio_venta()` y se recalcula en cascada cuando cambia el
    # dólar del proveedor. Los dos van juntos o ninguno (lo ata un CHECK).
    precio_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    precio_venta: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    stock_actual: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    stock_minimo: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    ubicacion_deposito: Mapped[str | None] = mapped_column(String(100), nullable=True)

    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    producto: Mapped["Producto"] = relationship(back_populates="variantes")

    __table_args__ = (
        # La BASE no lleva sufijo y las reales sí: son excluyentes.
        CheckConstraint(
            "(es_base AND sufijo IS NULL) OR (NOT es_base AND sufijo IS NOT NULL)",
            name="ck_variantes_base_sin_sufijo",
        ),
        # Espeja al de arriba: la BASE no es variante de nada, así que no
        # lleva nombre; las reales lo llevan siempre. Con el CHECK, que sea
        # obligatorio no depende de que el servicio se acuerde de validarlo.
        CheckConstraint(
            "(es_base AND descripcion_sufijo IS NULL)"
            " OR (NOT es_base AND descripcion_sufijo IS NOT NULL)",
            name="ck_variantes_base_sin_descripcion_sufijo",
        ),
        CheckConstraint("stock_minimo >= 0", name="ck_variantes_stock_minimo_no_negativo"),
        CheckConstraint(
            "precio_usd IS NULL OR precio_usd > 0",
            name="ck_variantes_precio_usd_positivo",
        ),
        # `precio_venta` se deriva de `precio_usd`: uno sin el otro sería un
        # número que nadie puede recalcular al cambiar la cotización.
        CheckConstraint(
            "(precio_usd IS NULL AND precio_venta IS NULL)"
            " OR (precio_usd IS NOT NULL AND precio_venta IS NOT NULL)",
            name="ck_variantes_precio_completo",
        ),
    )

    @property
    def codigo_con_verificador(self) -> str:
        """Lo que se imprime en la etiqueta y se codifica en Code128."""
        return f"{self.codigo_completo}{self.verificador}"

    # --- Precio efectivo ---------------------------------------------------
    # La regla "el propio manda sobre el del producto" vive acá y en un solo
    # lugar: la usan el listado, el detalle y cualquier pantalla futura. Si
    # cada consumidor hiciera su propio COALESCE, alcanzaría con que uno se
    # olvidara para mostrar un precio que no es el que se cobra.

    @property
    def tiene_precio_propio(self) -> bool:
        return self.precio_usd is not None

    @property
    def precio_usd_efectivo(self) -> Decimal:
        return self.precio_usd if self.precio_usd is not None else self.producto.precio_usd

    @property
    def precio_venta_efectivo(self) -> Decimal:
        return (
            self.precio_venta
            if self.precio_venta is not None
            else self.producto.precio_venta
        )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<Variante {self.id} {self.codigo_completo}>"
