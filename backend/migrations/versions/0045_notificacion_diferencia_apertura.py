"""Notificación de faltante/sobrante al abrir el turno.

Revision ID: 0045
Revises: 0044
Create Date: 2026-10-29

Suma 'diferencia_apertura' al enum de tipos de notificación: el efectivo
inicial de un turno no coincide con lo contado al cerrar el anterior.
"""

from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE no puede correr dentro de una transacción en Postgres < 12
    # ni usarse en la misma: va en su propio bloque autocommit.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE tipo_notificacion ADD VALUE IF NOT EXISTS 'diferencia_apertura'"
        )


def downgrade() -> None:
    # Postgres no quita valores de un enum: queda sin usar.
    pass
