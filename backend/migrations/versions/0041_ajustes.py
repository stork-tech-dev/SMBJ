"""Ajustes: parámetros del negocio que pasan del código a `configuracion_sistema`.

Revision ID: 0041
Revises: 0040
Create Date: 2026-09-29

Hasta acá estaban fijos en el código; ahora los edita la Cuenta Maestra desde
"Ajustes". Nacen con el valor que tenía el código, así que migrar no cambia
ningún comportamiento:

- `tope_descuento_venta` (50): tope de la SUMA del descuento del producto y
  el de la venta. Distinto de `descuento_maximo`, que es el tope del
  descuento propio de cada producto.
- `paso_descuento` (5): la lista de porcentajes de la vendedora es paso,
  2·paso, … hasta el tope de la venta.
- `pesos_por_punto` (1000): cuántos pesos de venta valen un punto.
- `dias_plazo_cambio` (30): plazo habitual para un cambio (pasado, avisa).
"""

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

_TABLA = "configuracion_sistema"


def upgrade() -> None:
    op.add_column(_TABLA, sa.Column("tope_descuento_venta", sa.Numeric(5, 2), nullable=False, server_default="50"))
    op.add_column(_TABLA, sa.Column("paso_descuento", sa.Integer(), nullable=False, server_default="5"))
    op.add_column(_TABLA, sa.Column("pesos_por_punto", sa.Numeric(10, 2), nullable=False, server_default="1000"))
    op.add_column(_TABLA, sa.Column("dias_plazo_cambio", sa.Integer(), nullable=False, server_default="30"))

    op.create_check_constraint(
        "ck_config_tope_descuento_venta", _TABLA,
        "tope_descuento_venta > 0 AND tope_descuento_venta <= 100",
    )
    op.create_check_constraint(
        "ck_config_paso_descuento", _TABLA,
        "paso_descuento > 0 AND paso_descuento <= tope_descuento_venta",
    )
    op.create_check_constraint("ck_config_pesos_por_punto", _TABLA, "pesos_por_punto > 0")
    op.create_check_constraint("ck_config_dias_plazo_cambio", _TABLA, "dias_plazo_cambio > 0")


def downgrade() -> None:
    for nombre in ("ck_config_dias_plazo_cambio", "ck_config_pesos_por_punto",
                   "ck_config_paso_descuento", "ck_config_tope_descuento_venta"):
        op.drop_constraint(nombre, _TABLA, type_="check")
    for columna in ("dias_plazo_cambio", "pesos_por_punto", "paso_descuento", "tope_descuento_venta"):
        op.drop_column(_TABLA, columna)
