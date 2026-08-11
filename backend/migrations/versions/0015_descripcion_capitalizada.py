"""Primera letra de la descripción del producto en mayúscula

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Deja en mayúscula la inicial de las descripciones que ya están cargadas.

    Desde ahora lo hace `_validar_descripcion` en cada alta y cada edición;
    esto es para las filas anteriores, que si no quedarían mezcladas con las
    nuevas en el mismo listado.

    **Solo el primer carácter**, igual que `capitalizar_inicial` en
    `app/core/utils.py`: `initcap()` bajaría el resto y arruinaría
    "Anillo de PLATA 925". Las que arrancan con un número no cambian, porque
    `upper()` sobre un dígito no hace nada.

    No hace falta tocar `ix_productos_descripcion_lower`: el índice es sobre
    `lower(descripcion)` y cambiar la caja de la inicial no cambia ese valor,
    así que el orden alfabético del listado queda igual. La búsqueda tampoco
    se ve afectada: filtra con `ilike`.
    """
    # El WHERE deja afuera las que ya están bien: sin él se reescribiría la
    # tabla entera para corregir unas pocas.
    op.execute(
        """
        UPDATE productos
        SET descripcion = upper(left(descripcion, 1)) || substr(descripcion, 2)
        WHERE descripcion <> upper(left(descripcion, 1)) || substr(descripcion, 2)
        """
    )


def downgrade() -> None:
    """
    No devuelve la minúscula: no hay forma de distinguir la descripción que
    esta migración corrigió de la que siempre estuvo en mayúscula. Bajar
    todas sería peor que dejarlas como están.

    Mismo criterio que el downgrade de 0012, que tampoco restaura las
    descripciones que completó con el SKU.
    """
    pass
