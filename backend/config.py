"""
Configuración central de la aplicación.

Todas las variables de entorno se declaran acá y en ningún otro lado.
Ningún módulo debe leer os.environ directamente: siempre importar
`settings` desde este archivo.
"""

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Variables de entorno tipadas y validadas al arranque."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Aplicación ---
    APP_NAME: str = "Soleil ERP"
    APP_ENV: str = "development"  # development | production
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # URL pública del sistema. Se usa para armar los links de los emails.
    APP_URL: str = "http://localhost:8000"

    # --- Zona horaria del negocio (UTC-03:00, Argentina) ---
    TIMEZONE: str = "America/Argentina/Buenos_Aires"

    # --- Base de datos ---
    POSTGRES_USER: str = "soleil"
    POSTGRES_PASSWORD: str = "soleil"
    POSTGRES_DB: str = "soleil"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432

    # Si se define DATABASE_URL explícitamente, tiene prioridad sobre
    # las variables sueltas de arriba.
    DATABASE_URL_OVERRIDE: str | None = Field(default=None, alias="DATABASE_URL")

    # --- JWT (usado a fondo en el módulo 02) ---
    JWT_SECRET: str = "cambiar-esta-clave-en-produccion"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_MINUTES: int = 30
    JWT_REFRESH_TOKEN_DAYS: int = 7

    # Cuánto se tolera sin actividad antes de cerrar la sesión.
    #
    # Es una constante APARTE de `JWT_ACCESS_TOKEN_MINUTES` aunque hoy valgan
    # lo mismo: una dice cuánto vale un token y la otra cuánta inactividad se
    # acepta. Confundirlas fue exactamente lo que dejó la sesión sin vencer —
    # los 30 minutos eran la vida del access token, que el middleware renovaba
    # en silencio con el refresh de 7 días.
    #
    # Tiene que ser >= al access token: si fuera menor, un token todavía
    # vigente dejaría entrar después de vencida la ventana. Lo cuida
    # `test_el_access_no_puede_durar_mas_que_la_ventana`.
    SESION_INACTIVIDAD_MINUTOS: int = 30
    JWT_COOKIE_NAME: str = "soleil_access_token"
    JWT_REFRESH_COOKIE_NAME: str = "soleil_refresh_token"
    # Secure=True exige HTTPS: se activa solo en producción.
    COOKIE_SECURE: bool = False

    # --- Identificación de dispositivos (módulo 03b) ---
    DEVICE_COOKIE_NAME: str = "device_uuid"
    DEVICE_COOKIE_MAX_AGE: int = 60 * 60 * 24 * 365 * 5  # 5 años
    DEVICE_FINGERPRINT_HEADER: str = "X-Device-Fingerprint"
    # Se puede apagar el middleware de dispositivos (los tests lo hacen para
    # no crear filas fuera de su transacción).
    DEVICE_MIDDLEWARE_ENABLED: bool = True

    # --- CORS ---
    # Lista separada por comas en el .env: "http://localhost:8000,http://localhost"
    CORS_ORIGINS: str = "http://localhost:8000,http://localhost"

    # --- SMTP (recuperación de contraseña, módulo 02) ---
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str = "no-reply@soleil.local"
    SMTP_TLS: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:
        """URL de conexión a PostgreSQL para SQLAlchemy."""
        if self.DATABASE_URL_OVERRIDE:
            return self.DATABASE_URL_OVERRIDE
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def CORS_ORIGINS_LIST(self) -> list[str]:
        """CORS_ORIGINS parseado como lista."""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def TZ(self) -> ZoneInfo:
        """Zona horaria del negocio como objeto ZoneInfo."""
        return ZoneInfo(self.TIMEZONE)


@lru_cache
def get_settings() -> Settings:
    """Instancia única de Settings (cacheada)."""
    return Settings()


settings = get_settings()
