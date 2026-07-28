"""Puntos de venta y dispositivos

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    tipo_enum = postgresql.ENUM(
        "cd", "local", "online", name="tipo_punto_venta", create_type=False
    )
    sa.Enum("cd", "local", "online", name="tipo_punto_venta").create(
        op.get_bind(), checkfirst=True
    )

    op.create_table(
        "puntos_de_venta",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(length=150), nullable=False),
        sa.Column("tipo", tipo_enum, nullable=False),
        sa.Column("codigo_confirmacion", sa.String(length=4), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_puntos_de_venta_nombre", "puntos_de_venta", ["nombre"])
    op.create_index("ix_puntos_de_venta_tipo", "puntos_de_venta", ["tipo"])

    # gen_random_uuid() es núcleo de PostgreSQL desde la versión 13, así que
    # no hace falta habilitar ninguna extensión (estamos en PG 15).
    op.create_table(
        "dispositivos",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "uuid",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("fingerprint", sa.String(length=128), nullable=True),
        sa.Column("punto_de_venta_id", sa.BigInteger(), nullable=True),
        sa.Column("descripcion", sa.String(length=150), server_default="Sin asignar", nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("fecha_alta", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("ultimo_acceso", sa.DateTime(), nullable=True),
        sa.Column("ultima_ip", sa.String(length=45), nullable=True),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["punto_de_venta_id"], ["puntos_de_venta.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    # unique=True + index=True en el modelo = un único índice único.
    op.create_index("ix_dispositivos_uuid", "dispositivos", ["uuid"], unique=True)
    op.create_index("ix_dispositivos_fingerprint", "dispositivos", ["fingerprint"])
    op.create_index("ix_dispositivos_punto_de_venta_id", "dispositivos", ["punto_de_venta_id"])


def downgrade() -> None:
    op.drop_table("dispositivos")
    op.drop_table("puntos_de_venta")
    sa.Enum(name="tipo_punto_venta").drop(op.get_bind(), checkfirst=True)
