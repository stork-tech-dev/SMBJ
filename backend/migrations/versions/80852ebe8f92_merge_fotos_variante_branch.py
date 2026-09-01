"""merge_fotos_variante_branch

Revision ID: 80852ebe8f92
Revises: 0024b, 0026
Create Date: 2026-08-31 12:25:37.027122
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '80852ebe8f92'
down_revision: Union[str, tuple[str, ...], None] = ('0024b', '0026')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
