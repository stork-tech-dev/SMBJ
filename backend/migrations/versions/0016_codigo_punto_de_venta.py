"""El código del punto de venta pasa a ser su abreviatura

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    `codigo_confirmacion` se reconvierte en `codigo`: la abreviatura corta y
    estable del punto de venta ("MPO" para Patio Olmos, "MTO" para Tienda
    Online), que se muestra como primera columna y a futuro identificará los
    reportes.

    **El uso anterior queda sin efecto por decisión explícita.** El campo era
    el código con el que un local confirmaba la recepción de un envío del CD
    —un secreto, diseñado en `prompts/05_stock.md`—, y un valor visible en la
    primera columna no puede cumplir esa función. Cómo se confirma una
    recepción se define cuando se construya el módulo de stock. Hoy no se
    rompe nada: ese módulo no existe y la columna está entera en NULL.
    """
    op.execute("ALTER TABLE puntos_de_venta RENAME COLUMN codigo_confirmacion TO codigo")

    # Se ensancha ANTES de cargar los datos: "MPO2" no entra en 4 caracteres.
    op.execute("ALTER TABLE puntos_de_venta ALTER COLUMN codigo TYPE varchar(6)")

    # Se completa por NOMBRE y no por id, que depende del orden de carga.
    #
    # El ELSE cubre cualquier fila que no sea de esta base: sin él, el SET NOT
    # NULL de abajo fallaría en cualquier otra instalación. 'PV' || id es feo
    # a propósito — se ve que hay que corregirlo a mano.
    op.execute(
        """
        UPDATE puntos_de_venta
        SET codigo = CASE nombre
            WHEN 'CD Central'        THEN 'MCD'
            WHEN 'Local Patio Olmos' THEN 'MPO'
            WHEN 'Paseo del Jockey'  THEN 'MPJ'
            WHEN 'Patio Olmos'       THEN 'MPO2'
            WHEN 'Tienda Online'     THEN 'MTO'
            ELSE 'PV' || id
        END
        WHERE codigo IS NULL OR btrim(codigo) = ''
        """
    )

    op.execute("ALTER TABLE puntos_de_venta ALTER COLUMN codigo SET NOT NULL")

    # Único: si el código va a identificar un reporte, dos puntos de venta con
    # el mismo valor lo vuelven ambiguo.
    op.execute(
        "CREATE UNIQUE INDEX ix_puntos_de_venta_codigo ON puntos_de_venta (codigo)"
    )


def downgrade() -> None:
    """
    Vuelve al nombre y al tipo anteriores.

    Los códigos cargados se pierden, y no hay nada que restaurar: la columna
    estaba entera en NULL antes de esta migración. El truncado a 4 caracteres
    lo hace explícito con un UPDATE previo, para que el ALTER no falle con
    "value too long".
    """
    op.execute("DROP INDEX IF EXISTS ix_puntos_de_venta_codigo")
    op.execute("ALTER TABLE puntos_de_venta ALTER COLUMN codigo DROP NOT NULL")
    op.execute("UPDATE puntos_de_venta SET codigo = NULL")
    op.execute("ALTER TABLE puntos_de_venta ALTER COLUMN codigo TYPE varchar(4)")
    op.execute("ALTER TABLE puntos_de_venta RENAME COLUMN codigo TO codigo_confirmacion")
