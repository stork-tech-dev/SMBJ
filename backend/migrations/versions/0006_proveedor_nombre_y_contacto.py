"""Proveedores: razon_social pasa a nombre, y se agrega contacto

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # RENAME COLUMN y no drop + add: conserva los datos existentes y el
    # tipo. Un drop/add vaciaría la columna en todos los proveedores.
    op.alter_column("proveedores", "razon_social", new_column_name="nombre")

    # El índice sobrevive al rename de la columna pero conserva su nombre
    # viejo, que quedaría mintiendo sobre qué indexa.
    op.execute("ALTER INDEX ix_proveedores_razon_social RENAME TO ix_proveedores_nombre")

    # Opcional: los proveedores que ya existen quedan con NULL.
    op.add_column("proveedores", sa.Column("contacto", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("proveedores", "contacto")
    op.execute("ALTER INDEX ix_proveedores_nombre RENAME TO ix_proveedores_razon_social")
    op.alter_column("proveedores", "nombre", new_column_name="razon_social")
