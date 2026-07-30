"""Dispositivos: datos del equipo leídos del User-Agent

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Todas opcionales: los dispositivos ya registrados quedan en NULL y se
    # completan solos en su próxima conexión, sin backfill.
    #
    # `user_agent` es el string crudo y los otros tres son su interpretación.
    # Se guardan ambos a propósito: si las heurísticas fallan con algún
    # navegador, el original permite recalcularlos.
    op.add_column("dispositivos", sa.Column("user_agent", sa.Text(), nullable=True))
    op.add_column(
        "dispositivos", sa.Column("sistema_operativo", sa.String(length=50), nullable=True)
    )
    op.add_column("dispositivos", sa.Column("navegador", sa.String(length=50), nullable=True))
    op.add_column("dispositivos", sa.Column("modelo", sa.String(length=80), nullable=True))


def downgrade() -> None:
    op.drop_column("dispositivos", "modelo")
    op.drop_column("dispositivos", "navegador")
    op.drop_column("dispositivos", "sistema_operativo")
    op.drop_column("dispositivos", "user_agent")
