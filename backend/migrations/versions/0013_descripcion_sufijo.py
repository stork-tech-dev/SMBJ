"""Descripción del sufijo: cómo se nombra la variante en pantalla

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Texto con el que se nombra la variante donde antes decía "variante R".

    El sufijo NO cambia: sigue siendo el carácter que entra en
    `codigo_completo` y viaja en la etiqueta. Esto es solo cómo se lo llama
    en pantalla — "Rojo", "Talle 42" — para que la lista se pueda leer.
    """
    op.add_column(
        "variantes",
        sa.Column("descripcion_sufijo", sa.String(length=60), nullable=True),
    )

    # Las variantes que ya existían se completan con el texto que la pantalla
    # venía mostrando para ellas: no aparece nada nuevo, y quedan listas para
    # corregir a mano desde la edición de variante.
    op.execute(
        """
        UPDATE variantes
        SET descripcion_sufijo = 'Variante ' || sufijo
        WHERE NOT es_base AND descripcion_sufijo IS NULL
        """
    )

    # Espeja al `ck_variantes_base_sin_sufijo` que la tabla ya tiene: la BASE
    # no es variante de nada, así que no lleva descripción; las reales la
    # llevan siempre. Con el CHECK, que sea obligatoria no depende de que el
    # servicio se acuerde de validarla.
    op.create_check_constraint(
        "ck_variantes_base_sin_descripcion_sufijo",
        "variantes",
        "(es_base AND descripcion_sufijo IS NULL)"
        " OR (NOT es_base AND descripcion_sufijo IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_variantes_base_sin_descripcion_sufijo", "variantes")
    op.drop_column("variantes", "descripcion_sufijo")
