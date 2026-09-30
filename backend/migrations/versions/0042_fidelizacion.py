"""Fidelización: categorías por puntos y descuento en el mes del cumpleaños.

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-30

- `clientes.fecha_nacimiento`: opcional. Sin fecha no hay beneficio.
- `categorias_fidelizacion`: rangos de puntos acumulados (históricos, sin
  restar canjes) con el % de descuento que la categoría recibe en el mes de
  su cumpleaños. Nace vacía: nada cambia hasta que la Cuenta Maestra las
  cargue en Ajustes.
- `motivos_descuento.es_descuento_cumpleanos`: el motivo al que apuntan los
  ítems con el descuento automático (uno solo, índice único parcial). Se
  marca el "Cumpleaños" existente o se crea.
- `ventas.sin_descuento_cumpleanos`: la vendedora puede quitar el beneficio
  en una venta puntual.
- `venta_items.descuento_automatico`: el descuento lo puso el sistema. El
  recálculo solo rehace esos, así un "Cumpleaños" elegido a mano se respeta.
"""

import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clientes", sa.Column("fecha_nacimiento", sa.Date(), nullable=True))

    op.create_table(
        "categorias_fidelizacion",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("nombre", sa.String(50), nullable=False, unique=True),
        sa.Column("puntos_desde", sa.Integer(), nullable=False, unique=True),
        sa.Column("porcentaje_cumpleanos", sa.Numeric(5, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("puntos_desde >= 0", name="ck_categorias_fidelizacion_puntos"),
        sa.CheckConstraint(
            "porcentaje_cumpleanos >= 0 AND porcentaje_cumpleanos <= 100",
            name="ck_categorias_fidelizacion_porcentaje",
        ),
    )

    op.add_column(
        "motivos_descuento",
        sa.Column("es_descuento_cumpleanos", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index(
        "uq_motivos_descuento_cumpleanos",
        "motivos_descuento",
        ["es_descuento_cumpleanos"],
        unique=True,
        postgresql_where=sa.text("es_descuento_cumpleanos"),
    )
    # El motivo de los descuentos automáticos: el "Cumpleaños" que ya exista
    # (comparado sin tildes ni mayúsculas) o uno nuevo.
    op.execute(
        """
        UPDATE motivos_descuento SET es_descuento_cumpleanos = true
         WHERE id = (SELECT id FROM motivos_descuento
                      WHERE translate(lower(nombre), 'áéíóúñ', 'aeioun') = 'cumpleanos'
                      ORDER BY id LIMIT 1)
        """
    )
    op.execute(
        """
        INSERT INTO motivos_descuento (nombre, nota, es_descuento_cumpleanos, activo)
        SELECT 'Cumpleaños',
               'Descuento automático del mes del cumpleaños según la categoría de fidelización.',
               true, true
         WHERE NOT EXISTS (SELECT 1 FROM motivos_descuento WHERE es_descuento_cumpleanos)
        """
    )

    op.add_column(
        "ventas",
        sa.Column("sin_descuento_cumpleanos", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "venta_items",
        sa.Column("descuento_automatico", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("venta_items", "descuento_automatico")
    op.drop_column("ventas", "sin_descuento_cumpleanos")
    op.drop_index("uq_motivos_descuento_cumpleanos", table_name="motivos_descuento")
    op.drop_column("motivos_descuento", "es_descuento_cumpleanos")
    op.drop_table("categorias_fidelizacion")
    op.drop_column("clientes", "fecha_nacimiento")
