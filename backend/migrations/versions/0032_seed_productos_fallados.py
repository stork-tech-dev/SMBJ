"""Seed: "Productos Fallados", la Ubicación Especial por defecto.

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-19

Separada de 0031 porque el valor 'especial' del enum recién se puede usar
una vez que esa migración ya confirmó.
"""

from alembic import op
import sqlalchemy as sa

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO puntos_de_venta (codigo, nombre, tipo, activo, created_at, updated_at)
            VALUES ('FALL', 'Productos Fallados', 'especial', true, now(), now())
            ON CONFLICT (codigo) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM puntos_de_venta WHERE codigo = 'FALL' AND tipo = 'especial'")
    )
