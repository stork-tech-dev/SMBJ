"""Estacionalidad pasa a temporada: tres valores en vez de cinco estaciones

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-12
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    La mercadería se compra por temporada, no por estación: el rubro
    repone en Otoño-Invierno y en Primavera-Verano. Las cinco estaciones
    sueltas obligaban a elegir entre dos valores que significan lo mismo
    —¿un buzo es de otoño o de invierno?— y a filtrar dos veces para ver una
    temporada entera.

    Cambian las tres cosas de una: el nombre de la columna, el tipo ENUM y
    sus valores. Van juntas porque separar el renombre del cambio de tipo
    dejaría una migración intermedia donde `temporada` guarda estaciones.

    **Los datos se colapsan y no vuelven.** El mapeo es el único que
    conserva el significado:

        permanente            -> atemporal
        primavera, verano     -> primavera_verano
        otoño, invierno       -> otoño_invierno

    El ELSE cubre cualquier valor que no sea de esta base: sin él el ALTER
    fallaría en otra instalación. Cae a `atemporal`, que es el default y el
    valor que no afirma nada sobre el producto.
    """
    op.execute(
        "CREATE TYPE temporada_producto AS ENUM "
        "('atemporal', 'otoño_invierno', 'primavera_verano')"
    )

    # El default viejo referencia el tipo viejo: hay que soltarlo antes de
    # convertir la columna, o el ALTER TYPE falla al no poder castearlo.
    op.execute("ALTER TABLE productos ALTER COLUMN estacionalidad DROP DEFAULT")

    op.execute(
        """
        ALTER TABLE productos
        ALTER COLUMN estacionalidad TYPE temporada_producto
        USING (
            CASE estacionalidad::text
                WHEN 'permanente' THEN 'atemporal'
                WHEN 'primavera'  THEN 'primavera_verano'
                WHEN 'verano'     THEN 'primavera_verano'
                WHEN 'otoño'      THEN 'otoño_invierno'
                WHEN 'invierno'   THEN 'otoño_invierno'
                ELSE 'atemporal'
            END
        )::temporada_producto
        """
    )

    op.execute("ALTER TABLE productos ALTER COLUMN estacionalidad SET DEFAULT 'atemporal'")
    op.execute("ALTER TABLE productos RENAME COLUMN estacionalidad TO temporada")
    op.execute("ALTER INDEX ix_productos_estacionalidad RENAME TO ix_productos_temporada")

    op.execute("DROP TYPE estacionalidad_producto")


def downgrade() -> None:
    """
    Vuelve al nombre, al tipo y a los cinco valores anteriores.

    Lo que NO vuelve son los datos: `primavera_verano` había fusionado
    primavera con verano, y no hay forma de saber cuál era cada fila. Se
    elige la estación de cada par (`verano`, `invierno`) porque es la
    dominante en la compra; `atemporal` sí vuelve exacto a `permanente`.
    """
    op.execute(
        "CREATE TYPE estacionalidad_producto AS ENUM "
        "('permanente', 'verano', 'invierno', 'otoño', 'primavera')"
    )

    op.execute("ALTER TABLE productos ALTER COLUMN temporada DROP DEFAULT")

    op.execute(
        """
        ALTER TABLE productos
        ALTER COLUMN temporada TYPE estacionalidad_producto
        USING (
            CASE temporada::text
                WHEN 'atemporal'        THEN 'permanente'
                WHEN 'primavera_verano' THEN 'verano'
                WHEN 'otoño_invierno'   THEN 'invierno'
                ELSE 'permanente'
            END
        )::estacionalidad_producto
        """
    )

    op.execute("ALTER TABLE productos ALTER COLUMN temporada SET DEFAULT 'permanente'")
    op.execute("ALTER TABLE productos RENAME COLUMN temporada TO estacionalidad")
    op.execute("ALTER INDEX ix_productos_temporada RENAME TO ix_productos_estacionalidad")

    op.execute("DROP TYPE temporada_producto")
