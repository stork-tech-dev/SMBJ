"""Fotos de producto: hasta 5 por producto, una principal

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "producto_fotos",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("producto_id", sa.BigInteger(), nullable=False),
        sa.Column("url", sa.String(length=255), nullable=False),
        sa.Column("es_principal", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("orden", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # CASCADE: una foto no tiene sentido sin su producto. El archivo en
        # disco lo borra el service; esto solo limpia la fila.
        sa.ForeignKeyConstraint(["producto_id"], ["productos.id"], ondelete="CASCADE"),
        sa.CheckConstraint("orden >= 0", name="ck_producto_fotos_orden_no_negativo"),
    )

    op.create_index("ix_producto_fotos_producto_id", "producto_fotos", ["producto_id"])

    # Una sola principal por producto, garantizado por la base. El índice es
    # PARCIAL: solo alcanza a las filas con es_principal = true. Si no lo
    # fuera, un producto no podría tener dos fotos secundarias.
    op.execute(
        "CREATE UNIQUE INDEX uq_producto_fotos_una_principal "
        "ON producto_fotos (producto_id) WHERE es_principal"
    )


def downgrade() -> None:
    op.drop_index("uq_producto_fotos_una_principal", table_name="producto_fotos")
    op.drop_index("ix_producto_fotos_producto_id", table_name="producto_fotos")
    op.drop_table("producto_fotos")
