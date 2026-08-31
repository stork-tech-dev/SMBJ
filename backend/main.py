"""
Punto de entrada de la aplicación FastAPI.

Monta dos cosas:
  - `/api/v1/...`  → la API REST, contrato principal del sistema
  - `/`, `/login`  → el HTML servido con Jinja2 (mismo proceso, sin build)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.pages import router as pages_router
from app.api.v1 import api_router
from app.middleware.auth_refresh_middleware import AuthRefreshMiddleware
from app.middleware.device_middleware import DeviceMiddleware
from config import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Arranque y apagado de la aplicación."""
    # Los modelos se importan acá para que queden registrados en Base
    # aunque nadie los haya importado todavía.
    import app.models  # noqa: F401

    yield


# La documentación interactiva se publica solo fuera de producción. Swagger,
# ReDoc y el openapi.json no exigen autenticación y describen la API entera
# —endpoints, esquemas, nombres de campos—, así que en un servidor público
# son un mapa del sistema para cualquiera que entre a la URL.
_ES_PRODUCCION = settings.APP_ENV == "production"

app = FastAPI(
    title=settings.APP_NAME,
    description="ERP Soleil / Mallorca — API v1",
    version="0.1.0",
    docs_url=None if _ES_PRODUCCION else "/docs",
    redoc_url=None if _ES_PRODUCCION else "/redoc",
    openapi_url=None if _ES_PRODUCCION else "/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS_LIST,
    allow_credentials=True,  # necesario para la cookie HttpOnly del JWT
    allow_methods=["*"],
    allow_headers=["*"],
)

# Identificación de dispositivos: deja request.state.device disponible y
# gestiona la cookie device_uuid. Se saltea en rutas de infraestructura.
app.add_middleware(DeviceMiddleware)

# Renovación de la sesión: si la cookie de acceso venció y el refresh sigue
# vivo, emite una nueva antes de que el handler mire quién es el usuario.
app.add_middleware(AuthRefreshMiddleware)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# API REST versionada.
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# HTML. Se monta último para que las rutas de la API tengan prioridad.
app.include_router(pages_router)
