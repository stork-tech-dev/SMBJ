"""Los permisos con recurso NULL tampoco se pueden repetir

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLAS = (
    ("rol_permisos", "rol_id", "uq_rol_permisos_rol_modulo_recurso"),
    ("usuario_permisos", "usuario_id", "uq_usuario_permisos_usuario_modulo_recurso"),
)


def upgrade() -> None:
    """
    El UNIQUE `(propietario, modulo, recurso)` no impedía duplicados cuando
    `recurso` era NULL —en PostgreSQL NULL no es igual a NULL—, y `recurso =
    NULL` es justamente "acceso al módulo completo": el caso más común.

    Consecuencias que esto arregla:

    1. `rol_permisos` llegó a tener 45 filas repetidas, y eso rompía el alta y
       la edición de usuarios: `_fila()` usa `scalar_one_or_none()`, así que
       guardar los accesos devolvía 500.
    2. El `ON CONFLICT (rol_id, modulo, recurso) DO NOTHING` del seed
       (`seed.sql:192`) era un no-op para esas mismas filas: `ON CONFLICT` se
       apoya en el índice único, y sin conflicto detectable no hay nada que
       saltear. El seed pide correrse dos veces (`seed.sql:129`), así que los
       duplicados volvían solos.

    `NULLS NOT DISTINCT` (PostgreSQL 15+) trata los NULL como iguales, y con
    eso las dos cosas se arreglan de una: no entran más duplicados y el
    ON CONFLICT del seed empieza a funcionar como su autor quiso, sin tocarlo.
    """
    for tabla, propietario, restriccion in TABLAS:
        # `IS NOT DISTINCT FROM` y no `=`: con `=` los NULL no matchean entre
        # sí y este DELETE no borraría NADA — que es exactamente el error que
        # causó el problema que viene a limpiar.
        #
        # Se conserva el id más bajo de cada grupo. Los duplicados que hay son
        # idénticos en sus cuatro flags, así que no se pierde configuración.
        op.execute(
            f"""
            DELETE FROM {tabla} a
            USING {tabla} b
            WHERE a.{propietario} = b.{propietario}
              AND a.modulo = b.modulo
              AND a.recurso IS NOT DISTINCT FROM b.recurso
              AND a.id > b.id
            """
        )

        # La limpieza corre también sobre `usuario_permisos`, que hoy no tiene
        # duplicados: si los tuviera, el ADD CONSTRAINT de abajo fallaría.
        op.execute(f"ALTER TABLE {tabla} DROP CONSTRAINT {restriccion}")
        op.execute(
            f"ALTER TABLE {tabla} ADD CONSTRAINT {restriccion} "
            f"UNIQUE NULLS NOT DISTINCT ({propietario}, modulo, recurso)"
        )


def downgrade() -> None:
    """
    Vuelve al UNIQUE común, que deja pasar duplicados con recurso NULL.

    Las filas borradas no se restauran: eran copias exactas de las que
    quedaron, así que no hay nada que recuperar.
    """
    for tabla, propietario, restriccion in TABLAS:
        op.execute(f"ALTER TABLE {tabla} DROP CONSTRAINT {restriccion}")
        op.execute(
            f"ALTER TABLE {tabla} ADD CONSTRAINT {restriccion} "
            f"UNIQUE ({propietario}, modulo, recurso)"
        )
