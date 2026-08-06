"""Precio propio por variante, que manda sobre el del producto

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Precio propio de una variante: un talle especial o una terminación más
    cara puede valer distinto que el resto del producto.

    Las dos columnas son anulables y **NULL significa "usa el del
    producto"**. No van en una tabla aparte porque la relación es 1 a 0-o-1:
    una tabla sería un JOIN en cada lectura y un segundo lugar que mantener
    sincronizado con la cascada del dólar, sin nada a cambio. El historial
    de cambios ya queda en `auditoria`, que es append-only.
    """
    op.add_column("variantes", sa.Column("precio_usd", sa.Numeric(10, 2), nullable=True))
    op.add_column("variantes", sa.Column("precio_venta", sa.Numeric(10, 2), nullable=True))

    op.create_check_constraint(
        "ck_variantes_precio_usd_positivo",
        "variantes",
        "precio_usd IS NULL OR precio_usd > 0",
    )

    # Los dos NULL o los dos con valor. `precio_venta` se deriva de
    # `precio_usd`, así que un precio en pesos sin su origen en dólares sería
    # un número que nadie puede recalcular cuando cambie la cotización.
    op.create_check_constraint(
        "ck_variantes_precio_completo",
        "variantes",
        "(precio_usd IS NULL AND precio_venta IS NULL)"
        " OR (precio_usd IS NOT NULL AND precio_venta IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_variantes_precio_completo", "variantes")
    op.drop_constraint("ck_variantes_precio_usd_positivo", "variantes")
    op.drop_column("variantes", "precio_venta")
    op.drop_column("variantes", "precio_usd")
