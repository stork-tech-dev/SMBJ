"""
Instancia única de Jinja2Templates (Principio 2: DRY).

Cualquier router que renderice HTML importa `templates` desde acá;
nunca instancia Jinja2Templates por su cuenta.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from config import settings

templates = Jinja2Templates(directory="app/templates")

# Resuelto desde este archivo y no como ruta relativa al CWD: si el
# directorio no se encontrara, todas las URLs saldrían sin versión y el
# problema de caché volvería en silencio, que es justo lo que se evita.
_ESTATICOS = Path(__file__).resolve().parents[1] / "static"


def estatico(path: str) -> str:
    """
    URL de un archivo estático con su versión colgada como `?v=`.

    Existe porque StaticFiles no manda `Cache-Control`, y sin esa cabecera
    el navegador aplica caché heurística: se queda con la copia vieja del
    .js o del .css sin revalidar. El resultado es una pantalla corriendo
    código de una versión anterior, que falla de formas difíciles de
    diagnosticar (una función que "no existe", un handler que no responde).

    La versión es el mtime del archivo, así que cambia sola en cada
    edición y fuerza al navegador a pedirlo de nuevo. En los templates se
    usa `estatico('/js/app.js')` en lugar de `url_for('static', ...)`.
    """
    relativo = path.lstrip("/")
    archivo = _ESTATICOS / relativo
    try:
        version = int(archivo.stat().st_mtime)
    except OSError:
        # Si el archivo no está (typo en el path, build incompleto) se
        # devuelve la URL sin versión en vez de romper el render entero.
        return f"/static/{relativo}"
    return f"/static/{relativo}?v={version}"


# Variables disponibles en todos los templates sin pasarlas en cada
# render(): evita repetirlas endpoint por endpoint.
templates.env.globals["APP_NAME"] = settings.APP_NAME
templates.env.globals["APP_ENV"] = settings.APP_ENV
templates.env.globals["estatico"] = estatico
