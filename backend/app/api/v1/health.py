"""Router de healthcheck: estado de la aplicación y de la base de datos."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.health import HealthDBResponse, HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse, summary="Estado de la aplicación")
async def health() -> HealthResponse:
    """Responde 200 si la aplicación está levantada. No toca la base."""
    return HealthResponse(status="ok")


@router.get("/db", response_model=HealthDBResponse, summary="Estado de la base de datos")
async def health_db(db: Session = Depends(get_db)) -> HealthDBResponse:
    """Verifica que la conexión a PostgreSQL responda."""
    try:
        db.execute(text("SELECT 1"))
        return HealthDBResponse(status="ok", database="ok")
    except Exception as exc:  # noqa: BLE001 - el detalle se devuelve tipado
        return HealthDBResponse(status="degraded", database="error", detalle=str(exc))
