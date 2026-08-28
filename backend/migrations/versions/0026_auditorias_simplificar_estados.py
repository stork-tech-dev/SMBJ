"""Simplificar estados de auditoría: en_curso + cerrada

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-28

Se elimina la instancia de aprobación intermedia. El conteo pasa
directamente de "en_curso" a "cerrada" (que aplica el ajuste de stock).

- Renombra 'aprobada' → 'cerrada' en los registros existentes.
- Elimina los valores 'pendiente_aprobacion' y 'rechazada' del enum.
- Elimina las columnas 'aprobada_por' y 'fecha_aprobacion'.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Convertir la columna a text para poder manipular los valores
    #    libremente. PostgreSQL no soporta DROP VALUE de un enum.
    #    El server_default depende del tipo, hay que quitarlo primero.
    op.execute("ALTER TABLE auditorias_inventario ALTER COLUMN estado DROP DEFAULT")
    op.execute("ALTER TABLE auditorias_inventario ALTER COLUMN estado TYPE text")
    op.execute("DROP TYPE estado_auditoria_inventario")

    # 2. Renombrar los estados viejos al nuevo valor.
    op.execute("""
        UPDATE auditorias_inventario
        SET estado = 'cerrada'
        WHERE estado IN ('aprobada', 'pendiente_aprobacion', 'rechazada')
    """)

    # 3. Recrear el enum con solo los dos valores nuevos.
    op.execute("""
        CREATE TYPE estado_auditoria_inventario AS ENUM ('en_curso', 'cerrada')
    """)
    op.execute("""
        ALTER TABLE auditorias_inventario
        ALTER COLUMN estado TYPE estado_auditoria_inventario
        USING estado::estado_auditoria_inventario
    """)
    op.execute("""
        ALTER TABLE auditorias_inventario
        ALTER COLUMN estado SET DEFAULT 'en_curso'
    """)

    # 4. Eliminar columnas de aprobación.
    op.drop_column("auditorias_inventario", "fecha_aprobacion")
    op.drop_column("auditorias_inventario", "aprobada_por")


def downgrade() -> None:
    # Agregar las columnas de aprobación.
    op.add_column(
        "auditorias_inventario",
        sa.Column("aprobada_por", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "auditorias_inventario",
        sa.Column("fecha_aprobacion", sa.DateTime(), nullable=True),
    )

    # Restaurar el enum con los cuatro valores originales.
    op.execute("ALTER TABLE auditorias_inventario ALTER COLUMN estado TYPE text")
    op.execute("DROP TYPE estado_auditoria_inventario")
    op.execute("""
        CREATE TYPE estado_auditoria_inventario
        AS ENUM ('en_curso', 'pendiente_aprobacion', 'aprobada', 'rechazada')
    """)
    op.execute("""
        UPDATE auditorias_inventario
        SET estado = 'aprobada'
        WHERE estado = 'cerrada'
    """)
    op.execute("""
        ALTER TABLE auditorias_inventario
        ALTER COLUMN estado TYPE estado_auditoria_inventario
        USING estado::estado_auditoria_inventario
    """)
