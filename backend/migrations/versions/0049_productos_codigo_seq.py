"""Códigos de producto más cortos: secuencia propia para el formato nuevo.

Revision ID: 0049
Revises: 0048
Create Date: 2026-11-06

Los productos nuevos usan un SKU de 4 caracteres (Soleil `AAA0`, Mallorca
`AA01`), así que el correlativo arranca de cero en lugar de continuar el del
formato anterior. No se tocan datos: los productos existentes conservan su
código porque las etiquetas ya están impresas. `productos_sku_seq` queda sin
uso.
"""

from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE productos_codigo_seq START 1")


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS productos_codigo_seq")
