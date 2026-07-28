"""Autenticación y usuarios: roles, usuarios, permisos, historial, sesiones

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# El historial de accesos es append-only igual que la auditoría, y por el
# mismo motivo: si se puede editar, no sirve como evidencia.
SQL_GUARDIA_HISTORIAL = """
CREATE OR REPLACE FUNCTION historial_bloquear_modificacion()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'historial_accesos es de solo inserción (append-only): % no permitido',
        TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

CREATE TRIGGER trg_historial_no_update
    BEFORE UPDATE ON historial_accesos
    EXECUTE FUNCTION historial_bloquear_modificacion();

CREATE TRIGGER trg_historial_no_delete
    BEFORE DELETE ON historial_accesos
    EXECUTE FUNCTION historial_bloquear_modificacion();
"""


def upgrade() -> None:
    # ------------------------------------------------------------------
    # roles
    # ------------------------------------------------------------------
    op.create_table(
        "roles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(length=50), nullable=False),
        sa.Column("descripcion", sa.String(length=255), nullable=True),
        sa.Column("es_sistema", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_roles_nombre", "roles", ["nombre"], unique=True)

    # ------------------------------------------------------------------
    # usuarios
    # ------------------------------------------------------------------
    op.create_table(
        "usuarios",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("nombre", sa.String(length=150), nullable=False),
        sa.Column("rol_id", sa.BigInteger(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("clave_especial_hash", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("ultimo_acceso", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["rol_id"], ["roles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_usuarios_email"),
    )
    op.create_index("ix_usuarios_username", "usuarios", ["username"], unique=True)
    op.create_index("ix_usuarios_rol_id", "usuarios", ["rol_id"])

    # Ahora que existe usuarios, se puede cerrar la FK que quedó pendiente
    # en configuracion_sistema desde la migración 0001.
    op.create_foreign_key(
        "fk_configuracion_updated_by_usuarios",
        "configuracion_sistema",
        "usuarios",
        ["updated_by"],
        ["id"],
        ondelete="SET NULL",
    )

    # ------------------------------------------------------------------
    # rol_permisos / usuario_permisos
    # ------------------------------------------------------------------
    for tabla, columna, referencia, nombre_uq in (
        ("rol_permisos", "rol_id", "roles.id", "uq_rol_permisos_rol_modulo_recurso"),
        ("usuario_permisos", "usuario_id", "usuarios.id", "uq_usuario_permisos_usuario_modulo_recurso"),
    ):
        op.create_table(
            tabla,
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column(columna, sa.BigInteger(), nullable=False),
            sa.Column("modulo", sa.String(length=50), nullable=False),
            sa.Column("recurso", sa.String(length=100), nullable=True),
            sa.Column("puede_ver", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("puede_crear", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("puede_editar", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("puede_eliminar", sa.Boolean(), server_default="false", nullable=False),
            sa.ForeignKeyConstraint([columna], [referencia], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            # PostgreSQL admite múltiples NULL en un UNIQUE: cada propietario
            # tiene una fila general por módulo (recurso=NULL) y N por recurso.
            sa.UniqueConstraint(columna, "modulo", "recurso", name=nombre_uq),
        )
        op.create_index(f"ix_{tabla}_{columna}", tabla, [columna])
        op.create_index(f"ix_{tabla}_modulo", tabla, ["modulo"])

    # ------------------------------------------------------------------
    # historial_accesos
    # ------------------------------------------------------------------
    # El tipo se crea explícitamente y se referencia con create_type=False:
    # si no, create_table intentaría crearlo de nuevo y falla.
    resultado_enum = postgresql.ENUM(
        "exitoso", "fallido", name="resultado_acceso", create_type=False
    )
    sa.Enum("exitoso", "fallido", name="resultado_acceso").create(op.get_bind(), checkfirst=True)

    op.create_table(
        "historial_accesos",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("ip_origen", sa.String(length=45), nullable=True),
        sa.Column("resultado", resultado_enum, nullable=False),
        sa.Column("detalle", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_historial_accesos_usuario_id", "historial_accesos", ["usuario_id"])
    op.create_index("ix_historial_accesos_timestamp", "historial_accesos", ["timestamp"])

    op.execute(SQL_GUARDIA_HISTORIAL)

    # ------------------------------------------------------------------
    # sesiones (refresh tokens revocables)
    # ------------------------------------------------------------------
    op.create_table(
        "sesiones",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("creada_en", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("expira_en", sa.DateTime(), nullable=False),
        sa.Column("revocada", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("ip_origen", sa.String(length=45), nullable=True),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sesiones_usuario_id", "sesiones", ["usuario_id"])
    op.create_index("ix_sesiones_jti", "sesiones", ["jti"], unique=True)


def downgrade() -> None:
    op.drop_table("sesiones")

    op.execute("DROP TRIGGER IF EXISTS trg_historial_no_delete ON historial_accesos")
    op.execute("DROP TRIGGER IF EXISTS trg_historial_no_update ON historial_accesos")
    op.execute("DROP FUNCTION IF EXISTS historial_bloquear_modificacion()")
    op.drop_table("historial_accesos")
    sa.Enum(name="resultado_acceso").drop(op.get_bind(), checkfirst=True)

    op.drop_table("usuario_permisos")
    op.drop_table("rol_permisos")

    op.drop_constraint(
        "fk_configuracion_updated_by_usuarios", "configuracion_sistema", type_="foreignkey"
    )
    op.drop_table("usuarios")
    op.drop_table("roles")
