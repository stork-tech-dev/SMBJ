"""Mínimo online y mínimo 1 por defecto en todas las ubicaciones.

Revision ID: 0038
Revises: 0037
Create Date: 2026-09-28

- `stock.stock_minimo_online`: tercer mínimo, rige en los puntos de venta de
  tipo 'online' (antes usaban el de local).
- Los tres mínimos nacen en 1 (antes 0): todo producto avisa cuando falta en
  cualquier sucursal. Las Ubicaciones Especiales no llevan mínimo: la regla
  de qué mínimo rige les da 0 (ver `minimo_aplicable_sql`).
- Datos existentes: los mínimos en 0 pasan a 1 (los configurados > 0 no se
  tocan) y se crean las filas que falten de cada variante en los CD, online y
  locales activos, en cantidad 0.

El downgrade saca la columna y vuelve el default a 0, pero NO deshace el
completado de datos: no hay forma de distinguir un 1 puesto acá de uno cargado
a mano después.
"""

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE stock ADD COLUMN stock_minimo_online INTEGER NOT NULL DEFAULT 1"
    )
    op.execute("ALTER TABLE stock ALTER COLUMN stock_minimo_cd SET DEFAULT 1")
    op.execute("ALTER TABLE stock ALTER COLUMN stock_minimo_local SET DEFAULT 1")

    op.execute("ALTER TABLE stock DROP CONSTRAINT ck_stock_minimos_no_negativos")
    op.execute(
        "ALTER TABLE stock ADD CONSTRAINT ck_stock_minimos_no_negativos CHECK ("
        "stock_minimo_cd >= 0 AND stock_minimo_local >= 0 AND stock_minimo_online >= 0)"
    )

    op.execute("UPDATE stock SET stock_minimo_cd = 1 WHERE stock_minimo_cd = 0")
    op.execute("UPDATE stock SET stock_minimo_local = 1 WHERE stock_minimo_local = 0")

    op.execute(
        """
        INSERT INTO stock (variante_id, punto_de_venta_id, cantidad,
                           stock_minimo_cd, stock_minimo_local, stock_minimo_online,
                           updated_at)
        SELECT v.id, p.id, 0, 1, 1, 1, now()
        FROM producto_variantes v
        CROSS JOIN puntos_de_venta p
        WHERE p.activo AND p.tipo IN ('cd', 'online', 'local')
        ON CONFLICT ON CONSTRAINT uq_stock_variante_punto_de_venta DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE stock DROP CONSTRAINT ck_stock_minimos_no_negativos")
    op.execute(
        "ALTER TABLE stock ADD CONSTRAINT ck_stock_minimos_no_negativos CHECK ("
        "stock_minimo_cd >= 0 AND stock_minimo_local >= 0)"
    )
    op.execute("ALTER TABLE stock ALTER COLUMN stock_minimo_cd SET DEFAULT 0")
    op.execute("ALTER TABLE stock ALTER COLUMN stock_minimo_local SET DEFAULT 0")
    op.execute("ALTER TABLE stock DROP COLUMN stock_minimo_online")
