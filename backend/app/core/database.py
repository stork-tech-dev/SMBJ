"""
Conexión a PostgreSQL: engine, SessionLocal y Base declarativa.

Cualquier módulo que necesite una sesión de base de datos debe usar
la dependency `get_db()`; nunca instanciar SessionLocal a mano dentro
de un endpoint.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import settings

# pool_pre_ping evita errores por conexiones muertas cuando el contenedor
# de la base se reinicia durante el desarrollo.
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=settings.DEBUG and settings.APP_ENV == "development",
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


class Base(DeclarativeBase):
    """Base declarativa de todos los modelos SQLAlchemy del proyecto."""


def get_db() -> Generator[Session, None, None]:
    """Dependency de FastAPI: entrega una sesión y la cierra siempre."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
