"""
Endpoint de consulta de auditoría. Solo lectura, por definición: la tabla
es append-only a nivel de base de datos.

Visible para Cuenta Maestra y Auditor. Se resuelve con el permiso del
módulo AUDITORIA, que el seed le da a esos dos roles.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permisos import Modulo, requiere_permiso
from app.schemas.auditoria import AuditoriaResponse
from app.schemas.comunes import RespuestaPaginada
from app.services import auditoria as servicio_auditoria

router = APIRouter(prefix="/auditoria", tags=["auditoria"])


@router.get(
    "", response_model=RespuestaPaginada[AuditoriaResponse], summary="Consultar auditoría"
)
def listar(
    usuario_id: int | None = Query(default=None),
    accion: str | None = Query(default=None, description="Coincidencia parcial, ej: 'venta.'"),
    entidad: str | None = Query(default=None),
    entidad_id: int | None = Query(default=None),
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.AUDITORIA, "ver")),
):
    filas, total = servicio_auditoria.listar_auditoria(
        db,
        usuario_id=usuario_id,
        accion=accion,
        entidad=entidad,
        entidad_id=entidad_id,
        desde=desde,
        hasta=hasta,
        pagina=pagina,
        tamano=tamano,
    )
    return RespuestaPaginada[AuditoriaResponse](
        total=total, pagina=pagina, tamano=tamano, resultados=filas  # type: ignore[arg-type]
    )
