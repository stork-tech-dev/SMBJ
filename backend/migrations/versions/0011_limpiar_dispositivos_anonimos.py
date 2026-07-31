"""Limpia los dispositivos que se registraban por cada visita anónima

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-30
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Borra los dispositivos que nadie aprobó nunca.

    Hasta esta versión el middleware daba de alta un dispositivo en cada
    visita sin cookie, incluida la pantalla de login: un visitante casual o
    un bot dejaban una fila. El alta pasó al login, pero los registros ya
    generados quedan.

    El criterio es conservador: solo se van los que están inactivos Y sin
    local asignado, que es exactamente lo que produce una visita anónima.
    Cualquier dispositivo que un admin haya activado o asignado se conserva,
    aunque hubiera nacido de una visita.

    Va como migración y no como script suelto porque en producción estos
    registros también se van a haber generado durante las pruebas.
    """
    op.execute(
        """
        DELETE FROM dispositivos
        WHERE activo = false
          AND punto_de_venta_id IS NULL
        """
    )


def downgrade() -> None:
    """
    No hay vuelta atrás: se borraron datos, no estructura.

    Los dispositivos eliminados no tenían información que valiera la pena
    conservar —ni local, ni activación, ni nadie que los usara— y sus altas
    quedaron registradas en `auditoria`, que es append-only.
    """
    pass
