"""Promociones: tipo porcentaje y nuevos alcances (PdV, MedioPago, Todos).

Revision ID: 0029
Revises: 0027
Create Date: 2026-09-10

`ALTER TYPE ... ADD VALUE` no puede ejecutarse dentro de una transacción en
PostgreSQL < 12, y en versiones ≥ 12 tiene la restricción de que el nuevo
valor no puede usarse en la misma transacción. Por eso la migración se marca
como non-transactional para los enum-alters y solo la DDL de columna y
constraint corre en la transacción principal.
"""

from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL ≥ 12: ALTER TYPE ADD VALUE se puede ejecutar dentro de una
    # transacción. La restricción es que el valor nuevo no puede USARSE en la
    # misma transacción, pero acá solo agregamos una columna INTEGER, así que
    # no hay problema. En PG < 12 esta sentencia fallaría; Railway y el dev
    # usan PG 15, así que es seguro.
    op.execute(sa.text("ALTER TYPE tipo_promocion ADD VALUE IF NOT EXISTS 'porcentaje'"))
    op.execute(sa.text("ALTER TYPE tipo_alcance_promocion ADD VALUE IF NOT EXISTS 'todos_productos'"))
    op.execute(sa.text("ALTER TYPE tipo_alcance_promocion ADD VALUE IF NOT EXISTS 'todos_categorias'"))
    op.execute(sa.text("ALTER TYPE tipo_alcance_promocion ADD VALUE IF NOT EXISTS 'punto_de_venta'"))
    op.execute(sa.text("ALTER TYPE tipo_alcance_promocion ADD VALUE IF NOT EXISTS 'medio_de_pago'"))

    op.add_column(
        "promociones",
        sa.Column("porcentaje_descuento", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_promociones_porcentaje_rango",
        "promociones",
        "porcentaje_descuento IS NULL OR "
        "(porcentaje_descuento >= 1 AND porcentaje_descuento <= 75)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_promociones_porcentaje_rango", "promociones", type_="check"
    )
    op.drop_column("promociones", "porcentaje_descuento")
    # Los enums de PostgreSQL no permiten eliminar valores una vez agregados
    # sin recrear el tipo. El downgrade no los revierte.
