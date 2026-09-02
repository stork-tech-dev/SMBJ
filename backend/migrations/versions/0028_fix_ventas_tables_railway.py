"""Fix: crea tablas de ventas faltantes en Railway

Revision ID: 0028
Revises: 80852ebe8f92
Create Date: 2026-09-02

En Railway, la migración 0024 (ventas) nunca ejecutó su contenido real:
se registró en alembic_version con el ID "0024" pero el SQL que corrió
fue el de la migración de fotos (variante_id), debido al conflicto de IDs
duplicados que existió antes de que se resolviera con 0024b.

Esta migración recrea el contenido de 0024_ventas.py de forma idempotente:
si las tablas ya existen (entornos donde 0024 sí corrió correctamente)
no hace nada; si no existen (Railway), las crea.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: Union[str, None] = "80852ebe8f92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tablas_existentes = inspector.get_table_names()

    # Si clientes ya existe, 0024_ventas.py corrió correctamente en este DB.
    # No hay nada que hacer.
    if "clientes" in tablas_existentes:
        return

    # A partir de acá: entorno con el estado roto de Railway donde 0024
    # nunca creó las tablas de ventas. Se reproduce todo el contenido de
    # 0024_ventas.upgrade() tal cual.

    op.execute("CREATE SEQUENCE IF NOT EXISTS ventas_numero_seq START 1")

    for nombre, valores in [
        ("tipo_punto_cliente", ("acumulacion", "canje", "ajuste")),
        ("tipo_promocion", ("dos_x_uno", "tres_x_dos")),
        ("tipo_alcance_promocion", ("producto", "categoria")),
        ("estado_venta", ("en_curso", "confirmada", "anulada")),
    ]:
        sa.Enum(*valores, name=nombre).create(op.get_bind(), checkfirst=True)

    op.create_table(
        "clientes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(length=150), nullable=False),
        sa.Column("dni", sa.String(length=15), nullable=True),
        sa.Column("domicilio", sa.String(length=200), nullable=True),
        sa.Column("codigo_postal", sa.String(length=10), nullable=True),
        sa.Column("localidad", sa.String(length=100), nullable=True),
        sa.Column("telefono", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=150), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_clientes_dni", "clientes", ["dni"], unique=True)
    op.create_index("ix_clientes_activo", "clientes", ["activo"])
    op.execute("CREATE INDEX ix_clientes_nombre_lower ON clientes (lower(nombre))")

    op.create_table(
        "medios_de_pago",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(length=60), nullable=False),
        sa.Column("soporta_cuotas", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("es_sena", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "NOT (es_sena AND soporta_cuotas)", name="ck_medios_de_pago_sena_sin_cuotas"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre", name="uq_medios_de_pago_nombre"),
    )
    op.create_index("ix_medios_de_pago_activo", "medios_de_pago", ["activo"])

    op.create_table(
        "planes_cuotas",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("medio_de_pago_id", sa.BigInteger(), nullable=False),
        sa.Column("cuotas", sa.SmallInteger(), nullable=False),
        sa.Column("recargo_cliente", sa.Numeric(5, 2), server_default="0", nullable=False),
        sa.Column("costo_medio", sa.Numeric(5, 2), server_default="0", nullable=False),
        sa.Column("monto_minimo", sa.Numeric(10, 2), server_default="0", nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("cuotas >= 1", name="ck_planes_cuotas_cantidad_positiva"),
        sa.CheckConstraint(
            "recargo_cliente >= 0 AND recargo_cliente <= 100",
            name="ck_planes_cuotas_recargo_rango",
        ),
        sa.CheckConstraint(
            "costo_medio >= 0 AND costo_medio <= 100", name="ck_planes_cuotas_costo_rango"
        ),
        sa.CheckConstraint("monto_minimo >= 0", name="ck_planes_cuotas_minimo_no_negativo"),
        sa.ForeignKeyConstraint(
            ["medio_de_pago_id"], ["medios_de_pago.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "medio_de_pago_id", "cuotas", "recargo_cliente", name="uq_plan_cuotas"
        ),
    )
    op.create_index("ix_planes_cuotas_medio", "planes_cuotas", ["medio_de_pago_id"])

    op.create_table(
        "promociones",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column(
            "tipo",
            postgresql.ENUM("dos_x_uno", "tres_x_dos", name="tipo_promocion", create_type=False),
            nullable=False,
        ),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("fecha_inicio", sa.Date(), nullable=True),
        sa.Column("fecha_fin", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "fecha_inicio IS NULL OR fecha_fin IS NULL OR fecha_inicio <= fecha_fin",
            name="ck_promociones_vigencia_coherente",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre", name="uq_promociones_nombre"),
    )
    op.create_index("ix_promociones_activo", "promociones", ["activo"])

    op.create_table(
        "promocion_alcance",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("promocion_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "tipo_alcance",
            postgresql.ENUM(
                "producto", "categoria", name="tipo_alcance_promocion", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("referencia_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["promocion_id"], ["promociones.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "promocion_id", "tipo_alcance", "referencia_id", name="uq_promocion_alcance"
        ),
    )
    op.create_index("ix_promocion_alcance_promocion", "promocion_alcance", ["promocion_id"])
    op.create_index("ix_promocion_alcance_referencia", "promocion_alcance", ["referencia_id"])

    op.create_table(
        "cliente_promociones",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("cliente_id", sa.BigInteger(), nullable=False),
        sa.Column("promocion_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["promocion_id"], ["promociones.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cliente_id", "promocion_id", name="uq_cliente_promocion"),
    )
    op.create_index("ix_cliente_promociones_cliente", "cliente_promociones", ["cliente_id"])
    op.create_index("ix_cliente_promociones_promocion", "cliente_promociones", ["promocion_id"])

    op.create_table(
        "senas",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("cliente_id", sa.BigInteger(), nullable=False),
        sa.Column("monto", sa.Numeric(10, 2), nullable=False),
        sa.Column("saldo", sa.Numeric(10, 2), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("monto > 0", name="ck_senas_monto_positivo"),
        sa.CheckConstraint("saldo >= 0 AND saldo <= monto", name="ck_senas_saldo_en_rango"),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_senas_cliente", "senas", ["cliente_id"])
    op.create_index("ix_senas_usuario", "senas", ["usuario_id"])
    op.create_index("ix_senas_activo", "senas", ["activo"])

    op.create_table(
        "motivos_descuento",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("porcentaje_sugerido", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "habilita_cuotas_sin_interes",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "porcentaje_sugerido IS NULL"
            " OR (porcentaje_sugerido > 0 AND porcentaje_sugerido <= 100)",
            name="ck_motivos_descuento_porcentaje_rango",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre", name="uq_motivos_descuento_nombre"),
    )
    op.create_index("ix_motivos_descuento_activo", "motivos_descuento", ["activo"])

    op.create_table(
        "ventas",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("numero", sa.String(length=12), nullable=False),
        sa.Column("cliente_id", sa.BigInteger(), nullable=True),
        sa.Column("punto_de_venta_id", sa.BigInteger(), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("dispositivo_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "estado",
            postgresql.ENUM(
                "en_curso", "confirmada", "anulada", name="estado_venta", create_type=False
            ),
            server_default="en_curso",
            nullable=False,
        ),
        sa.Column("subtotal", sa.Numeric(10, 2), server_default="0", nullable=False),
        sa.Column("descuento_total", sa.Numeric(10, 2), server_default="0", nullable=False),
        sa.Column("recargo_total", sa.Numeric(10, 2), server_default="0", nullable=False),
        sa.Column("total", sa.Numeric(10, 2), server_default="0", nullable=False),
        sa.Column("codigo_cambio", sa.String(length=8), nullable=True),
        sa.Column("puntos_acumulados", sa.Integer(), server_default="0", nullable=False),
        sa.Column("promocion_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("subtotal >= 0", name="ck_ventas_subtotal_no_negativo"),
        sa.CheckConstraint("descuento_total >= 0", name="ck_ventas_descuento_no_negativo"),
        sa.CheckConstraint("recargo_total >= 0", name="ck_ventas_recargo_no_negativo"),
        sa.CheckConstraint("total >= 0", name="ck_ventas_total_no_negativo"),
        sa.CheckConstraint("puntos_acumulados >= 0", name="ck_ventas_puntos_no_negativos"),
        sa.CheckConstraint(
            "(estado = 'en_curso' AND codigo_cambio IS NULL)"
            " OR (estado <> 'en_curso' AND codigo_cambio IS NOT NULL)",
            name="ck_ventas_codigo_cambio_al_confirmar",
        ),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["punto_de_venta_id"], ["puntos_de_venta.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["dispositivo_id"], ["dispositivos.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["promocion_id"], ["promociones.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ventas_numero", "ventas", ["numero"], unique=True)
    op.create_index("ix_ventas_codigo_cambio", "ventas", ["codigo_cambio"], unique=True)
    op.create_index("ix_ventas_cliente", "ventas", ["cliente_id"])
    op.create_index("ix_ventas_punto_de_venta", "ventas", ["punto_de_venta_id"])
    op.create_index("ix_ventas_usuario", "ventas", ["usuario_id"])
    op.create_index("ix_ventas_dispositivo", "ventas", ["dispositivo_id"])
    op.create_index("ix_ventas_promocion", "ventas", ["promocion_id"])
    op.create_index("ix_ventas_estado", "ventas", ["estado"])
    op.create_index("ix_ventas_created_at", "ventas", ["created_at"])
    op.execute(
        "CREATE INDEX ix_ventas_en_curso ON ventas (usuario_id, punto_de_venta_id)"
        " WHERE estado = 'en_curso'"
    )

    op.create_table(
        "venta_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("venta_id", sa.BigInteger(), nullable=False),
        sa.Column("variante_id", sa.BigInteger(), nullable=False),
        sa.Column("precio_unitario", sa.Numeric(10, 2), nullable=False),
        sa.Column("precio_lista", sa.Numeric(10, 2), nullable=False),
        sa.Column("descuento_item", sa.Numeric(5, 2), server_default="0", nullable=False),
        sa.Column("motivo_descuento_id", sa.BigInteger(), nullable=True),
        sa.Column("porcentaje_modificado", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("precio_final", sa.Numeric(10, 2), nullable=False),
        sa.Column("en_promocion", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("orden", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("precio_unitario >= 0", name="ck_venta_items_precio_no_negativo"),
        sa.CheckConstraint("precio_lista >= 0", name="ck_venta_items_lista_no_negativo"),
        sa.CheckConstraint("precio_final >= 0", name="ck_venta_items_final_no_negativo"),
        sa.CheckConstraint(
            "descuento_item >= 0 AND descuento_item <= 100",
            name="ck_venta_items_descuento_rango",
        ),
        sa.CheckConstraint(
            "descuento_item = 0 OR motivo_descuento_id IS NOT NULL",
            name="ck_venta_items_descuento_con_motivo",
        ),
        sa.CheckConstraint(
            "NOT (en_promocion AND descuento_item > 0)",
            name="ck_venta_items_promocion_sin_descuento",
        ),
        sa.ForeignKeyConstraint(["venta_id"], ["ventas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["variante_id"], ["producto_variantes.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["motivo_descuento_id"], ["motivos_descuento.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_venta_items_venta", "venta_items", ["venta_id"])
    op.create_index("ix_venta_items_variante", "venta_items", ["variante_id"])

    op.create_table(
        "venta_pagos",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("venta_id", sa.BigInteger(), nullable=False),
        sa.Column("medio_de_pago_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_cuotas_id", sa.BigInteger(), nullable=True),
        sa.Column("monto", sa.Numeric(10, 2), nullable=False),
        sa.Column("recargo", sa.Numeric(10, 2), server_default="0", nullable=False),
        sa.Column("monto_total", sa.Numeric(10, 2), nullable=False),
        sa.Column("sena_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("monto > 0", name="ck_venta_pagos_monto_positivo"),
        sa.CheckConstraint("recargo >= 0", name="ck_venta_pagos_recargo_no_negativo"),
        sa.CheckConstraint(
            "monto_total = monto + recargo", name="ck_venta_pagos_total_es_suma"
        ),
        sa.ForeignKeyConstraint(["venta_id"], ["ventas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["medio_de_pago_id"], ["medios_de_pago.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["plan_cuotas_id"], ["planes_cuotas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sena_id"], ["senas.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_venta_pagos_venta", "venta_pagos", ["venta_id"])
    op.create_index("ix_venta_pagos_medio", "venta_pagos", ["medio_de_pago_id"])
    op.create_index("ix_venta_pagos_sena", "venta_pagos", ["sena_id"])

    op.create_table(
        "puntos_cliente",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("cliente_id", sa.BigInteger(), nullable=False),
        sa.Column("venta_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "tipo",
            postgresql.ENUM(
                "acumulacion", "canje", "ajuste", name="tipo_punto_cliente", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("cantidad <> 0", name="ck_puntos_cliente_cantidad_no_cero"),
        sa.CheckConstraint(
            "(tipo = 'acumulacion' AND cantidad > 0)"
            " OR (tipo = 'canje' AND cantidad < 0)"
            " OR tipo = 'ajuste'",
            name="ck_puntos_cliente_signo_segun_tipo",
        ),
        sa.CheckConstraint(
            "tipo <> 'ajuste' OR descripcion IS NOT NULL",
            name="ck_puntos_cliente_ajuste_con_motivo",
        ),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["venta_id"], ["ventas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_puntos_cliente_cliente", "puntos_cliente", ["cliente_id"])
    op.create_index("ix_puntos_cliente_venta", "puntos_cliente", ["venta_id"])
    op.create_index("ix_puntos_cliente_usuario", "puntos_cliente", ["usuario_id"])
    op.create_index("ix_puntos_cliente_tipo", "puntos_cliente", ["tipo"])
    op.create_index("ix_puntos_cliente_timestamp", "puntos_cliente", ["timestamp"])

    op.execute(
        """
        CREATE OR REPLACE FUNCTION puntos_cliente_solo_insercion()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                'puntos_cliente es de solo inserción: para corregir, registrar '
                'un movimiento de tipo ajuste con el signo contrario';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_puntos_cliente_inmutable
            BEFORE UPDATE OR DELETE ON puntos_cliente
            FOR EACH ROW EXECUTE FUNCTION puntos_cliente_solo_insercion();
        """
    )

    # Eliminar el CHECK que impedía stock negativo: la venta lo justifica.
    # Si ya fue eliminado por algún motivo, ignorar.
    try:
        op.drop_constraint("ck_stock_cantidad_no_negativa", "stock", type_="check")
    except Exception:
        pass

    # FK que quedó pendiente en 0022 (la tabla ventas no existía).
    op.create_foreign_key(
        "fk_movimientos_stock_referencia_venta",
        "movimientos_stock",
        "ventas",
        ["referencia_venta_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # Seed mínimo para poder cobrar desde el primer día.
    op.execute(
        """
        INSERT INTO medios_de_pago (nombre, soporta_cuotas, es_sena, activo)
        VALUES ('Efectivo',           false, false, true),
               ('Débito',             false, false, true),
               ('Tarjeta de Crédito', true,  false, true),
               ('Seña',               false, true,  true)
        ON CONFLICT (nombre) DO NOTHING
        """
    )

    op.execute(
        """
        INSERT INTO rol_permisos
            (rol_id, modulo, recurso, puede_ver, puede_crear, puede_editar, puede_eliminar)
        SELECT id, 'configuracion', 'configuracion.promociones', true, true, true, false
        FROM roles WHERE nombre = 'supervisor'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    # Solo aplica si esta migración efectivamente creó las tablas.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "clientes" not in inspector.get_table_names():
        return

    for tabla in ("rol_permisos", "usuario_permisos"):
        op.execute(f"DELETE FROM {tabla} WHERE recurso = 'configuracion.promociones'")

    try:
        op.drop_constraint(
            "fk_movimientos_stock_referencia_venta", "movimientos_stock", type_="foreignkey"
        )
    except Exception:
        pass

    try:
        op.create_check_constraint("ck_stock_cantidad_no_negativa", "stock", "cantidad >= 0")
    except Exception:
        pass

    op.execute("DROP TRIGGER IF EXISTS trg_puntos_cliente_inmutable ON puntos_cliente")
    op.execute("DROP FUNCTION IF EXISTS puntos_cliente_solo_insercion()")

    for tabla in (
        "puntos_cliente",
        "venta_pagos",
        "venta_items",
        "ventas",
        "motivos_descuento",
        "senas",
        "cliente_promociones",
        "promocion_alcance",
        "promociones",
        "planes_cuotas",
        "medios_de_pago",
        "clientes",
    ):
        op.drop_table(tabla)

    for nombre in (
        "estado_venta",
        "tipo_alcance_promocion",
        "tipo_promocion",
        "tipo_punto_cliente",
    ):
        op.execute(f"DROP TYPE IF EXISTS {nombre}")

    op.execute("DROP SEQUENCE IF EXISTS ventas_numero_seq")
