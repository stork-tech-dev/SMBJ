"""La tabla `variantes` pasa a llamarse `producto_variantes`

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-14
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (nombre viejo, nombre nuevo) de todo lo que lleva el nombre de la tabla en
# el suyo. Postgres NO los renombra solo al renombrar la tabla: quedarían
# índices `ix_variantes_*` sobre una tabla que ya no se llama así, y la
# próxima migración que los busque por nombre no los encontraría.
INDICES = [
    ("ix_variantes_producto_id", "ix_producto_variantes_producto_id"),
    ("ix_variantes_codigo_completo", "ix_producto_variantes_codigo_completo"),
    ("uq_variantes_sufijo_por_producto", "uq_producto_variantes_sufijo_por_producto"),
    ("variantes_pkey", "producto_variantes_pkey"),
]

RESTRICCIONES = [
    ("ck_variantes_base_sin_sufijo", "ck_producto_variantes_base_sin_sufijo"),
    (
        "ck_variantes_base_sin_descripcion_sufijo",
        "ck_producto_variantes_base_sin_descripcion_sufijo",
    ),
    (
        "ck_variantes_stock_minimo_no_negativo",
        "ck_producto_variantes_stock_minimo_no_negativo",
    ),
    ("ck_variantes_precio_usd_positivo", "ck_producto_variantes_precio_usd_positivo"),
    ("ck_variantes_precio_completo", "ck_producto_variantes_precio_completo"),
    ("variantes_producto_id_fkey", "producto_variantes_producto_id_fkey"),
]


def upgrade() -> None:
    """
    `variantes` a secas no decía de qué: el esquema ya tiene `producto_fotos`
    y va a tener tablas de stock, y "variante" suelto no se ata a nada. El
    prefijo la agrupa con su producto, igual que las fotos.

    En plural, como las otras 17 tablas del esquema.

    Se renombran también los índices y las restricciones: Postgres los deja
    con el nombre viejo al renombrar la tabla, y un `ix_variantes_*` colgando
    de `producto_variantes` es una pista falsa para el que venga después.

    **La auditoría no se toca.** `entidad` pasa a escribirse
    `"producto_variantes"` de acá en adelante, pero las filas ya escritas
    siguen diciendo `"variantes"` y así se quedan: la tabla es append-only
    por trigger (migración 0001) y no admite UPDATE ni siquiera desde una
    migración. Una consulta del historial completo de variantes tiene que
    buscar por los dos nombres, y ese corte está en el commit que introdujo
    este cambio.
    """
    op.execute("ALTER TABLE variantes RENAME TO producto_variantes")

    for viejo, nuevo in INDICES:
        op.execute(f"ALTER INDEX IF EXISTS {viejo} RENAME TO {nuevo}")

    for viejo, nuevo in RESTRICCIONES:
        op.execute(f"ALTER TABLE producto_variantes RENAME CONSTRAINT {viejo} TO {nuevo}")


def downgrade() -> None:
    """Vuelve al nombre anterior, con sus índices y restricciones."""
    for viejo, nuevo in RESTRICCIONES:
        op.execute(f"ALTER TABLE producto_variantes RENAME CONSTRAINT {nuevo} TO {viejo}")

    for viejo, nuevo in INDICES:
        op.execute(f"ALTER INDEX IF EXISTS {nuevo} RENAME TO {viejo}")

    op.execute("ALTER TABLE producto_variantes RENAME TO variantes")
