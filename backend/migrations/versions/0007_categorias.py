"""Categorías: árbol de hasta 5 niveles para clasificar productos

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "categorias",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(length=150), nullable=False),
        sa.Column("nivel", sa.SmallInteger(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("orden", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # RESTRICT: borrar un padre no puede arrastrar su descendencia.
        sa.ForeignKeyConstraint(
            ["parent_id"], ["categorias.id"], ondelete="RESTRICT",
            name="categorias_parent_id_fkey",
        ),
        sa.CheckConstraint("nivel BETWEEN 1 AND 5", name="ck_categorias_nivel_rango"),
        # La regla que define el árbol, garantizada por la base y no solo
        # por el service: solo las raíces no tienen padre.
        sa.CheckConstraint(
            "(nivel = 1 AND parent_id IS NULL) OR (nivel > 1 AND parent_id IS NOT NULL)",
            name="ck_categorias_raiz_sin_padre",
        ),
    )

    op.create_index("ix_categorias_nombre", "categorias", ["nombre"])
    op.create_index("ix_categorias_nivel", "categorias", ["nivel"])
    op.create_index("ix_categorias_parent_id", "categorias", ["parent_id"])

    # Sin hermanos homónimos. NULLS NOT DISTINCT (PostgreSQL 15+) hace que
    # la regla alcance también a las raíces, donde parent_id es NULL: sin
    # eso, PostgreSQL considera cada NULL distinto y se podrían crear dos
    # categorías de nivel 1 con el mismo nombre.
    op.execute(
        "CREATE UNIQUE INDEX uq_categorias_hermanos "
        "ON categorias (parent_id, nombre) NULLS NOT DISTINCT"
    )


def downgrade() -> None:
    op.drop_index("uq_categorias_hermanos", table_name="categorias")
    op.drop_index("ix_categorias_parent_id", table_name="categorias")
    op.drop_index("ix_categorias_nivel", table_name="categorias")
    op.drop_index("ix_categorias_nombre", table_name="categorias")
    op.drop_table("categorias")
