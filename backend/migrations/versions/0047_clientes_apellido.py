"""Clientes: apellido.

Revision ID: 0047
Revises: 0046
Create Date: 2026-10-29

Apellido, nombre y email pasan a ser obligatorios en el alta (la regla vive
en `services/clientes.py`). La columna es nullable por los clientes ya
cargados, que no lo tienen. La fecha de nacimiento ya la agregó 0046.
"""

import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clientes", sa.Column("apellido", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("clientes", "apellido")
