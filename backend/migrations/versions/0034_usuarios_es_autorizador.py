"""Usuarios: campo es_autorizador.

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-21

Lista de usuarios que pueden autorizar un cambio por falla, administrada
por Cuenta Maestra desde /usuarios (no un permiso del árbol de roles: es un
flag por usuario individual, puede ser cualquier rol). Reemplaza al recurso
`CAMBIO_FALLA_AUTORIZAR`, que nunca se llegó a validar en el service. Mismo
campo que va a reusar el día que se implemente el selector de autorizador
de Novedades de Caja (sesión 09).
"""

from alembic import op
import sqlalchemy as sa

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usuarios",
        sa.Column(
            "es_autorizador", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    op.drop_column("usuarios", "es_autorizador")
