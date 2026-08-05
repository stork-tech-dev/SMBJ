"""Descripción de producto obligatoria, más el índice del orden alfabético

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Dos cambios sobre `productos`, los dos por el mismo motivo: la
    descripción es la columna por la que se lee y se ordena el catálogo.

    1. Pasa a NOT NULL. Sin descripción la fila solo se puede identificar
       por su SKU, que no dice nada de lo que es. La pantalla ya venía
       tapando el agujero mostrando el SKU en su lugar.

    2. Índice sobre `lower(descripcion)`, que es exactamente la expresión
       por la que ordena `listar_variantes`. Con unos pocos miles de
       productos, sin él cada página obliga a ordenar el catálogo entero
       antes de quedarse con 50 filas.
    """
    # Las filas viejas sin descripción se completan con el SKU, que es lo
    # que la pantalla venía mostrando para ellas: no aparece nada nuevo ni
    # se pierde nada. También los vacíos, que son NULL disfrazados.
    op.execute(
        """
        UPDATE productos
        SET descripcion = sku
        WHERE descripcion IS NULL OR btrim(descripcion) = ''
        """
    )

    op.execute("ALTER TABLE productos ALTER COLUMN descripcion SET NOT NULL")

    # El índice va sobre la MISMA expresión del ORDER BY —con `lower`— o el
    # planificador no lo usa. PostgreSQL 13+ además puede completar el
    # segundo criterio (el código de la variante) con un incremental sort,
    # así que la consulta paginada no necesita ordenar todo el catálogo.
    op.execute(
        "CREATE INDEX ix_productos_descripcion_lower ON productos (lower(descripcion))"
    )


def downgrade() -> None:
    """
    Vuelve a permitir NULL, pero NO restaura los que se completaron con el
    SKU: no hay forma de distinguirlos de los que legítimamente se llaman
    igual que su código.
    """
    op.execute("DROP INDEX IF EXISTS ix_productos_descripcion_lower")
    op.execute("ALTER TABLE productos ALTER COLUMN descripcion DROP NOT NULL")
