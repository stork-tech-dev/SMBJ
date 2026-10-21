"""Etiquetas: rollos, impresoras Zebra y diseños.

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-21

Módulo de impresión de etiquetas en ZPL por Zebra Browser Print (reemplaza
al PDF). Siembra los dos rollos que usa el negocio y el diseño aprobado el
19/10/2026. Las impresoras NO se siembran: sus nombres de red son de cada
PC y se cargan desde Ajustes → Impresoras.
"""


import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

# El diseño aprobado el 19/10/2026, tal como lo define el prototipo del
# cliente (`prototipo-etiquetas/datos/disenos.json`).
DISENO_APROBADO = {
    "codigo_max": 8,
    "separacion_texto_numero_mm": 0.5,
    "matriz": {"modulos": 14, "modulo_mm": 0.5, "blanco_min_mm": 1},
    "multiple": {"numero_solo_fuente": "F", "numero_fuente": "D", "texto_max_mm": 2, "margen_mm": 1},
    "colita": {
        "numero_fuente": "D",
        "texto_max_mm": 1.75,
        "blanco_mm": 2,
        "margen_doblez_mm": 2,
        "margen_mm": 1,
    },
}


def _ahora():
    return sa.text("now()")


def upgrade() -> None:
    giro = postgresql.ENUM("normal", "invertido", name="giro_formato_etiqueta", create_type=False)
    giro.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "etiqueta_impresoras",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("nombre", sa.String(60), nullable=False),
        sa.Column("browser_print", sa.String(200), nullable=False, unique=True),
        sa.Column("dpi", sa.Integer(), nullable=False, server_default="203"),
        sa.Column("corrimiento_x_mm", sa.Numeric(4, 2), nullable=False, server_default="0"),
        sa.Column("corrimiento_y_mm", sa.Numeric(4, 2), nullable=False, server_default="0"),
        sa.Column("oscuridad", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("velocidad", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=_ahora()),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=_ahora()),
        sa.CheckConstraint("corrimiento_x_mm BETWEEN -10 AND 10", name="ck_etq_impresora_corrimiento_x"),
        sa.CheckConstraint("corrimiento_y_mm BETWEEN -10 AND 10", name="ck_etq_impresora_corrimiento_y"),
        sa.CheckConstraint("oscuridad BETWEEN 0 AND 30", name="ck_etq_impresora_oscuridad"),
        sa.CheckConstraint("velocidad BETWEEN 2 AND 6", name="ck_etq_impresora_velocidad"),
    )

    formatos = op.create_table(
        "etiqueta_formatos",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("clave", sa.String(40), nullable=False, unique=True),
        sa.Column("nombre", sa.String(60), nullable=False),
        sa.Column("ancho_rollo_mm", sa.Numeric(6, 2), nullable=False),
        sa.Column("columnas", sa.Integer(), nullable=False),
        sa.Column("paso_mm", sa.Numeric(6, 2), nullable=False),
        sa.Column("ancho_mm", sa.Numeric(6, 2), nullable=False),
        sa.Column("alto_mm", sa.Numeric(6, 2), nullable=False),
        sa.Column("zona_desde_mm", sa.Numeric(6, 2), nullable=False),
        sa.Column("zona_hasta_mm", sa.Numeric(6, 2), nullable=False),
        sa.Column("doblez_mm", sa.Numeric(6, 2)),
        sa.Column("giro", giro, nullable=False),
        sa.Column(
            "impresora_id", sa.BigInteger(),
            sa.ForeignKey("etiqueta_impresoras.id", ondelete="RESTRICT"),
        ),
        sa.CheckConstraint("columnas > 0", name="ck_etq_formato_columnas"),
        sa.CheckConstraint("zona_hasta_mm > zona_desde_mm", name="ck_etq_formato_zona"),
    )

    disenos = op.create_table(
        "etiqueta_disenos",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("nombre", sa.String(80), nullable=False),
        sa.Column("parametros", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("archivado", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("actualizado_por_id", sa.BigInteger(), sa.ForeignKey("usuarios.id")),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=_ahora()),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=_ahora()),
    )

    versiones = op.create_table(
        "etiqueta_disenos_versiones",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "diseno_id", sa.BigInteger(),
            sa.ForeignKey("etiqueta_disenos.id", ondelete="CASCADE"), nullable=False, index=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(80), nullable=False),
        sa.Column("parametros", postgresql.JSONB(), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), sa.ForeignKey("usuarios.id")),
        sa.Column("creado_en", sa.DateTime(timezone=False), nullable=False, server_default=_ahora()),
        sa.UniqueConstraint("diseno_id", "version", name="uq_etq_diseno_version"),
    )

    # Los dos rollos, con las medidas que manda hoy el sistema viejo y que se
    # comprobaron imprimiendo en las Zebra (documento de requisitos, "Los dos
    # formatos").
    op.bulk_insert(formatos, [
        {
            "id": 1, "clave": "multiple_32x10", "nombre": "Múltiple 32×10",
            "ancho_rollo_mm": 102, "columnas": 3, "paso_mm": 35, "ancho_mm": 32, "alto_mm": 10,
            "zona_desde_mm": 0, "zona_hasta_mm": 32, "doblez_mm": None, "giro": "normal",
        },
        {
            "id": 2, "clave": "colita_66x11", "nombre": "Colita 66×11",
            "ancho_rollo_mm": 66, "columnas": 1, "paso_mm": 66, "ancho_mm": 66, "alto_mm": 11,
            "zona_desde_mm": 0, "zona_hasta_mm": 33, "doblez_mm": 16.5, "giro": "invertido",
        },
    ])
    op.bulk_insert(disenos, [
        {"id": 1, "nombre": "Aprobado 19/10/2026", "parametros": DISENO_APROBADO, "version": 1},
    ])
    op.bulk_insert(versiones, [
        {"diseno_id": 1, "version": 1, "nombre": "Aprobado 19/10/2026", "parametros": DISENO_APROBADO},
    ])
    # Las filas sembradas usan ids explícitos: las secuencias tienen que
    # seguir después de ellos.
    for tabla in ("etiqueta_formatos", "etiqueta_disenos"):
        op.execute(f"SELECT setval(pg_get_serial_sequence('{tabla}', 'id'), (SELECT MAX(id) FROM {tabla}))")


def downgrade() -> None:
    op.drop_table("etiqueta_disenos_versiones")
    op.drop_table("etiqueta_disenos")
    op.drop_table("etiqueta_formatos")
    op.drop_table("etiqueta_impresoras")
    sa.Enum(name="giro_formato_etiqueta").drop(op.get_bind(), checkfirst=True)
