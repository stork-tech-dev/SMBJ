"""
Lectura del header User-Agent.

Es lo único que un navegador expone sobre el equipo que se conecta: sistema
operativo, navegador y —en celulares— el modelo. El modelo o el número de
serie de una PC de escritorio NO se pueden obtener desde la web; eso
requeriría un agente instalado.

El string crudo se guarda SIEMPRE junto a lo parseado. El User-Agent es
notoriamente irregular y estas heurísticas van a fallar con algún navegador
raro: conservar el original permite corregir la interpretación después, o
cambiar esta función por una librería, sin haber perdido el dato.
"""

import re

# El orden importa: Edge y Opera se presentan también como Chrome, y Chrome
# se presenta también como Safari. Gana la primera coincidencia.
_NAVEGADORES: list[tuple[str, str]] = [
    (r"Edg[A-Z]?/([\d.]+)", "Edge"),
    (r"OPR/([\d.]+)", "Opera"),
    (r"SamsungBrowser/([\d.]+)", "Samsung Internet"),
    (r"Firefox/([\d.]+)", "Firefox"),
    (r"Chrome/([\d.]+)", "Chrome"),
    (r"Version/([\d.]+).*Safari", "Safari"),
]

_SISTEMAS: list[tuple[str, str]] = [
    # Android e iOS primero: sus User-Agent también mencionan Linux y Mac.
    (r"Android ([\d.]+)", "Android"),
    (r"(?:iPhone|iPad|iPod).*?OS ([\d_]+)", "iOS"),
    (r"Windows NT ([\d.]+)", "Windows"),
    (r"Mac OS X ([\d_.]+)", "macOS"),
    (r"(Ubuntu)", "Ubuntu"),
    (r"(Linux)", "Linux"),
]

# Equivalencias de Windows NT: la versión del kernel no es la comercial.
_WINDOWS = {"10.0": "10/11", "6.3": "8.1", "6.2": "8", "6.1": "7"}


def _mayor(version: str) -> str:
    """Solo el número mayor: 'Chrome 120' se lee mejor que 'Chrome 120.0.6099.109'."""
    return version.replace("_", ".").split(".")[0]


def navegador_de(user_agent: str) -> str | None:
    for patron, nombre in _NAVEGADORES:
        m = re.search(patron, user_agent)
        if m:
            return f"{nombre} {_mayor(m.group(1))}"
    return None


def sistema_de(user_agent: str) -> str | None:
    for patron, nombre in _SISTEMAS:
        m = re.search(patron, user_agent)
        if not m:
            continue

        valor = m.group(1)
        if nombre == "Windows":
            # Windows 10 y 11 comparten el NT 10.0: el navegador no los
            # distingue, así que se informa el par en vez de mentir.
            return f"Windows {_WINDOWS.get(valor, valor)}"
        if nombre in ("Ubuntu", "Linux"):
            return nombre
        return f"{nombre} {valor.replace('_', '.')}"
    return None


def modelo_de(user_agent: str) -> str | None:
    """
    Modelo del equipo, cuando el navegador lo informa.

    Solo aparece en móviles. En escritorio devuelve None: ni Windows ni
    macOS exponen la marca ni el modelo de la máquina.
    """
    # Android: "...; Android 13; SM-A536E Build/..." o "...; SM-A536E)"
    m = re.search(r"Android [\d.]+;\s*([^;)]+?)(?:\s+Build/|[;)])", user_agent)
    if m:
        modelo = m.group(1).strip()
        # "K" es el placeholder que usa Chrome desde que reduce el
        # User-Agent para no exponer el modelo exacto.
        if modelo and modelo not in {"K", "wv"}:
            return modelo

    for aparato in ("iPhone", "iPad", "iPod"):
        if aparato in user_agent:
            return aparato

    return None


def interpretar(user_agent: str | None) -> dict[str, str | None]:
    """
    Sistema operativo, navegador y modelo a partir del User-Agent.

    Devuelve las tres claves siempre, en None lo que no se pueda deducir:
    quien llama guarda el resultado tal cual, sin tener que preguntar.
    """
    ua = (user_agent or "").strip()
    if not ua:
        return {"sistema_operativo": None, "navegador": None, "modelo": None}

    return {
        "sistema_operativo": sistema_de(ua),
        "navegador": navegador_de(ua),
        "modelo": modelo_de(ua),
    }
