"""
Modelos de la venta: `ventas`, `venta_items`, `venta_pagos` y el catálogo
`motivos_descuento`.

La venta arranca en `en_curso` y ahí ya es una fila con sus ítems. No es un
detalle de implementación: el carrito vive en la base desde el primer
producto escaneado, y eso es lo que hace que una vendedora a la que se le
cierra la app encuentre su venta donde la dejó. Recién al confirmar se
descuenta el stock, se suman los puntos y se toca la seña — todo en la
misma transacción.

Un ítem es UNA unidad. No hay campo `cantidad` y no es un olvido: la lógica
de promociones necesita ordenar unidad por unidad para saber cuál es la más
barata de cada grupo, y con un contador esa unidad no existiría como fila.
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
    SmallInteger,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.cliente import Cliente
    from app.models.medio_pago import MedioDePago, PlanCuotas
    from app.models.producto import Variante
    from app.models.promocion import Promocion
    from app.models.punto_de_venta import PuntoDeVenta
    from app.models.sena import Sena
    from app.models.usuario import Usuario


class EstadoVenta(str, enum.Enum):
    """
    Dónde está la venta.

    `en_curso` es un carrito: todavía no tocó el stock ni los puntos.
    `confirmada` ya movió todo. `anulada` lo revirtió con movimientos
    contrarios — la fila no se borra ni cambia sus importes, porque la venta
    ocurrió y hay que poder explicarla.
    """

    EN_CURSO = "en_curso"
    CONFIRMADA = "confirmada"
    ANULADA = "anulada"


def _enum(tipo, nombre):
    """Enum de PostgreSQL que persiste el .value, no el nombre del miembro."""
    return Enum(tipo, name=nombre, values_callable=lambda e: [i.value for i in e])


class MotivoDescuento(Base):
    """
    Por qué se hace un descuento: "Cumpleaños", "Empleada", "Liquidación Plata".

    UN catálogo para todos los tipos de descuento del negocio —producto,
    venta, cliente, empleada— y no una tabla por tipo. Cada tipo sería la
    misma estructura con otro nombre, y los reportes tendrían que unirlas
    todas para responder "cuánto se descontó y por qué".

    `porcentaje_sugerido` en NULL significa "que la vendedora elija de la
    lista". Con valor, se preselecciona; si ella lo cambia, el ítem guarda
    `porcentaje_modificado = TRUE` y queda la trazabilidad.
    """

    __tablename__ = "motivos_descuento"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    nombre: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    porcentaje_sugerido: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    # Habilita los planes sin interés aunque la venta no llegue al monto
    # mínimo del plan. Es una decisión comercial que viaja con el motivo
    # ("Empleada") y no con el plan, porque depende de a quién se le vende.
    habilita_cuotas_sin_interes: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    activo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "porcentaje_sugerido IS NULL"
            " OR (porcentaje_sugerido > 0 AND porcentaje_sugerido <= 100)",
            name="ck_motivos_descuento_porcentaje_rango",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<MotivoDescuento {self.id} {self.nombre}>"


class Venta(Base):
    __tablename__ = "ventas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Correlativo del sistema, formato V-000001. Campo de negocio único con
    # su propio índice (Principio 4). Sale de una SEQUENCE y no de
    # MAX(numero)+1: dos cajas vendiendo a la vez sacan números distintos sin
    # bloquearse.
    numero: Mapped[str] = mapped_column(String(12), nullable=False, unique=True, index=True)

    # NULL = venta sin cliente. Es el caso normal del mostrador: obligar a
    # identificarse frenaría la caja por un dato que casi nunca se usa.
    cliente_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("clientes.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    punto_de_venta_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    dispositivo_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dispositivos.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    estado: Mapped[EstadoVenta] = mapped_column(
        _enum(EstadoVenta, "estado_venta"),
        nullable=False,
        server_default=EstadoVenta.EN_CURSO.value,
        index=True,
    )

    # DESNORMALIZACIÓN JUSTIFICADA (Principio 4): los cuatro importes son la
    # foto del cierre. Se recalculan mientras la venta está `en_curso` y se
    # congelan al confirmar, porque a partir de ahí tienen que seguir dando
    # lo mismo aunque cambien los precios, el dólar o las promociones.
    # Recalcularlos después no reconstruiría lo que el cliente pagó.
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default="0"
    )
    descuento_total: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default="0"
    )
    recargo_total: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default="0"
    )
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, server_default="0")

    # 8 caracteres alfanuméricos, generados al CONFIRMAR. NULL mientras la
    # venta está en curso: un carrito abierto no tiene con qué cambiarse
    # nada, y darle código antes gastaría uno por cada venta abandonada.
    codigo_cambio: Mapped[str | None] = mapped_column(
        String(8), nullable=True, unique=True, index=True
    )

    puntos_acumulados: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    promocion_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promociones.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )

    cliente: Mapped["Cliente"] = relationship()  # noqa: F821
    punto_de_venta: Mapped["PuntoDeVenta"] = relationship()  # noqa: F821
    usuario: Mapped["Usuario"] = relationship()  # noqa: F821
    promocion: Mapped["Promocion"] = relationship()  # noqa: F821

    # cascade: un ítem o un pago no significan nada sin su venta. `orden` en
    # los ítems no es cosmético: la lógica de promociones necesita un orden
    # estable para decidir qué unidad queda en $0.
    items: Mapped[list["VentaItem"]] = relationship(
        back_populates="venta", cascade="all, delete-orphan", order_by="VentaItem.orden"
    )
    pagos: Mapped[list["VentaPago"]] = relationship(
        back_populates="venta", cascade="all, delete-orphan", order_by="VentaPago.id"
    )

    __table_args__ = (
        CheckConstraint("subtotal >= 0", name="ck_ventas_subtotal_no_negativo"),
        CheckConstraint("descuento_total >= 0", name="ck_ventas_descuento_no_negativo"),
        CheckConstraint("recargo_total >= 0", name="ck_ventas_recargo_no_negativo"),
        CheckConstraint("total >= 0", name="ck_ventas_total_no_negativo"),
        CheckConstraint("puntos_acumulados >= 0", name="ck_ventas_puntos_no_negativos"),
        # El código de cambio nace al confirmar. Una venta cerrada sin código
        # no se podría cambiar nunca, y una en curso con código habría
        # gastado uno por nada.
        CheckConstraint(
            "(estado = 'en_curso' AND codigo_cambio IS NULL)"
            " OR (estado <> 'en_curso' AND codigo_cambio IS NOT NULL)",
            name="ck_ventas_codigo_cambio_al_confirmar",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<Venta {self.id} {self.numero} {self.estado.value}>"


class VentaItem(Base):
    """
    UNA unidad vendida. Sin campo `cantidad`: dos anillos iguales son dos
    filas, porque la promoción 2x1 tiene que poder dejar una en $0 y cobrar
    la otra.
    """

    __tablename__ = "venta_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    venta_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ventas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variante_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("producto_variantes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # DESNORMALIZACIÓN JUSTIFICADA (Principio 4): el precio al momento de la
    # venta. El de la variante cambia con el dólar, y sin esta copia la
    # venta de ayer se reescribiría sola.
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # DESNORMALIZACIÓN JUSTIFICADA: el precio de LISTA de la variante ese
    # día. No es lo que pagó el cliente —eso es `precio_final`— y la
    # diferencia importa: es el valor con el que se acredita un cambio. Sin
    # este dato, un cambio hecho meses después no se podría valuar.
    precio_lista: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # El porcentaje aplicado a ESTA unidad, ya con el tope validado.
    descuento_item: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default="0"
    )
    motivo_descuento_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("motivos_descuento.id", ondelete="RESTRICT"), nullable=True
    )

    # TRUE si la vendedora se apartó del porcentaje sugerido por el motivo.
    # No bloquea nada: deja el rastro para el reporte de descuentos.
    porcentaje_modificado: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    # Lo que efectivamente se cobra por esta unidad. $0 si es la unidad
    # gratis de una promoción.
    precio_final: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    en_promocion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    # Orden de carga. Lo necesita la lógica de promociones para desempatar
    # entre unidades del mismo precio de forma estable: sin él, dos corridas
    # sobre el mismo carrito podrían regalar unidades distintas.
    orden: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    venta: Mapped["Venta"] = relationship(back_populates="items")
    variante: Mapped["Variante"] = relationship()  # noqa: F821
    motivo_descuento: Mapped["MotivoDescuento"] = relationship()

    __table_args__ = (
        CheckConstraint("precio_unitario >= 0", name="ck_venta_items_precio_no_negativo"),
        CheckConstraint("precio_lista >= 0", name="ck_venta_items_lista_no_negativo"),
        CheckConstraint("precio_final >= 0", name="ck_venta_items_final_no_negativo"),
        CheckConstraint(
            "descuento_item >= 0 AND descuento_item <= 100",
            name="ck_venta_items_descuento_rango",
        ),
        # Un descuento sin motivo no se puede explicar en el reporte, y el
        # motivo es justamente lo primero que la vendedora elige.
        CheckConstraint(
            "descuento_item = 0 OR motivo_descuento_id IS NOT NULL",
            name="ck_venta_items_descuento_con_motivo",
        ),
        # Promoción y descuento sobre la misma unidad serían dos beneficios
        # apilados. La regla la valida el service con un mensaje entendible;
        # esto es la última barrera.
        CheckConstraint(
            "NOT (en_promocion AND descuento_item > 0)",
            name="ck_venta_items_promocion_sin_descuento",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<VentaItem {self.id} venta={self.venta_id} ${self.precio_final}>"


class VentaPago(Base):
    """
    Con qué se pagó. Hasta dos filas por venta (lo valida el service).

    Los tres importes están separados a propósito: `monto` es la parte de la
    venta que cubre este medio, `recargo` es lo que suma financiarla y
    `monto_total` es lo que efectivamente se cobra por esta vía. El recargo
    se calcula SOLO sobre `monto`, nunca sobre el total de la venta: si el
    cliente paga mitad efectivo y mitad tarjeta en cuotas, el interés es de
    la mitad financiada.
    """

    __tablename__ = "venta_pagos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    venta_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ventas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    medio_de_pago_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("medios_de_pago.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # NULL cuando es un pago sin financiar (efectivo, débito, un pago).
    plan_cuotas_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("planes_cuotas.id", ondelete="RESTRICT"), nullable=True
    )

    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    recargo: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default="0"
    )
    monto_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # Solo cuando el medio es una seña: dice de cuál se descontó. Sin esto no
    # se podría reconstruir en qué se gastó una seña.
    sena_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("senas.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    venta: Mapped["Venta"] = relationship(back_populates="pagos")
    medio_de_pago: Mapped["MedioDePago"] = relationship()  # noqa: F821
    plan_cuotas: Mapped["PlanCuotas"] = relationship()  # noqa: F821
    sena: Mapped["Sena"] = relationship()  # noqa: F821

    __table_args__ = (
        CheckConstraint("monto > 0", name="ck_venta_pagos_monto_positivo"),
        CheckConstraint("recargo >= 0", name="ck_venta_pagos_recargo_no_negativo"),
        # La suma tiene que cerrar: si `monto_total` pudiera ser cualquier
        # cosa, el arqueo de caja compararía contra un número inventado.
        CheckConstraint(
            "monto_total = monto + recargo", name="ck_venta_pagos_total_es_suma"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - solo debug
        return f"<VentaPago {self.id} venta={self.venta_id} ${self.monto_total}>"
