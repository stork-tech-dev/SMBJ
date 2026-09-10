"""Motivos: nota, vigencia y restricciones. Nota en Promociones.

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-10

- `promociones.nota`       VARCHAR(500) nullable — texto libre con explicación
- `motivos_descuento.nota` VARCHAR(500) nullable — ídem para motivos
- `motivos_descuento.fecha_inicio` DATE nullable — vigencia opcional
- `motivos_descuento.fecha_fin`    DATE nullable — ídem
- `motivo_restriccion` — tabla de restricciones de sucursal / medio de pago
  (mismo patrón que `promocion_alcance`, tipo como CHECK en lugar de enum)
"""

from alembic import op
import sqlalchemy as sa

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Columnas nuevas en promociones
    op.add_column("promociones", sa.Column("nota", sa.String(500), nullable=True))

    # 2. Columnas nuevas en motivos_descuento
    op.add_column("motivos_descuento", sa.Column("nota", sa.String(500), nullable=True))
    op.add_column("motivos_descuento", sa.Column("fecha_inicio", sa.Date(), nullable=True))
    op.add_column("motivos_descuento", sa.Column("fecha_fin", sa.Date(), nullable=True))

    op.create_check_constraint(
        "ck_motivos_descuento_vigencia_coherente",
        "motivos_descuento",
        "fecha_inicio IS NULL OR fecha_fin IS NULL OR fecha_inicio <= fecha_fin",
    )

    # 3. Tabla de restricciones de motivos (sucursal / medio de pago)
    op.create_table(
        "motivo_restriccion",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "motivo_id",
            sa.BigInteger(),
            sa.ForeignKey("motivos_descuento.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # 'punto_de_venta' | 'medio_de_pago'
        sa.Column("tipo", sa.String(20), nullable=False),
        # referencia_id al PuntoDeVenta o MedioDePago
        sa.Column("referencia_id", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("motivo_id", "tipo", "referencia_id", name="uq_motivo_restriccion"),
        sa.CheckConstraint(
            "tipo IN ('punto_de_venta', 'medio_de_pago')",
            name="ck_motivo_restriccion_tipo",
        ),
    )


def downgrade() -> None:
    op.drop_table("motivo_restriccion")
    op.drop_constraint("ck_motivos_descuento_vigencia_coherente", "motivos_descuento", type_="check")
    op.drop_column("motivos_descuento", "fecha_fin")
    op.drop_column("motivos_descuento", "fecha_inicio")
    op.drop_column("motivos_descuento", "nota")
    op.drop_column("promociones", "nota")
