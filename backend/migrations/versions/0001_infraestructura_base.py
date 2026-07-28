"""Infraestructura base: auditoria, configuracion_sistema, motivos_baja

Revision ID: 0001
Revises:
Create Date: 2026-07-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- Guardia de inmutabilidad de la tabla auditoria (Principio 3) ---
#
# La garantía vive en la base, no en el código. Se usan dos capas:
#
# 1. Un trigger a nivel de sentencia (STATEMENT) que aborta cualquier
#    UPDATE o DELETE. Se dispara incluso cuando la sentencia no afecta
#    ninguna fila, y no se puede eludir ni siquiera desde un superusuario.
# 2. REVOKE de UPDATE/DELETE/TRUNCATE al rol de la aplicación. Es defensa
#    en profundidad: si el rol de la app es superusuario (caso del
#    docker-compose de desarrollo) PostgreSQL ignora el chequeo de
#    permisos, y por eso el trigger es la protección que realmente cuenta.

SQL_FUNCION_GUARDIA = """
CREATE OR REPLACE FUNCTION auditoria_bloquear_modificacion()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'La tabla auditoria es de solo inserción (append-only): % no permitido',
        TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;
"""

SQL_TRIGGERS = """
CREATE TRIGGER trg_auditoria_no_update
    BEFORE UPDATE ON auditoria
    EXECUTE FUNCTION auditoria_bloquear_modificacion();

CREATE TRIGGER trg_auditoria_no_delete
    BEFORE DELETE ON auditoria
    EXECUTE FUNCTION auditoria_bloquear_modificacion();

CREATE TRIGGER trg_auditoria_no_truncate
    BEFORE TRUNCATE ON auditoria
    EXECUTE FUNCTION auditoria_bloquear_modificacion();
"""

SQL_REVOKE = """
DO $$
BEGIN
    EXECUTE format(
        'REVOKE UPDATE, DELETE, TRUNCATE ON TABLE auditoria FROM %I',
        current_user
    );
END;
$$;
"""


def upgrade() -> None:
    # ------------------------------------------------------------------
    # auditoria
    # ------------------------------------------------------------------
    op.create_table(
        "auditoria",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=True),
        sa.Column("accion", sa.String(length=100), nullable=False),
        sa.Column("entidad", sa.String(length=100), nullable=False),
        sa.Column("entidad_id", sa.BigInteger(), nullable=True),
        sa.Column("estado_anterior", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("estado_nuevo", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_origen", sa.String(length=45), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auditoria_usuario_id", "auditoria", ["usuario_id"])
    op.create_index("ix_auditoria_accion", "auditoria", ["accion"])
    op.create_index("ix_auditoria_entidad", "auditoria", ["entidad"])
    op.create_index("ix_auditoria_timestamp", "auditoria", ["timestamp"])
    op.create_index("ix_auditoria_entidad_entidad_id", "auditoria", ["entidad", "entidad_id"])

    op.execute(SQL_FUNCION_GUARDIA)
    op.execute(SQL_TRIGGERS)
    op.execute(SQL_REVOKE)

    # ------------------------------------------------------------------
    # configuracion_sistema
    # ------------------------------------------------------------------
    op.create_table(
        "configuracion_sistema",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("redondeo", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("descuento_maximo", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column(
            "metodo_descuento",
            sa.String(length=20),
            server_default="encadenado",
            nullable=False,
        ),
        sa.Column("letra_empresa", sa.String(length=1), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # FK a usuarios: se agrega recién en el módulo 02, cuando la
        # tabla usuarios existe.
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("letra_empresa IN ('S', 'M')", name="ck_config_letra_empresa"),
        sa.CheckConstraint(
            "metodo_descuento IN ('encadenado', 'sumado')",
            name="ck_config_metodo_descuento",
        ),
        sa.CheckConstraint(
            "descuento_maximo >= 0 AND descuento_maximo <= 100",
            name="ck_config_descuento_maximo",
        ),
    )

    # ------------------------------------------------------------------
    # motivos_baja — catálogo que necesita el seed inicial
    # ------------------------------------------------------------------
    op.create_table(
        "motivos_baja",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre", name="uq_motivos_baja_nombre"),
    )


def downgrade() -> None:
    op.drop_table("motivos_baja")
    op.drop_table("configuracion_sistema")

    op.execute("DROP TRIGGER IF EXISTS trg_auditoria_no_truncate ON auditoria")
    op.execute("DROP TRIGGER IF EXISTS trg_auditoria_no_delete ON auditoria")
    op.execute("DROP TRIGGER IF EXISTS trg_auditoria_no_update ON auditoria")
    op.execute("DROP FUNCTION IF EXISTS auditoria_bloquear_modificacion()")

    op.drop_index("ix_auditoria_entidad_entidad_id", table_name="auditoria")
    op.drop_index("ix_auditoria_timestamp", table_name="auditoria")
    op.drop_index("ix_auditoria_entidad", table_name="auditoria")
    op.drop_index("ix_auditoria_accion", table_name="auditoria")
    op.drop_index("ix_auditoria_usuario_id", table_name="auditoria")
    op.drop_table("auditoria")
