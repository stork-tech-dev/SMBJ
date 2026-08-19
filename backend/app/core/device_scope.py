"""
Aislamiento de datos por dispositivo.

Un vendedor ve y opera SOLO el local del equipo en el que está trabajando.
No es una preferencia de pantalla: es lo que evita que desde la caja de un
local se dé de baja mercadería de otro, o se confirme un remito ajeno.

La regla vive acá y en un solo lugar, y los endpoints la aplican pidiendo
la dependency `get_device_scope`. Reimplementarla en cada endpoint sería
garantizar que alguno quede sin ella: el que se olvide no falla, simplemente
deja ver todo.

El vendedor cuyo equipo todavía no tiene local asignado no ve nada. Es
deliberado: mostrarle el stock de todos los locales sería peor que no
mostrarle ninguno, y elegir uno por él sería adivinar.
"""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status

from app.core.device_deps import get_current_device
from app.core.permisos import ROL_VENDEDOR, get_current_user
from app.models.dispositivo import Dispositivo
from app.models.usuario import Usuario


@dataclass(frozen=True)
class DeviceScope:
    """
    A qué ubicación está limitada esta request.

    - `restringido=False` → sin límite: ve todos los puntos de venta.
    - `restringido=True` con `punto_de_venta_id` → solo esa ubicación.
    - `restringido=True` con `sin_asignacion=True` → no ve NADA: es un
      vendedor en un equipo que nadie asignó todavía.
    """

    restringido: bool
    punto_de_venta_id: int | None = None
    sin_asignacion: bool = False

    def permite(self, punto_de_venta_id: int | None) -> bool:
        """Si esta request puede tocar datos de esa ubicación."""
        if not self.restringido:
            return True
        if self.sin_asignacion or punto_de_venta_id is None:
            return False
        return punto_de_venta_id == self.punto_de_venta_id

    def exigir(self, punto_de_venta_id: int | None) -> None:
        """
        Corta con 403 si la ubicación no es la suya.

        Los endpoints la llaman con el punto de venta que viene en el cuerpo
        o en la URL: sin esto, un vendedor podría cambiar un id a mano y
        operar sobre otro local.
        """
        if self.permite(punto_de_venta_id):
            return
        if self.sin_asignacion:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=MENSAJE_SIN_ASIGNACION,
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo se puede operar sobre el local asignado a este dispositivo",
        )


# El texto lo muestran las tres pantallas del módulo y lo devuelve la API en
# el 403. Vive acá para que digan exactamente lo mismo (Principio 2).
MENSAJE_SIN_ASIGNACION = (
    "Este dispositivo no tiene un local asignado. Contactá al administrador."
)


def get_punto_de_venta_scope(
    usuario: Usuario, device: Dispositivo | None
) -> DeviceScope:
    """
    Resuelve el alcance de una request a partir del rol y del equipo.

    Solo el rol `vendedor` queda limitado. Los roles superiores —Supervisor,
    Distribución, Auditor, Dueño, Cuenta Maestra— trabajan sobre todos los
    locales: un supervisor que solo pudiera ver el local donde está parado
    no podría supervisar nada.
    """
    if usuario.rol is None or usuario.rol.nombre != ROL_VENDEDOR:
        return DeviceScope(restringido=False)

    # Un equipo sin registrar, desactivado o sin local asignado son el mismo
    # caso desde acá: no hay ubicación de la que hablar.
    if device is None or not device.activo or device.punto_de_venta_id is None:
        return DeviceScope(restringido=True, sin_asignacion=True)

    return DeviceScope(restringido=True, punto_de_venta_id=device.punto_de_venta_id)


def get_device_scope(
    device: Dispositivo | None = Depends(get_current_device),
    usuario: Usuario = Depends(get_current_user),
) -> DeviceScope:
    """
    La dependency que usan los endpoints de stock, remitos y auditoría.

    No corta la request por sí sola: un vendedor sin asignación tiene que
    poder abrir la pantalla y leer el motivo por el que está vacía. Lo que
    corta es `exigir()`, cuando se intenta operar sobre una ubicación
    concreta.
    """
    return get_punto_de_venta_scope(usuario, device)
