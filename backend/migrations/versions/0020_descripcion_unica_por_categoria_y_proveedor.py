"""Una descripción no se repite dentro del mismo proveedor y categoría

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-15
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# La MISMA expresión que usa `_validar_descripcion_unica()` en
# app/services/productos.py, y la misma tabla de reemplazo que
# `sin_tildes()` en app/core/utils.py. Si cambia una tiene que cambiar la
# otra: el índice solo se usa si la comparación del service es idéntica, y
# si dejaran de coincidir la base aceptaría lo que el service rechaza.
CLAVE = (
    "lower(translate(descripcion, 'áéíóúüñÁÉÍÓÚÜÑ', 'aeiouunAEIOUUN')), "
    "categoria_id, proveedor_id"
)


def upgrade() -> None:
    """
    Índice único sobre (descripción, categoría, proveedor).

    Dos productos del mismo proveedor y la misma categoría con la misma
    descripción son, para quien mira el catálogo, el mismo producto
    cargado dos veces: no hay ningún dato en pantalla que permita
    distinguirlos. Lo que corresponde en ese caso es una variante del que
    ya existe, no un producto nuevo.

    Sin tildes y sin mayúsculas, porque "Cadena plata" y "cadena PLATA"
    tampoco se distinguen mirando la tabla.

    Incluye los inactivos: un producto dado de baja no se borra, sigue
    ocupando su descripción y se puede volver a activar. Reusarla dejaría
    dos filas idénticas apenas alguien lo reactive.
    """
    # Los duplicados que ya existan hacen fallar la creación del índice con
    # un error de Postgres que no dice cuáles son. Se buscan antes para
    # poder nombrarlos: la migración no los toca sola porque elegir cuál
    # sobrevive es una decisión del negocio, no de un script.
    duplicados = op.get_bind().exec_driver_sql(
        f"""
        SELECT string_agg(sku, ', ' ORDER BY sku) AS skus, min(descripcion) AS descripcion
        FROM productos
        GROUP BY {CLAVE}
        HAVING count(*) > 1
        """
    ).fetchall()

    if duplicados:
        detalle = "; ".join(f"{d.descripcion!r}: {d.skus}" for d in duplicados)
        raise RuntimeError(
            "Hay productos que ya comparten descripción, categoría y proveedor. "
            "Corregí la descripción de uno de cada grupo (o desactivá y renombrá "
            f"el que sobra) antes de aplicar esta migración → {detalle}"
        )

    op.execute(
        f"CREATE UNIQUE INDEX uq_productos_descripcion_por_categoria_y_proveedor "
        f"ON productos ({CLAVE})"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_productos_descripcion_por_categoria_y_proveedor")
