"""Operaciones de caja: retiros con código, novedades, retiros de mercadería y joyero.

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-24

Sesión 09. Cuatro operaciones que ocurren durante un turno además de las
ventas:

- Retiros de efectivo con un código personal de 4 dígitos. La tabla
  `retiros_efectivo` ya existía desde la 0027 con otro esquema (motivo
  obligatorio, "autorizado_por" / "realizado_por") y nadie la usaba desde una
  pantalla: se adapta al esquema de la sesión 09 en vez de crear otra.
- Novedades de caja, con su catálogo de conceptos.
- Retiros de mercadería de empleadas (descuentan stock, no tocan la caja).
- Cobros de joyero (entran a la caja, no son venta).

`usuarios.es_autorizador` ya existe desde la 0034: no se vuelve a crear.

El valor nuevo del enum `tipo_movimiento_stock` se agrega en un
`autocommit_block()`: env.py corre todas las migraciones pendientes en una
sola transacción, y PostgreSQL no deja usar un valor de enum recién agregado
en la misma transacción (mismo criterio que la 0031).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                "ALTER TYPE tipo_movimiento_stock ADD VALUE IF NOT EXISTS 'retiro_mercaderia'"
            )
        )

    # ── usuarios: código de retiro ─────────────────────────────────────────
    op.add_column(
        "usuarios",
        sa.Column("puede_retirar", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("usuarios", sa.Column("codigo_retiro_hash", sa.String(255), nullable=True))

    # ── motivos_descuento: el motivo de las empleadas ──────────────────────
    op.add_column(
        "motivos_descuento",
        sa.Column(
            "es_descuento_empleada", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    # Uno solo: el retiro de mercadería lo busca por esta marca.
    op.create_index(
        "uq_motivos_descuento_empleada",
        "motivos_descuento",
        ["es_descuento_empleada"],
        unique=True,
        postgresql_where=sa.text("es_descuento_empleada"),
    )

    # ── retiros_efectivo: al esquema de la sesión 09 ───────────────────────
    op.add_column(
        "retiros_efectivo", sa.Column("punto_de_venta_id", sa.BigInteger(), nullable=True)
    )
    op.execute(
        """
        UPDATE retiros_efectivo r SET punto_de_venta_id = t.punto_de_venta_id
        FROM turnos t WHERE t.id = r.turno_id
        """
    )
    op.alter_column("retiros_efectivo", "punto_de_venta_id", nullable=False)
    op.create_foreign_key(
        "fk_retiros_efectivo_punto_de_venta",
        "retiros_efectivo",
        "puntos_de_venta",
        ["punto_de_venta_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_retiros_efectivo_punto_de_venta_id", "retiros_efectivo", ["punto_de_venta_id"]
    )
    # usuario_id = quien retira (identificado por su código);
    # registrado_por_id = quien lo cargó en el celular.
    op.alter_column("retiros_efectivo", "autorizado_por", new_column_name="usuario_id")
    op.alter_column("retiros_efectivo", "realizado_por", new_column_name="registrado_por_id")
    op.alter_column("retiros_efectivo", "motivo", nullable=True)
    op.create_check_constraint(
        "ck_retiros_efectivo_monto_positivo", "retiros_efectivo", "monto > 0"
    )

    # ── novedades de caja ──────────────────────────────────────────────────
    tipo_novedad = sa.Enum("entrada", "salida", name="tipo_novedad")
    tipo_novedad.create(op.get_bind(), checkfirst=True)
    tipo_col = postgresql.ENUM(name="tipo_novedad", create_type=False)

    op.create_table(
        "conceptos_novedad",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("tipo", tipo_col, nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("nombre", name="uq_conceptos_novedad_nombre"),
    )

    op.create_table(
        "novedades_caja",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "turno_id", sa.BigInteger(),
            sa.ForeignKey("turnos.id", ondelete="RESTRICT"), nullable=False, index=True,
        ),
        sa.Column(
            "punto_de_venta_id", sa.BigInteger(),
            sa.ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"), nullable=False, index=True,
        ),
        sa.Column(
            "concepto_id", sa.BigInteger(),
            sa.ForeignKey("conceptos_novedad.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("monto", sa.Numeric(10, 2), nullable=False),
        sa.Column("tipo", tipo_col, nullable=False),
        sa.Column(
            "autorizador_id", sa.BigInteger(),
            sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "registrado_por_id", sa.BigInteger(),
            sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.CheckConstraint("monto > 0", name="ck_novedades_caja_monto_positivo"),
    )

    # ── retiros de mercadería de empleadas ─────────────────────────────────
    op.create_table(
        "retiros_mercaderia",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "turno_id", sa.BigInteger(),
            sa.ForeignKey("turnos.id", ondelete="RESTRICT"), nullable=False, index=True,
        ),
        sa.Column(
            "punto_de_venta_id", sa.BigInteger(),
            sa.ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"), nullable=False, index=True,
        ),
        sa.Column(
            "empleada_usuario_id", sa.BigInteger(),
            sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=True, index=True,
        ),
        sa.Column("empleada_nombre", sa.String(150), nullable=True),
        sa.Column("empleada_dni", sa.String(15), nullable=True),
        sa.Column("es_empresa_propia", sa.Boolean(), nullable=False),
        sa.Column(
            "variante_id", sa.BigInteger(),
            sa.ForeignKey("producto_variantes.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("precio_lista", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "motivo_descuento_id", sa.BigInteger(),
            sa.ForeignKey("motivos_descuento.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("descuento_aplicado", sa.Numeric(5, 2), nullable=False),
        sa.Column("precio_con_descuento", sa.Numeric(10, 2), nullable=False),
        sa.Column("codigo_cambio", sa.String(8), nullable=False),
        sa.Column(
            "registrado_por_id", sa.BigInteger(),
            sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("codigo_cambio", name="uq_retiros_mercaderia_codigo_cambio"),
        sa.CheckConstraint(
            "(es_empresa_propia AND empleada_usuario_id IS NOT NULL)"
            " OR (NOT es_empresa_propia AND empleada_usuario_id IS NULL"
            " AND empleada_nombre IS NOT NULL)",
            name="ck_retiros_mercaderia_empleada",
        ),
        sa.CheckConstraint(
            "precio_lista >= 0 AND precio_con_descuento >= 0",
            name="ck_retiros_mercaderia_precios",
        ),
        sa.CheckConstraint(
            "descuento_aplicado >= 0 AND descuento_aplicado <= 100",
            name="ck_retiros_mercaderia_descuento",
        ),
    )

    op.add_column(
        "movimientos_stock",
        sa.Column("retiro_mercaderia_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_movimientos_stock_retiro_mercaderia",
        "movimientos_stock",
        "retiros_mercaderia",
        ["retiro_mercaderia_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_movimientos_stock_retiro_mercaderia_id",
        "movimientos_stock",
        ["retiro_mercaderia_id"],
    )

    # Un cambio puede tener como origen un retiro de mercadería (el producto
    # era para regalo y quien lo recibió lo viene a cambiar).
    op.add_column(
        "cambios",
        sa.Column("retiro_mercaderia_origen_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_cambios_retiro_mercaderia_origen",
        "cambios",
        "retiros_mercaderia",
        ["retiro_mercaderia_origen_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # ── cobros de joyero ───────────────────────────────────────────────────
    op.create_table(
        "cobros_joyero",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "turno_id", sa.BigInteger(),
            sa.ForeignKey("turnos.id", ondelete="RESTRICT"), nullable=False, index=True,
        ),
        sa.Column(
            "punto_de_venta_id", sa.BigInteger(),
            sa.ForeignKey("puntos_de_venta.id", ondelete="RESTRICT"), nullable=False, index=True,
        ),
        sa.Column("monto_efectivo", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("monto_otros", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column(
            "medio_de_pago_id", sa.BigInteger(),
            sa.ForeignKey("medios_de_pago.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("monto_cobrado", sa.Numeric(10, 2), nullable=False),
        sa.Column("numero_reclamo", sa.String(50), nullable=True),
        sa.Column(
            "registrado_por_id", sa.BigInteger(),
            sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False,
        ),
        # Los cobros de joyero no admiten cuotas: queda escrito en el modelo.
        sa.Column("sin_cuotas", sa.Boolean(), sa.Computed("TRUE", persisted=True)),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "monto_efectivo >= 0 AND monto_otros >= 0", name="ck_cobros_joyero_montos"
        ),
        sa.CheckConstraint("monto_cobrado > 0", name="ck_cobros_joyero_cobrado_positivo"),
    )


def downgrade() -> None:
    op.drop_table("cobros_joyero")

    op.drop_constraint("fk_cambios_retiro_mercaderia_origen", "cambios", type_="foreignkey")
    op.drop_column("cambios", "retiro_mercaderia_origen_id")

    op.drop_index("ix_movimientos_stock_retiro_mercaderia_id", table_name="movimientos_stock")
    op.drop_constraint(
        "fk_movimientos_stock_retiro_mercaderia", "movimientos_stock", type_="foreignkey"
    )
    op.drop_column("movimientos_stock", "retiro_mercaderia_id")
    op.drop_table("retiros_mercaderia")

    op.drop_table("novedades_caja")
    op.drop_table("conceptos_novedad")
    sa.Enum(name="tipo_novedad").drop(op.get_bind(), checkfirst=True)

    op.drop_constraint("ck_retiros_efectivo_monto_positivo", "retiros_efectivo", type_="check")
    op.execute("UPDATE retiros_efectivo SET motivo = '' WHERE motivo IS NULL")
    op.alter_column("retiros_efectivo", "motivo", nullable=False)
    op.alter_column("retiros_efectivo", "registrado_por_id", new_column_name="realizado_por")
    op.alter_column("retiros_efectivo", "usuario_id", new_column_name="autorizado_por")
    op.drop_index("ix_retiros_efectivo_punto_de_venta_id", table_name="retiros_efectivo")
    op.drop_constraint(
        "fk_retiros_efectivo_punto_de_venta", "retiros_efectivo", type_="foreignkey"
    )
    op.drop_column("retiros_efectivo", "punto_de_venta_id")

    op.drop_index("uq_motivos_descuento_empleada", table_name="motivos_descuento")
    op.drop_column("motivos_descuento", "es_descuento_empleada")

    op.drop_column("usuarios", "codigo_retiro_hash")
    op.drop_column("usuarios", "puede_retirar")
    # El valor 'retiro_mercaderia' del enum tipo_movimiento_stock no se quita:
    # PostgreSQL no permite borrar valores de un enum sin recrearlo.
