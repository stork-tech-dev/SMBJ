"""
Endpoints de notificaciones para el usuario logueado.
Solo el propio usuario puede ver y marcar sus notificaciones.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permisos import Modulo, requiere_permiso
from app.models.turno import Notificacion
from app.schemas.notificaciones import NotificacionResponse

router = APIRouter(prefix="/notificaciones", tags=["notificaciones"])


@router.get("", response_model=list[NotificacionResponse])
def listar_notificaciones(
    solo_no_leidas: bool = False,
    usuario=Depends(requiere_permiso(Modulo.CAJA, "ver")),
    db: Session = Depends(get_db),
):
    """Lista las notificaciones del usuario autenticado."""
    stmt = (
        select(Notificacion)
        .where(Notificacion.usuario_id == usuario.id)
        .order_by(Notificacion.created_at.desc())
    )
    if solo_no_leidas:
        stmt = stmt.where(Notificacion.leida.is_(False))
    filas = db.execute(stmt).scalars().all()
    return [
        NotificacionResponse(
            id=n.id,
            tipo=n.tipo.value,
            titulo=n.titulo,
            cuerpo=n.cuerpo,
            leida=n.leida,
            metadata_=n.metadata_,
            created_at=n.created_at,
        )
        for n in filas
    ]


@router.patch("/{notificacion_id}/leer", response_model=NotificacionResponse)
def marcar_leida(
    notificacion_id: int,
    usuario=Depends(requiere_permiso(Modulo.CAJA, "ver")),
    db: Session = Depends(get_db),
):
    """Marca una notificación como leída. Solo el propietario puede hacerlo."""
    notif = db.execute(
        select(Notificacion).where(
            Notificacion.id == notificacion_id,
            Notificacion.usuario_id == usuario.id,
        )
    ).scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notificación no encontrada")
    notif.leida = True
    db.commit()
    db.refresh(notif)
    return NotificacionResponse(
        id=notif.id,
        tipo=notif.tipo.value,
        titulo=notif.titulo,
        cuerpo=notif.cuerpo,
        leida=notif.leida,
        metadata_=notif.metadata_,
        created_at=notif.created_at,
    )


@router.patch("/leer-todas", status_code=status.HTTP_204_NO_CONTENT)
def marcar_todas_leidas(
    usuario=Depends(requiere_permiso(Modulo.CAJA, "ver")),
    db: Session = Depends(get_db),
):
    """Marca todas las notificaciones no leídas del usuario como leídas."""
    db.execute(
        update(Notificacion)
        .where(Notificacion.usuario_id == usuario.id, Notificacion.leida.is_(False))
        .values(leida=True)
    )
    db.commit()
