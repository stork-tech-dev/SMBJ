"""Anulaciones y cambios de producto

Revision ID: 0029
Revises: 0027
Create Date: 2026-09-07

Agrega `codigo_cambio_activo` a la tabla `ventas` y crea las tablas del
módulo de cambios: `cambios`, `cambio_items_devueltos`, `cambio_items_nuevos`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── ventas: marcar si el código de cambio sigue activo ─────────────────
    op.add_column(
        "ventas",
        sa.Column(
            "codigo_cambio_activo",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
    )

    # ── enums ───────────────────────────────────────────────────────────────
    sa.Enum(
        "comun", "promocion", "falla", "gift_card_fisica",
        name="tipo_cambio",
    ).create(op.get_bind(), checkfirst=True)

    sa.Enum(
        "pendiente", "confirmado", "cancelado",
        name="estado_cambio",
    ).create(op.get_bind(), checkfirst=True)

    # ── cambios ─────────────────────────────────────────────────────────────
    op.create_table(
        "cambios",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "tipo",
            postgresql.ENUM(
                "comun", "promocion", "falla", "gift_card_fisica",
                name="tipo_cambio", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("venta_origen_id", sa.BigInteger(), nullable=True),
        sa.Column("punto_de_venta_id", sa.BigInteger(), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("autorizador_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "estado",
            postgresql.ENUM(
                "pendiente", "confirmado", "cancelado",
                name="estado_cambio", create_type=False,
            ),
            server_default="pendiente",
            nullable=False,
        ),
        sa.Column(
            "diferencia",
            sa.Numeric(10, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column("medio_pago_diferencia_id", sa.BigInteger(), nullable=True),
        sa.Column("plan_cuotas_diferencia_id", sa.BigInteger(), nullable=True),
        sa.Column("codigo_cambio_nuevo", sa.String(length=8), nullable=True),
        sa.Column(
            "contador_cambios_previos",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("contador_cambios_previos >= 0", name="ck_cambios_contador_no_negativo"),
        sa.ForeignKeyConstraint(["venta_origen_id"], ["ventas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["punto_de_venta_id"], ["puntos_de_venta.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["autorizador_id"], ["usuarios.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["medio_pago_diferencia_id"], ["medios_de_pago.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["plan_cuotas_diferencia_id"], ["planes_cuotas.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codigo_cambio_nuevo", name="uq_cambios_codigo_nuevo"),
    )
    op.create_index("ix_cambios_tipo", "cambios", ["tipo"])
    op.create_index("ix_cambios_estado", "cambios", ["estado"])
    op.create_index("ix_cambios_venta_origen", "cambios", ["venta_origen_id"])
    op.create_index("ix_cambios_punto_de_venta", "cambios", ["punto_de_venta_id"])
    op.create_index("ix_cambios_usuario", "cambios", ["usuario_id"])
    op.create_index("ix_cambios_created_at", "cambios", ["created_at"])

    # ── cambio_items_devueltos ───────────────────────────────────────────────
    op.create_table(
        "cambio_items_devueltos",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("cambio_id", sa.BigInteger(), nullable=False),
        sa.Column("venta_item_id", sa.BigInteger(), nullable=True),
        sa.Column("variante_id", sa.BigInteger(), nullable=False),
        sa.Column("precio_reconocido", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "en_promocion",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "tipo_promo",
            postgresql.ENUM(
                "dos_x_uno", "tres_x_dos",
                name="tipo_promocion", create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("material_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("precio_reconocido >= 0", name="ck_cambio_devueltos_precio_no_negativo"),
        sa.ForeignKeyConstraint(["cambio_id"], ["cambios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["venta_item_id"], ["venta_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["variante_id"], ["producto_variantes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["material_id"], ["categorias.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cambio_devueltos_cambio", "cambio_items_devueltos", ["cambio_id"])
    op.create_index("ix_cambio_devueltos_variante", "cambio_items_devueltos", ["variante_id"])

    # ── cambio_items_nuevos ─────────────────────────────────────────────────
    op.create_table(
        "cambio_items_nuevos",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("cambio_id", sa.BigInteger(), nullable=False),
        sa.Column("variante_id", sa.BigInteger(), nullable=False),
        sa.Column("precio_actual", sa.Numeric(10, 2), nullable=False),
        sa.Column("material_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("precio_actual >= 0", name="ck_cambio_nuevos_precio_no_negativo"),
        sa.ForeignKeyConstraint(["cambio_id"], ["cambios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["variante_id"], ["producto_variantes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["material_id"], ["categorias.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cambio_nuevos_cambio", "cambio_items_nuevos", ["cambio_id"])
    op.create_index("ix_cambio_nuevos_variante", "cambio_items_nuevos", ["variante_id"])


def downgrade() -> None:
    op.drop_table("cambio_items_nuevos")
    op.drop_table("cambio_items_devueltos")
    op.drop_table("cambios")

    for nombre in ("tipo_cambio", "estado_cambio"):
        op.execute(f"DROP TYPE IF EXISTS {nombre}")

    op.drop_column("ventas", "codigo_cambio_activo")
