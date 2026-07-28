"""
Acceso a datos de dispositivos (Repository Pattern).

Concentra todas las queries de la tabla `dispositivos`. El service y el
middleware no arman queries: pasan por acá. Ninguna regla de negocio vive
en el repositorio — solo lectura y escritura.
"""

import uuid as uuid_lib
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.utils import ahora_db
from app.models.dispositivo import Dispositivo


class DeviceRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, device_id: int) -> Dispositivo | None:
        return self.db.get(Dispositivo, device_id)

    def get_by_uuid(self, uuid: str | uuid_lib.UUID) -> Dispositivo | None:
        try:
            valor = uuid if isinstance(uuid, uuid_lib.UUID) else uuid_lib.UUID(str(uuid))
        except (ValueError, AttributeError):
            return None
        return self.db.execute(
            select(Dispositivo).where(Dispositivo.uuid == valor)
        ).scalar_one_or_none()

    def get_by_fingerprint(self, fingerprint: str) -> Dispositivo | None:
        """
        Dispositivo más reciente con ese fingerprint. Se toma el último
        creado por si el mismo navegador generó varios registros.
        """
        if not fingerprint:
            return None
        return self.db.execute(
            select(Dispositivo)
            .where(Dispositivo.fingerprint == fingerprint)
            .order_by(Dispositivo.id.desc())
        ).scalars().first()

    def create(
        self, fingerprint: str | None, ip: str | None, uuid: uuid_lib.UUID | None = None
    ) -> Dispositivo:
        """Crea un dispositivo nuevo, inactivo y sin local, como pide el flujo."""
        dispositivo = Dispositivo(
            uuid=uuid or uuid_lib.uuid4(),
            fingerprint=fingerprint,
            punto_de_venta_id=None,
            descripcion="Sin asignar",
            activo=False,
            fecha_alta=ahora_db(),
            ultimo_acceso=ahora_db(),
            ultima_ip=ip,
            created_at=ahora_db(),
            updated_at=ahora_db(),
        )
        self.db.add(dispositivo)
        self.db.flush()
        return dispositivo

    def update_last_access(self, dispositivo: Dispositivo, ip: str | None) -> Dispositivo:
        dispositivo.ultimo_acceso = ahora_db()
        if ip:
            dispositivo.ultima_ip = ip
        self.db.flush()
        return dispositivo

    def list_all(
        self,
        descripcion: str | None = None,
        punto_de_venta_id: int | None = None,
        activo: bool | None = None,
        acceso_desde: date | None = None,
        acceso_hasta: date | None = None,
    ) -> list[Dispositivo]:
        from sqlalchemy import func

        consulta = select(Dispositivo)
        if descripcion:
            consulta = consulta.where(Dispositivo.descripcion.ilike(f"%{descripcion}%"))
        if punto_de_venta_id is not None:
            consulta = consulta.where(Dispositivo.punto_de_venta_id == punto_de_venta_id)
        if activo is not None:
            consulta = consulta.where(Dispositivo.activo.is_(activo))
        if acceso_desde:
            consulta = consulta.where(func.date(Dispositivo.ultimo_acceso) >= acceso_desde)
        if acceso_hasta:
            consulta = consulta.where(func.date(Dispositivo.ultimo_acceso) <= acceso_hasta)

        return list(
            self.db.execute(consulta.order_by(Dispositivo.fecha_alta.desc())).scalars().all()
        )
