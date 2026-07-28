"""
Instancia única de Jinja2Templates (Principio 2: DRY).

Cualquier router que renderice HTML importa `templates` desde acá;
nunca instancia Jinja2Templates por su cuenta.
"""

from fastapi.templating import Jinja2Templates

from config import settings

templates = Jinja2Templates(directory="app/templates")

# Variables disponibles en todos los templates sin pasarlas en cada
# render(): evita repetirlas endpoint por endpoint.
templates.env.globals["APP_NAME"] = settings.APP_NAME
templates.env.globals["APP_ENV"] = settings.APP_ENV
