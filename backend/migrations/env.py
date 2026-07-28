"""Entorno de Alembic. La URL de la base sale siempre de config.settings."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importar el paquete de modelos completo registra todas las tablas en
# Base.metadata, que es lo que Alembic compara para autogenerar.
import app.models  # noqa: F401
from app.core.database import Base
from config import settings

config = context.config

# Por defecto la URL sale de settings, pero si alguien ya la definió en el
# objeto Config (los tests apuntan a una base descartable) se respeta.
url_configurada = config.get_main_option("sqlalchemy.url", None)
URL_BASE = url_configurada or settings.DATABASE_URL
config.set_main_option("sqlalchemy.url", URL_BASE)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Genera el SQL sin conectarse a la base."""
    context.configure(
        url=URL_BASE,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Aplica las migraciones contra la base real."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
