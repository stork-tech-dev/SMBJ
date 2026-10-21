"""
Motor de etiquetas Zebra: arma cada etiqueta y genera el ZPL y su vista
previa. Funciones puras, sin base ni ORM (como `app/core/codigos.py`): el
servicio `app/services/etiquetas.py` les pasa el rollo, el diseño y la ficha
de la impresora como diccionarios.
"""
