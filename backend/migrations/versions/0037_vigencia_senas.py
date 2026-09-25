"""Vigencia de las señas, en `configuracion_sistema`.

Revision ID: 0037
Revises: 0036
Create Date: 2026-09-25

El reporte de Señas muestra la fecha de vencimiento y el estado "vencida".
El vencimiento no se persiste en cada seña (Principio 4): es la fecha de alta
más estos días, calculado al consultar. Por ahora es solo un criterio del
reporte; el cobro no bloquea una seña vencida.
"""

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "configuracion_sistema",
        sa.Column("dias_vigencia_sena", sa.Integer(), nullable=False, server_default="30"),
    )
    op.create_check_constraint(
        "ck_config_dias_vigencia_sena", "configuracion_sistema", "dias_vigencia_sena > 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_config_dias_vigencia_sena", "configuracion_sistema", type_="check")
    op.drop_column("configuracion_sistema", "dias_vigencia_sena")
