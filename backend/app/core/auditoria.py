"""
Auditoría inmutable (Principio 3).

`registrar_auditoria()` es la ÚNICA forma de escribir en la tabla
`auditoria`. Todos los services la llaman; nadie instancia el modelo
Auditoria directamente.

Regla de transaccionalidad: esta función NO hace commit. Se ejecuta
dentro de la misma transacción que la acción que audita, de modo que
si la acción falla no queda registro huérfano, y si el registro falla
la acción tampoco se confirma. El commit lo hace el service que
orquesta la operación completa.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.utils import ahora_db, ip_de_request
from app.models.auditoria import Auditoria

# Claves que nunca deben quedar registradas en los snapshots JSON.
CAMPOS_SENSIBLES = frozenset(
    {
        "password",
        "password_hash",
        "clave_especial",
        "clave_especial_hash",
        "pin",
        "pin_hash",
        "token",
        "access_token",
        "refresh_token",
    }
)


def _serializar(valor: Any) -> Any:
    """Convierte un valor Python cualquiera en algo que JSONB acepte."""
    if isinstance(valor, Enum):
        return valor.value
    if isinstance(valor, Decimal):
        # str y no float: preserva la precisión exacta del importe.
        return str(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, UUID):
        return str(valor)
    if isinstance(valor, dict):
        return {k: _serializar(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple, set)):
        return [_serializar(v) for v in valor]
    return valor


def snapshot(obj: Any, campos: list[str] | None = None) -> dict | None:
    """
    Convierte un modelo SQLAlchemy (o un dict) en un dict JSON-safe apto
    para `estado_anterior` / `estado_nuevo`, filtrando campos sensibles.

    `campos` permite limitar el snapshot a un subconjunto de columnas.
    """
    if obj is None:
        return None

    if isinstance(obj, dict):
        crudo = dict(obj)
    else:
        crudo = {
            col.name: getattr(obj, col.name)
            for col in obj.__table__.columns  # type: ignore[attr-defined]
        }

    if campos is not None:
        crudo = {k: v for k, v in crudo.items() if k in campos}

    return {k: _serializar(v) for k, v in crudo.items() if k not in CAMPOS_SENSIBLES}


def registrar_auditoria(
    db: Session,
    *,
    accion: str,
    entidad: str,
    usuario_id: int | None = None,
    entidad_id: int | None = None,
    estado_anterior: Any = None,
    estado_nuevo: Any = None,
    ip_origen: str | None = None,
    request: Request | None = None,
) -> Auditoria:
    """
    Registra una acción sensible en la tabla `auditoria`.

    Args:
        db: sesión activa — la MISMA en la que se ejecuta la acción auditada.
        accion: verbo con formato "<entidad>.<verbo>", ej. "venta.anular".
        entidad: nombre de la tabla o entidad de negocio afectada.
        usuario_id: autor de la acción; None cuando la ejecuta el sistema.
        entidad_id: id del registro afectado, si aplica.
        estado_anterior / estado_nuevo: modelo, dict o None. Solo se
            completan cuando la acción modifica datos existentes.
        ip_origen: IP explícita; si no se pasa, se toma del `request`.
        request: request de FastAPI del que extraer la IP.

    Returns:
        La instancia de Auditoria ya agregada a la sesión (sin commit).
    """
    registro = Auditoria(
        usuario_id=usuario_id,
        accion=accion,
        entidad=entidad,
        entidad_id=entidad_id,
        estado_anterior=snapshot(estado_anterior),
        estado_nuevo=snapshot(estado_nuevo),
        ip_origen=ip_origen if ip_origen is not None else ip_de_request(request),
        timestamp=ahora_db(),
    )
    db.add(registro)
    # flush y no commit: valida la escritura contra la base (dispara el
    # trigger de inmutabilidad si algo intentara un UPDATE) sin cerrar la
    # transacción del service que llama.
    db.flush()
    return registro
