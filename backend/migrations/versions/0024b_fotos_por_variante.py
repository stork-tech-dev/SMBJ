"""Fotos de producto pueden asociarse a una variante (fallback al producto)

Revision ID: 0024b
Revises: 0023
Create Date: 2026-08-25

Agrega `variante_id` (nullable) a `producto_fotos`. Fotos con variante_id
son exclusivas de esa variante; con NULL siguen siendo del producto
(compartidas por todas sus variantes). El índice parcial único de principal
se desdobla en dos: uno por producto (WHERE variante_id IS NULL) y otro por
variante (WHERE variante_id IS NOT NULL).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024b"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Nueva columna nullable
    op.add_column(
        "producto_fotos",
        sa.Column("variante_id", sa.BigInteger(), nullable=True),
    )

    # 2. FK con CASCADE: si se borra la variante, sus fotos propias se van.
    op.create_foreign_key(
        "fk_producto_fotos_variante_id",
        "producto_fotos",
        "producto_variantes",
        ["variante_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 3. Índice para consultas por variante
    op.create_index(
        "ix_producto_fotos_variante_id", "producto_fotos", ["variante_id"]
    )

    # 4. Reemplazar el índice parcial de principal: ahora hay dos pools.
    op.drop_index("uq_producto_fotos_una_principal", table_name="producto_fotos")

    # Una principal por producto (fotos compartidas, variante_id IS NULL)
    op.execute(
        "CREATE UNIQUE INDEX uq_producto_fotos_principal_producto "
        "ON producto_fotos (producto_id) "
        "WHERE es_principal AND variante_id IS NULL"
    )

    # Una principal por variante (fotos propias, variante_id IS NOT NULL)
    op.execute(
        "CREATE UNIQUE INDEX uq_producto_fotos_principal_variante "
        "ON producto_fotos (variante_id) "
        "WHERE es_principal AND variante_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("uq_producto_fotos_principal_variante", table_name="producto_fotos")
    op.drop_index("uq_producto_fotos_principal_producto", table_name="producto_fotos")

    # Restaurar el índice original (solo por producto, sin distinción)
    op.execute(
        "CREATE UNIQUE INDEX uq_producto_fotos_una_principal "
        "ON producto_fotos (producto_id) WHERE es_principal"
    )

    op.drop_index("ix_producto_fotos_variante_id", table_name="producto_fotos")
    op.drop_constraint("fk_producto_fotos_variante_id", "producto_fotos", type_="foreignkey")
    op.drop_column("producto_fotos", "variante_id")
