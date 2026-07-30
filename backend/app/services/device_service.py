"""
Lógica de negocio de dispositivos.

Incluye el flujo de identificación (cookie → fingerprint → alta) y el ABM
administrativo. Todo lo que corresponde queda registrado en `auditoria`.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria, snapshot
from app.core.utils import ahora_db
from app.models.dispositivo import Dispositivo
from app.models.punto_de_venta import PuntoDeVenta, TipoPuntoVenta
from app.repositories.device_repository import DeviceRepository
from app.services.roles import NoEncontrado, ReglaDeNegocio


class DeviceService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = DeviceRepository(db)

    # ------------------------------------------------------------------
    # Identificación (sin autenticación de usuario)
    # ------------------------------------------------------------------

    def identificar_dispositivo(
        self,
        uuid_cookie: str | None,
        fingerprint: str | None,
        ip: str | None,
        user_agent: str | None = None,
    ) -> tuple[Dispositivo, bool]:
        """
        Resuelve qué dispositivo corresponde a esta request y lo devuelve
        junto con un flag `set_cookie` (True cuando hay que escribir/renovar
        la cookie en la response).

        Flujo:
          1. Cookie válida  → actualizar último acceso.
          2. Sin cookie pero fingerprint de un dispositivo ACTIVO → restaurar.
          3. En cualquier otro caso → crear uno nuevo, inactivo.

        NO hace commit: lo hace quien llama (el endpoint o el middleware).
        """
        # 1. Cookie que apunta a un dispositivo existente.
        if uuid_cookie:
            dispositivo = self.repo.get_by_uuid(uuid_cookie)
            if dispositivo is not None:
                self.repo.update_last_access(dispositivo, ip, user_agent)
                # En una navegación normal el dispositivo se crea sin
                # fingerprint (el navegador no manda el header). Cuando el
                # frontend luego llama con el fingerprint, se completa acá,
                # para que la recuperación futura funcione.
                if fingerprint and not dispositivo.fingerprint:
                    dispositivo.fingerprint = fingerprint
                    self.db.flush()
                return dispositivo, False

        # 2. Recuperación por fingerprint, solo si el dispositivo está activo.
        if fingerprint:
            candidato = self.repo.get_by_fingerprint(fingerprint)
            if candidato is not None and candidato.activo:
                self.repo.update_last_access(candidato, ip, user_agent)
                registrar_auditoria(
                    self.db,
                    usuario_id=None,
                    accion="dispositivo.restaurado_por_fingerprint",
                    entidad="dispositivos",
                    entidad_id=candidato.id,
                    ip_origen=ip,
                )
                # Se reescribe la cookie con el uuid recuperado.
                return candidato, True

        # 3. Alta de un dispositivo nuevo (inactivo, sin local).
        dispositivo = self.repo.create(
            fingerprint=fingerprint, ip=ip, user_agent=user_agent
        )
        registrar_auditoria(
            self.db,
            usuario_id=None,
            accion="dispositivo.creado",
            entidad="dispositivos",
            entidad_id=dispositivo.id,
            estado_nuevo={"uuid": str(dispositivo.uuid)},
            ip_origen=ip,
        )
        return dispositivo, True

    # ------------------------------------------------------------------
    # Administración (Cuenta Maestra y Dueño)
    # ------------------------------------------------------------------

    def obtener(self, device_id: int) -> Dispositivo:
        dispositivo = self.repo.get_by_id(device_id)
        if dispositivo is None:
            raise NoEncontrado("Dispositivo inexistente")
        return dispositivo

    def listar(
        self,
        descripcion: str | None = None,
        punto_de_venta_id: int | None = None,
        activo: bool | None = None,
        acceso_desde: date | None = None,
        acceso_hasta: date | None = None,
    ) -> list[Dispositivo]:
        return self.repo.list_all(
            descripcion=descripcion,
            punto_de_venta_id=punto_de_venta_id,
            activo=activo,
            acceso_desde=acceso_desde,
            acceso_hasta=acceso_hasta,
        )

    def _validar_local(self, punto_de_venta_id: int | None) -> None:
        """Solo se pueden asignar puntos de venta de tipo 'local'."""
        if punto_de_venta_id is None:
            return
        punto = self.db.get(PuntoDeVenta, punto_de_venta_id)
        if punto is None:
            raise NoEncontrado("Punto de venta inexistente")
        if punto.tipo != TipoPuntoVenta.LOCAL:
            raise ReglaDeNegocio("Solo se pueden asignar puntos de venta de tipo local")

    def actualizar(
        self,
        device_id: int,
        usuario_id: int,
        ip: str | None,
        descripcion: str | None = None,
        punto_de_venta_id: int | None = None,
        observaciones: str | None = None,
        activo: bool | None = None,
        asignar_local: bool = False,
    ) -> Dispositivo:
        """
        Edita un dispositivo. `uuid` y `fingerprint` NO son editables: no se
        exponen como parámetros.

        `asignar_local` distingue "no tocar el local" (False) de "poner el
        local en este valor, incluso NULL" (True), ya que None es ambiguo.
        """
        dispositivo = self.obtener(device_id)
        antes = snapshot(dispositivo)
        local_previo = dispositivo.punto_de_venta_id

        if descripcion is not None:
            dispositivo.descripcion = descripcion or "Sin asignar"
        if observaciones is not None:
            dispositivo.observaciones = observaciones
        if activo is not None:
            dispositivo.activo = activo
        if asignar_local:
            self._validar_local(punto_de_venta_id)
            dispositivo.punto_de_venta_id = punto_de_venta_id

        dispositivo.updated_at = ahora_db()
        self.db.flush()

        registrar_auditoria(
            self.db,
            usuario_id=usuario_id,
            accion="dispositivo.editado",
            entidad="dispositivos",
            entidad_id=dispositivo.id,
            estado_anterior=antes,
            estado_nuevo=dispositivo,
            ip_origen=ip,
        )

        # Registro específico cuando cambia la asignación de local.
        if asignar_local and dispositivo.punto_de_venta_id != local_previo:
            registrar_auditoria(
                self.db,
                usuario_id=usuario_id,
                accion="dispositivo.asignado_local",
                entidad="dispositivos",
                entidad_id=dispositivo.id,
                estado_anterior={"punto_de_venta_id": local_previo},
                estado_nuevo={"punto_de_venta_id": dispositivo.punto_de_venta_id},
                ip_origen=ip,
            )

        return dispositivo

    def _cambiar_estado(
        self, device_id: int, activo: bool, usuario_id: int, ip: str | None
    ) -> Dispositivo:
        dispositivo = self.obtener(device_id)
        antes = snapshot(dispositivo)
        dispositivo.activo = activo
        dispositivo.updated_at = ahora_db()
        self.db.flush()

        registrar_auditoria(
            self.db,
            usuario_id=usuario_id,
            accion="dispositivo.reactivado" if activo else "dispositivo.desactivado",
            entidad="dispositivos",
            entidad_id=dispositivo.id,
            estado_anterior=antes,
            estado_nuevo=dispositivo,
            ip_origen=ip,
        )
        return dispositivo

    def desactivar(self, device_id: int, usuario_id: int, ip: str | None) -> Dispositivo:
        return self._cambiar_estado(device_id, False, usuario_id, ip)

    def reactivar(self, device_id: int, usuario_id: int, ip: str | None) -> Dispositivo:
        return self._cambiar_estado(device_id, True, usuario_id, ip)


def local_a_saludar(db: Session, uuid_dispositivo: str | None) -> str | None:
    """
    Nombre del punto de venta con el que saludar en el login, o None.

    Solo saluda a dispositivos **activos y con local asignado**: es el
    mismo criterio que `get_active_device`, el que habilita a un celular a
    operar. Un dispositivo recién creado (inactivo y sin local) no muestra
    nada, que es lo correcto — todavía no pertenece a ningún local.

    Resuelve el dispositivo desde la cookie con la sesión del request y no
    desde `request.state.device`. Dos motivos: ese snapshot lo deja el
    middleware, que en los tests está apagado —la feature quedaría sin
    poder probarse—, y así la consulta usa la misma sesión que el resto de
    la página.

    Es de SOLO LECTURA: a diferencia de `identificar_dispositivo`, no crea
    un dispositivo si no lo encuentra. Renderizar el login no debe tener
    efectos secundarios.
    """
    if not uuid_dispositivo:
        return None

    # get_by_uuid ya devuelve None ante un uuid mal formado, así que una
    # cookie manipulada no rompe la pantalla de login.
    dispositivo = DeviceRepository(db).get_by_uuid(uuid_dispositivo)
    if (
        dispositivo is None
        or not dispositivo.activo
        or dispositivo.punto_de_venta_id is None
    ):
        return None

    punto = db.get(PuntoDeVenta, dispositivo.punto_de_venta_id)
    # Un local dado de baja no se saluda: sería confuso.
    if punto is None or not punto.activo:
        return None
    return punto.nombre
