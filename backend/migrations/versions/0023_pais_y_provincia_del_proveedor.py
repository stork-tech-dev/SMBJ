"""Contacto y dirección del proveedor pasan a ser país y provincia

Revision ID: 0023
Revises: 0021
Create Date: 2026-08-19

NÚMERO SALTEADO A PROPÓSITO: la 0022 existe en la rama `05_stock` y todavía
no está acá. Esta cuelga de la 0021, así que las dos ramas corren solas; al
mergear van a quedar DOS cabezas colgando de la 0021 y hay que unirlas —lo
más simple es cambiar el `down_revision` de esta a "0022"—.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    `contacto` pasa a `pais` y `direccion` a `provincia`.

    Es un RENAME y no un par de columnas nuevas: lo que se pidió es que el
    proveedor se describa por dónde está, no por a quién llamar, así que los
    campos viejos no quedan. Renombrar conserva los índices y las
    restricciones que colgaran de la columna, cosa que agregar y borrar no
    haría.

    OJO CON LO QUE YA ESTÁ CARGADO: el contenido no se toca, solo el nombre.
    Un proveedor que tenía contacto "Juan Pérez" queda con país "Juan Pérez".
    No se limpia desde acá porque una migración no puede saber cuál de esos
    valores era una persona y cuál ya era un lugar; se revisa a mano después.

    Los tipos quedan como estaban (VARCHAR 200 y 255). Achicarlos ahora
    obligaría a truncar, y no hay nada que ganar.
    """
    op.alter_column("proveedores", "contacto", new_column_name="pais")
    op.alter_column("proveedores", "direccion", new_column_name="provincia")


def downgrade() -> None:
    op.alter_column("proveedores", "pais", new_column_name="contacto")
    op.alter_column("proveedores", "provincia", new_column_name="direccion")
