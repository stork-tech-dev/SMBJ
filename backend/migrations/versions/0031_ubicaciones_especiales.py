"""Puntos de venta: nuevo tipo "especial" (Ubicación Especial).

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-19

Un lugar donde el producto existe físicamente pero NO cuenta como stock
vendible (ej. mercadería fallada, en reparación). Solo aparece como origen
o destino de un remito y como opción de filtro en /consulta-stock — en todo
lo demás queda excluida (ver `_consulta_base` en app/services/stock.py y
los column_property de Variante en app/models/producto.py).

El seed de "Productos Fallados" va en 0032 y no acá: PostgreSQL no permite
usar un valor de enum recién agregado dentro de la misma transacción en la
que se agregó. En este proyecto `env.py` corre TODAS las migraciones
pendientes en una sola transacción (no una por revisión), así que separar
en dos archivos no alcanza por sí solo — el `ALTER TYPE` tiene que salir de
esa transacción con `autocommit_block()` para que 0032 ya lo vea confirmado.
"""

from alembic import op
import sqlalchemy as sa

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(sa.text("ALTER TYPE tipo_punto_venta ADD VALUE IF NOT EXISTS 'especial'"))


def downgrade() -> None:
    # Los enums de PostgreSQL no permiten eliminar valores una vez agregados
    # sin recrear el tipo. El downgrade no revierte el ALTER TYPE.
    pass
