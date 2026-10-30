"""Cambios con más de un ticket: tabla cambio_origenes.

Revision ID: 0048
Revises: 0047
Create Date: 2026-10-29

Un cambio puede juntar varios códigos de cambio (ventas o retiros de
mercadería) para que lo devuelto de todos sume. Los orígenes pasan de dos
columnas de `cambios` a la tabla `cambio_origenes`; los existentes se
migran y las columnas viejas se borran (una sola verdad).

`cambio_items_devueltos.retiro_mercaderia_id`: de qué retiro es la unidad
devuelta, ahora que puede haber más de uno. Se completa en los existentes.
"""

import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cambio_origenes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("cambio_id", sa.BigInteger(),
                  sa.ForeignKey("cambios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("venta_id", sa.BigInteger(),
                  sa.ForeignKey("ventas.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("retiro_mercaderia_id", sa.BigInteger(),
                  sa.ForeignKey("retiros_mercaderia.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("(venta_id IS NULL) <> (retiro_mercaderia_id IS NULL)",
                           name="ck_cambio_origenes_un_origen"),
        sa.UniqueConstraint("cambio_id", "venta_id", name="uq_cambio_origenes_venta"),
        sa.UniqueConstraint("cambio_id", "retiro_mercaderia_id", name="uq_cambio_origenes_retiro"),
    )
    op.create_index("ix_cambio_origenes_cambio_id", "cambio_origenes", ["cambio_id"])
    op.create_index("ix_cambio_origenes_venta_id", "cambio_origenes", ["venta_id"])
    op.create_index("ix_cambio_origenes_retiro_mercaderia_id", "cambio_origenes",
                    ["retiro_mercaderia_id"])

    op.add_column("cambio_items_devueltos", sa.Column(
        "retiro_mercaderia_id", sa.BigInteger(),
        sa.ForeignKey("retiros_mercaderia.id", ondelete="RESTRICT"), nullable=True,
    ))

    # Los orígenes de los cambios existentes.
    op.execute("""
        INSERT INTO cambio_origenes (cambio_id, venta_id, retiro_mercaderia_id, created_at)
        SELECT id, venta_origen_id, retiro_mercaderia_origen_id, created_at
        FROM cambios
        WHERE venta_origen_id IS NOT NULL OR retiro_mercaderia_origen_id IS NOT NULL
    """)
    op.execute("""
        UPDATE cambio_items_devueltos d
        SET retiro_mercaderia_id = c.retiro_mercaderia_origen_id
        FROM cambios c
        WHERE d.cambio_id = c.id AND c.retiro_mercaderia_origen_id IS NOT NULL
    """)

    op.drop_column("cambios", "retiro_mercaderia_origen_id")
    # Borrar la columna se lleva su índice (`ix_cambios_venta_origen`).
    op.drop_column("cambios", "venta_origen_id")


def downgrade() -> None:
    op.add_column("cambios", sa.Column(
        "venta_origen_id", sa.BigInteger(),
        sa.ForeignKey("ventas.id", ondelete="RESTRICT"), nullable=True,
    ))
    op.create_index("ix_cambios_venta_origen", "cambios", ["venta_origen_id"])
    op.add_column("cambios", sa.Column(
        "retiro_mercaderia_origen_id", sa.BigInteger(),
        sa.ForeignKey("retiros_mercaderia.id", ondelete="RESTRICT"), nullable=True,
    ))
    # Vuelve el PRIMER origen de cada cambio: los demás se pierden.
    op.execute("""
        UPDATE cambios c
        SET venta_origen_id = o.venta_id, retiro_mercaderia_origen_id = o.retiro_mercaderia_id
        FROM (
            SELECT DISTINCT ON (cambio_id) cambio_id, venta_id, retiro_mercaderia_id
            FROM cambio_origenes ORDER BY cambio_id, id
        ) o
        WHERE o.cambio_id = c.id
    """)
    op.drop_column("cambio_items_devueltos", "retiro_mercaderia_id")
    op.drop_table("cambio_origenes")
