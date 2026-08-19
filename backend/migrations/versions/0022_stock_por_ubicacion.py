"""Control de stock: por ubicación, con movimientos, remitos y auditorías

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    El stock deja de ser un número en la variante y pasa a ser una fila por
    variante y ubicación.

    Un "stock global" no existe en el negocio: 12 unidades en Patio Olmos y
    0 en el resto son dos hechos distintos, no un total de 12. Y sin
    ubicación no hay forma de mandar mercadería de un lado a otro, que es
    justamente lo que hace este módulo.

    `motivos_baja` no se crea acá: existe desde la 0001, porque el seed la
    necesitaba.
    """
    # Correlativo de los remitos. Una SEQUENCE y no MAX(numero)+1: dos
    # envíos simultáneos sacan números distintos sin bloquearse, igual que
    # los SKU de la 0008.
    op.execute("CREATE SEQUENCE remitos_numero_seq START 1")

    for nombre, valores in [
        (
            "tipo_movimiento_stock",
            (
                "ingreso_proveedor", "envio_cd_local", "devolucion_local_cd",
                "venta", "devolucion_venta", "baja", "ajuste_auditoria",
            ),
        ),
        ("estado_remito", ("pendiente", "en_camino", "confirmado", "con_diferencia")),
        (
            "estado_auditoria_inventario",
            ("en_curso", "pendiente_aprobacion", "aprobada", "rechazada"),
        ),
    ]:
        sa.Enum(*valores, name=nombre).create(op.get_bind(), checkfirst=True)

    # ---------------------------------------------------------------- stock
    op.create_table(
        "stock",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("variante_id", sa.BigInteger(), nullable=False),
        sa.Column("punto_de_venta_id", sa.BigInteger(), nullable=False),
        sa.Column("cantidad", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stock_minimo_cd", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stock_minimo_local", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # CASCADE: el stock de una variante que se elimina no significa nada.
        # RESTRICT en el punto de venta: no se puede borrar una ubicación que
        # todavía tiene mercadería.
        sa.ForeignKeyConstraint(["variante_id"], ["producto_variantes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["punto_de_venta_id"], ["puntos_de_venta.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "variante_id", "punto_de_venta_id", name="uq_stock_variante_punto_de_venta"
        ),
        sa.CheckConstraint("cantidad >= 0", name="ck_stock_cantidad_no_negativa"),
        sa.CheckConstraint(
            "stock_minimo_cd >= 0 AND stock_minimo_local >= 0",
            name="ck_stock_minimos_no_negativos",
        ),
    )
    op.create_index("ix_stock_variante_id", "stock", ["variante_id"])
    op.create_index("ix_stock_punto_de_venta_id", "stock", ["punto_de_venta_id"])

    # --------------------------------------------------------------- remitos
    op.create_table(
        "remitos",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("numero", sa.String(length=12), nullable=False),
        sa.Column("punto_venta_origen_id", sa.BigInteger(), nullable=False),
        sa.Column("punto_venta_destino_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "estado",
            postgresql.ENUM(
                "pendiente", "en_camino", "confirmado", "con_diferencia",
                name="estado_remito", create_type=False,
            ),
            server_default="pendiente",
            nullable=False,
        ),
        sa.Column("usuario_envio_id", sa.BigInteger(), nullable=False),
        sa.Column("usuario_recepcion_id", sa.BigInteger(), nullable=True),
        sa.Column("fecha_envio", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("fecha_recepcion", sa.DateTime(), nullable=True),
        sa.Column("pdf_url", sa.String(length=255), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["punto_venta_origen_id"], ["puntos_de_venta.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["punto_venta_destino_id"], ["puntos_de_venta.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["usuario_envio_id"], ["usuarios.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["usuario_recepcion_id"], ["usuarios.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "punto_venta_origen_id <> punto_venta_destino_id",
            name="ck_remitos_origen_distinto_destino",
        ),
    )
    op.create_index("ix_remitos_numero", "remitos", ["numero"], unique=True)
    op.create_index("ix_remitos_origen", "remitos", ["punto_venta_origen_id"])
    op.create_index("ix_remitos_destino", "remitos", ["punto_venta_destino_id"])
    op.create_index("ix_remitos_estado", "remitos", ["estado"])

    op.create_table(
        "remito_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("remito_id", sa.BigInteger(), nullable=False),
        sa.Column("variante_id", sa.BigInteger(), nullable=False),
        sa.Column("cantidad_enviada", sa.Integer(), nullable=False),
        sa.Column("cantidad_recibida", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["remito_id"], ["remitos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["variante_id"], ["producto_variantes.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("remito_id", "variante_id", name="uq_remito_items_variante"),
        sa.CheckConstraint("cantidad_enviada > 0", name="ck_remito_items_enviada_positiva"),
        sa.CheckConstraint(
            "cantidad_recibida IS NULL OR cantidad_recibida >= 0",
            name="ck_remito_items_recibida_no_negativa",
        ),
    )
    op.create_index("ix_remito_items_remito_id", "remito_items", ["remito_id"])
    op.create_index("ix_remito_items_variante_id", "remito_items", ["variante_id"])

    # ---------------------------------------------- auditorías de inventario
    op.create_table(
        "auditorias_inventario",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("punto_de_venta_id", sa.BigInteger(), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "estado",
            postgresql.ENUM(
                "en_curso", "pendiente_aprobacion", "aprobada", "rechazada",
                name="estado_auditoria_inventario", create_type=False,
            ),
            server_default="en_curso",
            nullable=False,
        ),
        sa.Column("filtro_categoria_id", sa.BigInteger(), nullable=True),
        sa.Column("aprobada_por", sa.BigInteger(), nullable=True),
        sa.Column("fecha_inicio", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("fecha_fin", sa.DateTime(), nullable=True),
        sa.Column("fecha_aprobacion", sa.DateTime(), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["punto_de_venta_id"], ["puntos_de_venta.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["aprobada_por"], ["usuarios.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["filtro_categoria_id"], ["categorias.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_auditorias_inventario_punto_de_venta", "auditorias_inventario", ["punto_de_venta_id"]
    )
    op.create_index("ix_auditorias_inventario_estado", "auditorias_inventario", ["estado"])

    op.create_table(
        "auditoria_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("auditoria_id", sa.BigInteger(), nullable=False),
        sa.Column("variante_id", sa.BigInteger(), nullable=False),
        sa.Column("cantidad_sistema", sa.Integer(), nullable=False),
        sa.Column("cantidad_contada", sa.Integer(), nullable=False),
        # La resta la hace el motor: es lo que decide si se genera un ajuste,
        # y no puede depender de que todos los caminos se acuerden de hacerla
        # igual.
        sa.Column(
            "diferencia",
            sa.Integer(),
            sa.Computed("cantidad_contada - cantidad_sistema", persisted=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["auditoria_id"], ["auditorias_inventario.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["variante_id"], ["producto_variantes.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("auditoria_id", "variante_id", name="uq_auditoria_items_variante"),
    )
    op.create_index("ix_auditoria_items_auditoria_id", "auditoria_items", ["auditoria_id"])
    op.create_index("ix_auditoria_items_variante_id", "auditoria_items", ["variante_id"])

    # --------------------------------------------------------- movimientos
    # Va última: sus FK apuntan a remitos y auditorias_inventario.
    op.create_table(
        "movimientos_stock",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "tipo",
            postgresql.ENUM(
                "ingreso_proveedor", "envio_cd_local", "devolucion_local_cd",
                "venta", "devolucion_venta", "baja", "ajuste_auditoria",
                name="tipo_movimiento_stock", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("variante_id", sa.BigInteger(), nullable=False),
        sa.Column("punto_venta_origen_id", sa.BigInteger(), nullable=True),
        sa.Column("punto_venta_destino_id", sa.BigInteger(), nullable=True),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("remito_id", sa.BigInteger(), nullable=True),
        sa.Column("motivo_baja_id", sa.BigInteger(), nullable=True),
        sa.Column("auditoria_id", sa.BigInteger(), nullable=True),
        # Sin FK: `ventas` llega en el módulo 06. La columna se crea ahora
        # porque el tipo `venta` ya existe y el dato hay que poder guardarlo.
        sa.Column("referencia_venta_id", sa.BigInteger(), nullable=True),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        # RESTRICT en la variante: borrar un producto no puede borrar la
        # historia de lo que se movió de él.
        sa.ForeignKeyConstraint(["variante_id"], ["producto_variantes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["punto_venta_origen_id"], ["puntos_de_venta.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["punto_venta_destino_id"], ["puntos_de_venta.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["remito_id"], ["remitos.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["motivo_baja_id"], ["motivos_baja.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["auditoria_id"], ["auditorias_inventario.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("cantidad > 0", name="ck_movimientos_stock_cantidad_positiva"),
        sa.CheckConstraint(
            "punto_venta_origen_id IS NOT NULL OR punto_venta_destino_id IS NOT NULL",
            name="ck_movimientos_stock_tiene_ubicacion",
        ),
    )
    for columna in (
        "tipo", "variante_id", "punto_venta_origen_id", "punto_venta_destino_id",
        "remito_id", "referencia_venta_id", "usuario_id", "timestamp",
    ):
        op.create_index(f"ix_movimientos_stock_{columna}", "movimientos_stock", [columna])

    # ------------------------------------------- mudanza del stock que había
    # Lo que estaba en la variante se manda al CD: es donde entra la
    # mercadería, y el único lugar del que se puede repartir. Si hubiera
    # varios CD gana el de menor id; si no hubiera ninguno, el UPDATE no
    # encuentra destino y las unidades se pierden — por eso primero se
    # verifica y se aborta con un mensaje entendible.
    conexion = op.get_bind()
    unidades = conexion.exec_driver_sql(
        "SELECT coalesce(sum(stock_actual), 0) FROM producto_variantes"
    ).scalar_one()
    cd = conexion.exec_driver_sql(
        "SELECT id FROM puntos_de_venta WHERE tipo = 'cd' ORDER BY id LIMIT 1"
    ).scalar_one_or_none()

    if unidades and cd is None:
        raise RuntimeError(
            f"Hay {unidades} unidades de stock cargadas y ningún punto de venta "
            "de tipo 'cd' al que mudarlas. Creá el CD antes de aplicar esta "
            "migración, o la mercadería quedaría sin ubicación."
        )

    if cd is not None:
        conexion.exec_driver_sql(
            """
            INSERT INTO stock (variante_id, punto_de_venta_id, cantidad,
                               stock_minimo_cd, stock_minimo_local, updated_at)
            SELECT id, %(cd)s, stock_actual, stock_minimo, stock_minimo, now()
            FROM producto_variantes
            WHERE stock_actual <> 0 OR stock_minimo <> 0
            """,
            {"cd": cd},
        )

    # ------------------------------------------- permisos: stock es su módulo
    # Hasta acá, las bajas y las auditorías de inventario colgaban del módulo
    # `productos` (seed de la 0001). Pasan a `stock`, que es su lugar: el
    # Auditor no tiene acceso a Productos y sí tiene que poder auditar
    # inventario, así que compartir módulo lo dejaba afuera.
    #
    # Se mueven las filas ya sembradas en vez de dejarlas: si no, el árbol de
    # permisos mostraría los mismos recursos en dos módulos, y uno de los dos
    # no haría nada.
    for tabla in ("rol_permisos", "usuario_permisos"):
        conexion.exec_driver_sql(
            f"""
            UPDATE {tabla} SET modulo = 'stock'
            WHERE modulo = 'productos'
              AND recurso IN ('stock.baja', 'stock.auditoria')
            """
        )

    op.drop_column("producto_variantes", "stock_actual")
    op.drop_column("producto_variantes", "stock_minimo")


def downgrade() -> None:
    """
    Devuelve el stock a la variante sumando todas las ubicaciones.

    La vuelta atrás PIERDE información y no hay forma de que no lo haga: el
    detalle por ubicación no entra en una sola columna. Los movimientos, los
    remitos y las auditorías se borran con sus tablas.
    """
    op.add_column(
        "producto_variantes",
        sa.Column("stock_actual", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "producto_variantes",
        sa.Column("stock_minimo", sa.Integer(), server_default="0", nullable=False),
    )
    op.execute(
        """
        UPDATE producto_variantes v
        SET stock_actual = t.total, stock_minimo = t.minimo
        FROM (
            SELECT variante_id, sum(cantidad) AS total,
                   max(greatest(stock_minimo_cd, stock_minimo_local)) AS minimo
            FROM stock GROUP BY variante_id
        ) t
        WHERE t.variante_id = v.id
        """
    )

    for tabla in ("rol_permisos", "usuario_permisos"):
        op.execute(
            f"""
            UPDATE {tabla} SET modulo = 'productos'
            WHERE modulo = 'stock' AND recurso IN ('stock.baja', 'stock.auditoria')
            """
        )
    # Los permisos propios del módulo se van con él: sin las pantallas de
    # stock, un permiso 'stock' no habilita nada.
    op.execute("DELETE FROM rol_permisos WHERE modulo = 'stock'")
    op.execute("DELETE FROM usuario_permisos WHERE modulo = 'stock'")

    op.drop_table("movimientos_stock")
    op.drop_table("auditoria_items")
    op.drop_table("auditorias_inventario")
    op.drop_table("remito_items")
    op.drop_table("remitos")
    op.drop_table("stock")

    op.execute("DROP SEQUENCE IF EXISTS remitos_numero_seq")
    for nombre in ("tipo_movimiento_stock", "estado_remito", "estado_auditoria_inventario"):
        op.execute(f"DROP TYPE IF EXISTS {nombre}")
