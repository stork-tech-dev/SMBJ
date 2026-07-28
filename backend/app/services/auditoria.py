"""
Consulta de auditoría (solo lectura).

La escritura vive en `app/core/auditoria.py` y es la única vía de entrada
a la tabla. Acá solo se lee.
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria


def listar_auditoria(
    db: Session,
    usuario_id: int | None = None,
    accion: str | None = None,
    entidad: str | None = None,
    entidad_id: int | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    pagina: int = 1,
    tamano: int = 50,
) -> tuple[list[Auditoria], int]:
    """
    Listado con los filtros del Principio 5. `accion` filtra por prefijo,
    de modo que "venta." trae todas las acciones del módulo de ventas.
    """
    consulta = select(Auditoria)

    if usuario_id is not None:
        consulta = consulta.where(Auditoria.usuario_id == usuario_id)
    if accion:
        consulta = consulta.where(Auditoria.accion.ilike(f"%{accion}%"))
    if entidad:
        consulta = consulta.where(Auditoria.entidad.ilike(f"%{entidad}%"))
    if entidad_id is not None:
        consulta = consulta.where(Auditoria.entidad_id == entidad_id)
    if desde:
        consulta = consulta.where(func.date(Auditoria.timestamp) >= desde)
    if hasta:
        consulta = consulta.where(func.date(Auditoria.timestamp) <= hasta)

    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()

    filas = (
        db.execute(
            consulta.order_by(Auditoria.timestamp.desc(), Auditoria.id.desc())
            .limit(tamano)
            .offset((pagina - 1) * tamano)
        )
        .scalars()
        .all()
    )
    return list(filas), total
