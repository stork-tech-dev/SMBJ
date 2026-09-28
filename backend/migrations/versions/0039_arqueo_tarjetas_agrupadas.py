"""Crédito y Débito se arquean juntos: "Tarjetas de Crédito / Débito".

Revision ID: 0039
Revises: 0038
Create Date: 2026-09-28

El cierre de caja pedía contar por separado lo cobrado con Tarjeta de
Crédito y con Débito, pero en el local se cuentan juntos (salen de la misma
terminal). El agrupamiento ya estaba soportado por `medios_pago_arqueo_config`
(`agrupa_en_terminal` + `grupo_terminal`, ver `arqueo.calcular_esperado`);
faltaba cargarlo. Los medios se buscan por el nombre del seed de la 0024: si
alguno no existe, simplemente no se agrupa.

Los arqueos ya registrados no cambian: conservan un renglón por medio.
"""

from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

# Mismo texto que `services/arqueo.py::GRUPO_TARJETAS` (las migraciones no
# importan código de la app).
GRUPO = "Tarjetas de Crédito / Débito"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO medios_pago_arqueo_config
            (medio_de_pago_id, agrupa_en_terminal, grupo_terminal, es_informativo, updated_at)
        SELECT id, true, '{GRUPO}', false, now()
        FROM medios_de_pago
        WHERE nombre IN ('Débito', 'Tarjeta de Crédito')
        ON CONFLICT (medio_de_pago_id) DO UPDATE
            SET agrupa_en_terminal = true,
                grupo_terminal = EXCLUDED.grupo_terminal,
                updated_at = now()
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE medios_pago_arqueo_config
        SET agrupa_en_terminal = false, grupo_terminal = NULL, updated_at = now()
        WHERE grupo_terminal = '{GRUPO}'
        """
    )
