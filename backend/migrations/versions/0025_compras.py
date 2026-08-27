"""Módulo de compras a proveedores

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-26

Crea las tablas `compras` y `compra_items` para el registro de compras a
proveedores, y agrega `compra_id` a `movimientos_stock` para trazar cada
movimiento de ingreso hasta la compra que lo originó.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

estado_compra = sa.Enum("borrador", "cerrada", "eliminada", name="estado_compra")


def upgrade() -> None:
    estado_col = postgresql.ENUM(
        "borrador", "cerrada", "eliminada", name="estado_compra", create_type=False
    )
    sa.Enum("borrador", "cerrada", "eliminada", name="estado_compra").create(
        op.get_bind(), checkfirst=True
    )

    op.create_table(
        "compras",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("proveedor_id", sa.BigInteger(), sa.ForeignKey("proveedores.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("punto_de_venta_id", sa.BigInteger(), sa.ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("estado", estado_col, nullable=False, server_default="borrador", index=True),
        sa.Column("fecha_compra", sa.Date(), nullable=True),
        sa.Column("fecha_carga", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("fecha_cierre", sa.DateTime(timezone=False), nullable=True),
        sa.Column("usuario_carga_id", sa.BigInteger(), sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "compra_items",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("compra_id", sa.BigInteger(), sa.ForeignKey("compras.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("variante_id", sa.BigInteger(), sa.ForeignKey("producto_variantes.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("precio_usd_anterior", sa.Numeric(10, 2), nullable=True),
        sa.Column("precio_usd_nuevo", sa.Numeric(10, 2), nullable=False),
        sa.Column("precio_actualizado", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("etiquetas_impresas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("es_producto_nuevo", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("compra_id", "variante_id", name="uq_compra_items_variante"),
        sa.CheckConstraint("cantidad > 0", name="ck_compra_items_cantidad_positiva"),
        sa.CheckConstraint("precio_usd_nuevo > 0", name="ck_compra_items_precio_positivo"),
        sa.CheckConstraint("etiquetas_impresas >= 0", name="ck_compra_items_etiquetas_no_negativas"),
    )

    # Traza desde movimientos_stock hasta la compra que los originó.
    op.add_column(
        "movimientos_stock",
        sa.Column("compra_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_movimientos_stock_compra_id",
        "movimientos_stock",
        "compras",
        ["compra_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_movimientos_stock_compra_id", "movimientos_stock", ["compra_id"])


def downgrade() -> None:
    op.drop_index("ix_movimientos_stock_compra_id", table_name="movimientos_stock")
    op.drop_constraint("fk_movimientos_stock_compra_id", "movimientos_stock", type_="foreignkey")
    op.drop_column("movimientos_stock", "compra_id")
    op.drop_table("compra_items")
    op.drop_table("compras")
    estado_compra.drop(op.get_bind(), checkfirst=True)
