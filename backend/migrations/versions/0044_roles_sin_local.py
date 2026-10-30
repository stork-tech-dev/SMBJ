"""Dueño y Cuenta Maestra sin local asignado.

Revision ID: 0044
Revises: 0043
Create Date: 2026-10-29

Desde ahora los usuarios dueño y cuenta_maestra no tienen Punto de Venta
asignado (la regla vive en `services/usuarios.py`). Limpia los que ya lo
tenían cargado.
"""

from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE usuarios SET local_asignado_id = NULL
        WHERE local_asignado_id IS NOT NULL
          AND rol_id IN (SELECT id FROM roles WHERE nombre IN ('dueno', 'cuenta_maestra'))
        """
    )


def downgrade() -> None:
    # No hay forma de saber qué local tenía cada uno: no se restaura nada.
    pass
