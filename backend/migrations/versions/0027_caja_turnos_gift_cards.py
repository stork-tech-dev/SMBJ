"""Caja: turnos, arqueos, retiros, gift cards y notificaciones

Revision ID: 0027
Revises: 80852ebe8f92
Create Date: 2026-08-31

Crea las 9 tablas del módulo de caja:
- turnos, turno_vendedoras, retiros_efectivo
- medios_pago_arqueo_config
- arqueos (con diferencia GENERATED ALWAYS AS)
- arqueo_items (con diferencia GENERATED ALWAYS AS)
- plataformas_gift_card, gift_cards_virtuales_uso
- notificaciones

Las columnas `diferencia` en `arqueos` y `arqueo_items` son GENERATED ALWAYS AS STORED:
nunca se escriben desde el ORM, solo se leen.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0027'
down_revision: Union[str, None] = '80852ebe8f92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('plataformas_gift_card',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('nombre', sa.String(), nullable=False),
    sa.Column('activo', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('medios_pago_arqueo_config',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('medio_de_pago_id', sa.BigInteger(), nullable=False),
    sa.Column('agrupa_en_terminal', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('grupo_terminal', sa.String(), nullable=True),
    sa.Column('es_informativo', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['medio_de_pago_id'], ['medios_de_pago.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('medio_de_pago_id')
    )
    op.create_table('notificaciones',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('usuario_id', sa.BigInteger(), nullable=False),
    sa.Column('tipo', sa.Enum('diferencia_arqueo', name='tipo_notificacion'), nullable=False),
    sa.Column('titulo', sa.String(), nullable=False),
    sa.Column('cuerpo', sa.Text(), nullable=False),
    sa.Column('leida', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notificaciones_usuario_id'), 'notificaciones', ['usuario_id'], unique=False)
    op.create_table('turnos',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('punto_de_venta_id', sa.BigInteger(), nullable=False),
    sa.Column('estado', sa.Enum('abierto', 'cerrado', name='estado_turno'), server_default='abierto', nullable=False),
    sa.Column('efectivo_apertura', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('usuario_apertura_id', sa.BigInteger(), nullable=False),
    sa.Column('usuario_cierre_id', sa.BigInteger(), nullable=True),
    sa.Column('fecha_apertura', sa.DateTime(), nullable=False),
    sa.Column('fecha_cierre', sa.DateTime(), nullable=True),
    sa.Column('notas', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['punto_de_venta_id'], ['puntos_de_venta.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['usuario_apertura_id'], ['usuarios.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['usuario_cierre_id'], ['usuarios.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_turnos_punto_de_venta_id'), 'turnos', ['punto_de_venta_id'], unique=False)
    op.create_table('arqueos',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('turno_id', sa.BigInteger(), nullable=False),
    sa.Column('usuario_id', sa.BigInteger(), nullable=False),
    sa.Column('total_esperado', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('total_declarado', sa.Numeric(precision=10, scale=2), nullable=False),
    # GENERATED ALWAYS AS (total_declarado - total_esperado) STORED
    sa.Column('diferencia', sa.Numeric(precision=10, scale=2),
              sa.Computed('total_declarado - total_esperado', persisted=True)),
    sa.Column('notificacion_enviada', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['turno_id'], ['turnos.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('turno_id')
    )
    op.create_table('gift_cards_virtuales_uso',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('plataforma_id', sa.BigInteger(), nullable=False),
    sa.Column('venta_id', sa.BigInteger(), nullable=False),
    sa.Column('monto_consumido', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.Column('usuario_id', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['plataforma_id'], ['plataformas_gift_card.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['venta_id'], ['ventas.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_gift_cards_virtuales_uso_plataforma_id'), 'gift_cards_virtuales_uso', ['plataforma_id'], unique=False)
    op.create_index(op.f('ix_gift_cards_virtuales_uso_venta_id'), 'gift_cards_virtuales_uso', ['venta_id'], unique=False)
    op.create_table('retiros_efectivo',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('turno_id', sa.BigInteger(), nullable=False),
    sa.Column('monto', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('motivo', sa.String(), nullable=False),
    sa.Column('autorizado_por', sa.BigInteger(), nullable=False),
    sa.Column('realizado_por', sa.BigInteger(), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['autorizado_por'], ['usuarios.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['realizado_por'], ['usuarios.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['turno_id'], ['turnos.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_retiros_efectivo_turno_id'), 'retiros_efectivo', ['turno_id'], unique=False)
    op.create_table('turno_vendedoras',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('turno_id', sa.BigInteger(), nullable=False),
    sa.Column('usuario_id', sa.BigInteger(), nullable=False),
    sa.Column('ingreso', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['turno_id'], ['turnos.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('turno_id', 'usuario_id')
    )
    op.create_index(op.f('ix_turno_vendedoras_turno_id'), 'turno_vendedoras', ['turno_id'], unique=False)
    op.create_table('arqueo_items',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('arqueo_id', sa.BigInteger(), nullable=False),
    sa.Column('medio_de_pago_id', sa.BigInteger(), nullable=True),
    sa.Column('grupo_terminal', sa.String(), nullable=True),
    sa.Column('monto_esperado', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('monto_declarado', sa.Numeric(precision=10, scale=2), nullable=False),
    # GENERATED ALWAYS AS (monto_declarado - monto_esperado) STORED
    sa.Column('diferencia', sa.Numeric(precision=10, scale=2),
              sa.Computed('monto_declarado - monto_esperado', persisted=True)),
    sa.Column('es_informativo', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['arqueo_id'], ['arqueos.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['medio_de_pago_id'], ['medios_de_pago.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_arqueo_items_arqueo_id'), 'arqueo_items', ['arqueo_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_arqueo_items_arqueo_id'), table_name='arqueo_items')
    op.drop_table('arqueo_items')
    op.drop_index(op.f('ix_turno_vendedoras_turno_id'), table_name='turno_vendedoras')
    op.drop_table('turno_vendedoras')
    op.drop_index(op.f('ix_retiros_efectivo_turno_id'), table_name='retiros_efectivo')
    op.drop_table('retiros_efectivo')
    op.drop_index(op.f('ix_gift_cards_virtuales_uso_venta_id'), table_name='gift_cards_virtuales_uso')
    op.drop_index(op.f('ix_gift_cards_virtuales_uso_plataforma_id'), table_name='gift_cards_virtuales_uso')
    op.drop_table('gift_cards_virtuales_uso')
    op.drop_table('arqueos')
    op.drop_index(op.f('ix_turnos_punto_de_venta_id'), table_name='turnos')
    op.drop_table('turnos')
    op.drop_index(op.f('ix_notificaciones_usuario_id'), table_name='notificaciones')
    op.drop_table('notificaciones')
    op.drop_table('medios_pago_arqueo_config')
    op.drop_table('plataformas_gift_card')
    op.execute("DROP TYPE IF EXISTS estado_turno")
    op.execute("DROP TYPE IF EXISTS tipo_notificacion")
