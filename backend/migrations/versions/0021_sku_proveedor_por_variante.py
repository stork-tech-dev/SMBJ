"""Cada variante puede tener su propio código de proveedor

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    `sku_proveedor` en `producto_variantes`, espejo del de `productos`.

    El proveedor no numera por producto: numera por color y por talle.
    "NK-AM90-RJ" y "NK-AM90-BL" son dos códigos del mismo artículo, y con un
    solo campo en el producto no había dónde anotarlos.

    NULL significa "usa el del producto", que es exactamente lo que pasa hoy:
    por eso la columna nace toda en NULL y no hace falta ningún backfill.

    Mismas características que la del producto (VARCHAR(30), opcional, con
    índice y sin unicidad): dos proveedores pueden usar el mismo código.
    """
    op.add_column(
        "producto_variantes",
        sa.Column("sku_proveedor", sa.String(length=30), nullable=True),
    )
    op.create_index(
        "ix_producto_variantes_sku_proveedor", "producto_variantes", ["sku_proveedor"]
    )


def downgrade() -> None:
    """
    Al volver atrás, las variantes pierden su código propio y pasan a
    responder con el del producto. No hay dónde guardarlos: el producto tiene
    un solo campo y las variantes que lo usaban son varias.
    """
    op.drop_index("ix_producto_variantes_sku_proveedor", table_name="producto_variantes")
    op.drop_column("producto_variantes", "sku_proveedor")
