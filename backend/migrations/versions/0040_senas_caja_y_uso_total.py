"""Señas: entran a la caja, vencen y se usan enteras.

Revision ID: 0040
Revises: 0039
Create Date: 2026-09-29

- `senas` guarda con qué medio se pagó, en qué turno y local entró la plata
  (para que el arqueo la cuente) y la fecha en que vence. Las tres primeras
  son NULL en las señas anteriores: se registraron sin caja.
- `vence_el` se persiste: cambiar la vigencia no tiene que alargar ni acortar
  las señas ya entregadas. Las existentes se completan con la regla que
  usaba el reporte (alta + vigencia configurada).
- `venta_pagos.sena_consumido`: cuánto se descontó del saldo de la seña. Con
  el uso total puede ser más que `monto` (la diferencia se pierde), y la
  anulación necesita saberlo para devolverla entera.
- La vigencia pasa de 30 a 60 días.
"""

import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "senas",
        sa.Column(
            "medio_de_pago_id",
            sa.BigInteger(),
            sa.ForeignKey("medios_de_pago.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "senas",
        sa.Column(
            "turno_id",
            sa.BigInteger(),
            sa.ForeignKey("turnos.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "senas",
        sa.Column(
            "punto_de_venta_id",
            sa.BigInteger(),
            sa.ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_senas_turno_id", "senas", ["turno_id"])
    op.create_index("ix_senas_punto_de_venta_id", "senas", ["punto_de_venta_id"])

    # La vigencia nueva primero: las señas existentes vencen con la de hoy.
    op.alter_column("configuracion_sistema", "dias_vigencia_sena", server_default="60")
    op.execute("UPDATE configuracion_sistema SET dias_vigencia_sena = 60 WHERE dias_vigencia_sena = 30")

    op.add_column("senas", sa.Column("vence_el", sa.Date(), nullable=True))
    op.execute(
        """
        UPDATE senas
           SET vence_el = created_at::date
                          + COALESCE((SELECT dias_vigencia_sena FROM configuracion_sistema LIMIT 1), 60)
        """
    )
    op.alter_column("senas", "vence_el", nullable=False)
    op.create_index("ix_senas_vence_el", "senas", ["vence_el"])

    op.add_column(
        "venta_pagos", sa.Column("sena_consumido", sa.Numeric(10, 2), nullable=True)
    )
    op.create_check_constraint(
        "ck_venta_pagos_sena_consumido",
        "venta_pagos",
        "sena_consumido IS NULL OR (sena_id IS NOT NULL AND sena_consumido >= monto)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_venta_pagos_sena_consumido", "venta_pagos", type_="check")
    op.drop_column("venta_pagos", "sena_consumido")
    op.drop_index("ix_senas_vence_el", table_name="senas")
    op.drop_column("senas", "vence_el")
    op.execute("UPDATE configuracion_sistema SET dias_vigencia_sena = 30 WHERE dias_vigencia_sena = 60")
    op.alter_column("configuracion_sistema", "dias_vigencia_sena", server_default="30")
    op.drop_index("ix_senas_punto_de_venta_id", table_name="senas")
    op.drop_index("ix_senas_turno_id", table_name="senas")
    op.drop_column("senas", "punto_de_venta_id")
    op.drop_column("senas", "turno_id")
    op.drop_column("senas", "medio_de_pago_id")
