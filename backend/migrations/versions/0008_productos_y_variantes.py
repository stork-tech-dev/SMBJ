"""Productos y variantes, con la secuencia que genera los SKU

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Correlativo de los SKU. Una SEQUENCE y no MAX(sku)+1: dos altas
    # simultáneas obtienen números distintos sin bloquearse entre sí, y no
    # puede haber SKU repetidos ni con concurrencia.
    op.execute("CREATE SEQUENCE productos_sku_seq START 1")

    estacionalidad = postgresql.ENUM(
        "permanente", "verano", "invierno", "otoño", "primavera",
        name="estacionalidad_producto", create_type=False,
    )
    sa.Enum(
        "permanente", "verano", "invierno", "otoño", "primavera",
        name="estacionalidad_producto",
    ).create(op.get_bind(), checkfirst=True)

    op.create_table(
        "productos",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("sku", sa.String(length=5), nullable=False),
        sa.Column("sku_proveedor", sa.String(length=30), nullable=True),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("categoria_id", sa.BigInteger(), nullable=False),
        sa.Column("proveedor_id", sa.BigInteger(), nullable=False),
        sa.Column("precio_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("precio_venta", sa.Numeric(10, 2), nullable=False),
        sa.Column("descuento_producto", sa.Numeric(5, 2), server_default="0", nullable=False),
        sa.Column("peso_gramos", sa.Numeric(8, 2), nullable=True),
        sa.Column(
            "estacionalidad", estacionalidad, server_default="permanente", nullable=False
        ),
        sa.Column("stock_infinito", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("tiene_variantes", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # RESTRICT en ambas: ni una categoría ni un proveedor pueden
        # llevarse productos por delante al eliminarse.
        sa.ForeignKeyConstraint(["categoria_id"], ["categorias.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["proveedor_id"], ["proveedores.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("precio_usd > 0", name="ck_productos_precio_usd_positivo"),
        sa.CheckConstraint("precio_venta >= 0", name="ck_productos_precio_venta_no_negativo"),
        sa.CheckConstraint(
            "descuento_producto >= 0 AND descuento_producto <= 100",
            name="ck_productos_descuento_rango",
        ),
        sa.CheckConstraint(
            "peso_gramos IS NULL OR peso_gramos > 0", name="ck_productos_peso_positivo"
        ),
    )

    op.create_index("ix_productos_sku", "productos", ["sku"], unique=True)
    op.create_index("ix_productos_sku_proveedor", "productos", ["sku_proveedor"])
    op.create_index("ix_productos_categoria_id", "productos", ["categoria_id"])
    op.create_index("ix_productos_proveedor_id", "productos", ["proveedor_id"])
    op.create_index("ix_productos_estacionalidad", "productos", ["estacionalidad"])
    op.create_index("ix_productos_activo", "productos", ["activo"])

    op.create_table(
        "variantes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("producto_id", sa.BigInteger(), nullable=False),
        sa.Column("sufijo", sa.String(length=1), nullable=True),
        sa.Column("es_base", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("codigo_completo", sa.String(length=16), nullable=False),
        sa.Column("verificador", sa.String(length=1), nullable=False),
        sa.Column("stock_actual", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stock_minimo", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ubicacion_deposito", sa.String(length=100), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # CASCADE: una variante no tiene sentido sin su producto.
        sa.ForeignKeyConstraint(["producto_id"], ["productos.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "(es_base AND sufijo IS NULL) OR (NOT es_base AND sufijo IS NOT NULL)",
            name="ck_variantes_base_sin_sufijo",
        ),
        sa.CheckConstraint("stock_minimo >= 0", name="ck_variantes_stock_minimo_no_negativo"),
    )

    op.create_index("ix_variantes_producto_id", "variantes", ["producto_id"])
    op.create_index("ix_variantes_codigo_completo", "variantes", ["codigo_completo"], unique=True)

    # Un solo sufijo por producto, y una sola BASE. NULLS NOT DISTINCT hace
    # que la regla alcance a la BASE, cuyo sufijo es NULL: sin eso se
    # podrían crear dos variantes BASE del mismo producto.
    op.execute(
        "CREATE UNIQUE INDEX uq_variantes_sufijo_por_producto "
        "ON variantes (producto_id, sufijo) NULLS NOT DISTINCT"
    )


def downgrade() -> None:
    op.drop_index("uq_variantes_sufijo_por_producto", table_name="variantes")
    op.drop_index("ix_variantes_codigo_completo", table_name="variantes")
    op.drop_index("ix_variantes_producto_id", table_name="variantes")
    op.drop_table("variantes")

    for indice in (
        "ix_productos_activo",
        "ix_productos_estacionalidad",
        "ix_productos_proveedor_id",
        "ix_productos_categoria_id",
        "ix_productos_sku_proveedor",
        "ix_productos_sku",
    ):
        op.drop_index(indice, table_name="productos")
    op.drop_table("productos")

    sa.Enum(name="estacionalidad_producto").drop(op.get_bind(), checkfirst=True)
    op.execute("DROP SEQUENCE IF EXISTS productos_sku_seq")
