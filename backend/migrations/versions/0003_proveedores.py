"""Proveedores y valor del dólar

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# El historial del dólar es append-only por el mismo motivo que la
# auditoría: si se pudiera editar, no serviría para reconstruir el precio
# histórico de un producto. La garantía vive en la base.
SQL_GUARDIA_HISTORIAL = """
CREATE OR REPLACE FUNCTION proveedor_dolar_bloquear_modificacion()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'proveedor_dolar_historial es de solo inserción (append-only): % no permitido',
        TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

CREATE TRIGGER trg_proveedor_dolar_no_update
    BEFORE UPDATE ON proveedor_dolar_historial
    EXECUTE FUNCTION proveedor_dolar_bloquear_modificacion();

CREATE TRIGGER trg_proveedor_dolar_no_delete
    BEFORE DELETE ON proveedor_dolar_historial
    EXECUTE FUNCTION proveedor_dolar_bloquear_modificacion();
"""


def upgrade() -> None:
    estado_enum = postgresql.ENUM(
        "activo", "desactivado", "inhabilitado", name="estado_proveedor", create_type=False
    )
    origen_enum = postgresql.ENUM(
        "manual", "masivo_valor", "masivo_porcentaje", "importacion_excel",
        name="origen_cambio_dolar", create_type=False,
    )
    sa.Enum(
        "activo", "desactivado", "inhabilitado", name="estado_proveedor"
    ).create(op.get_bind(), checkfirst=True)
    sa.Enum(
        "manual", "masivo_valor", "masivo_porcentaje", "importacion_excel",
        name="origen_cambio_dolar",
    ).create(op.get_bind(), checkfirst=True)

    op.create_table(
        "proveedores",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("razon_social", sa.String(length=200), nullable=False),
        sa.Column("direccion", sa.String(length=255), nullable=True),
        sa.Column("telefono", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("estado", estado_enum, server_default="activo", nullable=False),
        sa.Column("dolar_actual", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("dolar_actual > 0", name="ck_proveedores_dolar_positivo"),
    )
    op.create_index("ix_proveedores_razon_social", "proveedores", ["razon_social"])
    op.create_index("ix_proveedores_estado", "proveedores", ["estado"])

    op.create_table(
        "proveedor_dolar_historial",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("proveedor_id", sa.BigInteger(), nullable=False),
        sa.Column("valor_anterior", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("valor_nuevo", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("origen", origen_enum, nullable=False),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["proveedor_id"], ["proveedores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_proveedor_dolar_historial_proveedor_id",
        "proveedor_dolar_historial",
        ["proveedor_id"],
    )
    op.create_index(
        "ix_proveedor_dolar_historial_timestamp",
        "proveedor_dolar_historial",
        ["timestamp"],
    )

    op.execute(SQL_GUARDIA_HISTORIAL)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_proveedor_dolar_no_delete ON proveedor_dolar_historial"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_proveedor_dolar_no_update ON proveedor_dolar_historial"
    )
    op.execute("DROP FUNCTION IF EXISTS proveedor_dolar_bloquear_modificacion()")

    op.drop_table("proveedor_dolar_historial")
    op.drop_table("proveedores")

    sa.Enum(name="origen_cambio_dolar").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="estado_proveedor").drop(op.get_bind(), checkfirst=True)
