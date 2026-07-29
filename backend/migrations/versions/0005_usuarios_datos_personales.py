"""Datos personales de usuarios: fecha de nacimiento, celular y local asignado

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Las tres columnas son opcionales: los usuarios que ya existen quedan
    # con NULL y no hace falta backfill.
    op.add_column("usuarios", sa.Column("fecha_nacimiento", sa.Date(), nullable=True))
    op.add_column("usuarios", sa.Column("celular", sa.String(length=20), nullable=True))
    op.add_column("usuarios", sa.Column("local_asignado_id", sa.BigInteger(), nullable=True))

    op.create_index("ix_usuarios_local_asignado_id", "usuarios", ["local_asignado_id"])

    # SET NULL: dar de baja un punto de venta no puede arrastrar usuarios.
    op.create_foreign_key(
        "usuarios_local_asignado_id_fkey",
        "usuarios",
        "puntos_de_venta",
        ["local_asignado_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("usuarios_local_asignado_id_fkey", "usuarios", type_="foreignkey")
    op.drop_index("ix_usuarios_local_asignado_id", table_name="usuarios")
    op.drop_column("usuarios", "local_asignado_id")
    op.drop_column("usuarios", "celular")
    op.drop_column("usuarios", "fecha_nacimiento")
