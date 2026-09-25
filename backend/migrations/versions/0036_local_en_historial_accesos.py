"""Local desde el que se accedió, en `historial_accesos`.

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-25

El listado de usuarios muestra el local del último acceso. Se guarda en cada
fila del historial —y no en `usuarios`— porque es un dato del acceso: queda
el local de ese momento aunque después el dispositivo se reasigne a otro.

`historial_accesos` es append-only (trigger que bloquea UPDATE): por eso la
FK no lleva ON DELETE SET NULL, que sería un UPDATE. Los puntos de venta no
se borran, se desactivan.
"""

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "historial_accesos",
        sa.Column(
            "punto_de_venta_id",
            sa.BigInteger(),
            sa.ForeignKey("puntos_de_venta.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_historial_accesos_punto_de_venta_id", "historial_accesos", ["punto_de_venta_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_historial_accesos_punto_de_venta_id", table_name="historial_accesos")
    op.drop_column("historial_accesos", "punto_de_venta_id")
