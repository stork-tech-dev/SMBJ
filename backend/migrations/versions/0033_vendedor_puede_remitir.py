"""Vendedor: permiso para armar envíos (puede_remitir) por defecto.

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-21

La hoja "Armar envío" del /remitos mobile (origen fijo al propio local,
destino acotado a CD/Ubicaciones Especiales) la usa un vendedor para
mandar mercadería fallada o reponerse desde el CD. Sin `puede_crear` en
Stock el botón queda oculto para cualquier vendedor — no tiene sentido
que la pantalla exista y nadie con ese rol pueda usarla.

No es un ALTER de esquema: es una fila de datos (`rol_permisos`) que ya
existe desde 0022 con `puede_crear = false`. `UPDATE` y no `INSERT`
porque la fila ya está.
"""

from alembic import op
import sqlalchemy as sa

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE rol_permisos SET puede_crear = true
            WHERE modulo = 'stock' AND recurso IS NULL
              AND rol_id = (SELECT id FROM roles WHERE nombre = 'vendedor')
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE rol_permisos SET puede_crear = false
            WHERE modulo = 'stock' AND recurso IS NULL
              AND rol_id = (SELECT id FROM roles WHERE nombre = 'vendedor')
            """
        )
    )
