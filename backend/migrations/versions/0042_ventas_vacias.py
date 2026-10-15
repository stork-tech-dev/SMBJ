"""Ventas vacías: se borran las `en_curso` sin productos.

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-15

Desde acá una venta nace con su primer producto y se descarta al quitarle
el último: una venta sin productos no existe. Las que quedaron vacías de
antes (se abría una al entrar a "Nueva venta") hacían aparecer el aviso de
"venta sin concluir" sin nada que cobrar. Nunca tocaron el stock ni los
puntos, así que se borran igual que un descarte.
"""

from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

# Las ventas en curso sin ningún ítem.
_VACIAS = """
    SELECT v.id FROM ventas v
    WHERE v.estado = 'en_curso'
      AND NOT EXISTS (SELECT 1 FROM venta_items i WHERE i.venta_id = v.id)
"""


def upgrade() -> None:
    # Los pagos caen solos por el ON DELETE CASCADE; se borran antes igual
    # para no depender de eso.
    op.execute(f"DELETE FROM venta_pagos WHERE venta_id IN ({_VACIAS})")
    op.execute(f"DELETE FROM ventas WHERE id IN ({_VACIAS})")


def downgrade() -> None:
    # Sin vuelta atrás: eran carritos vacíos, no hay nada que restaurar.
    pass
