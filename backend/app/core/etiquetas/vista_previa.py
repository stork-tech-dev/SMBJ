"""
Vista previa en SVG, armada con los MISMOS elementos que el ZPL
(`motor.Armado`): lo que se ve es lo que se imprime.

Se dibuja derecha (como se lee), aunque el rollo salga girado de la
impresora. El cuadradito es un DataMatrix real (`ppf.datamatrix`): se puede
leer con el celular desde la pantalla. Las letras son aproximadas: la letra 0
de la Zebra es una Helvetica angosta, y las D y F de mapa de puntos se
dibujan con una letra de ancho fijo.

Portado del prototipo del cliente (`prototipo-etiquetas/app/vista_previa.py`).
"""

from html import escape

from ppf.datamatrix import DataMatrix

from app.core.etiquetas.motor import FUENTES_FIJAS, Motor

GRIS_COLITA = "#e4e7eb"


def _matriz(x, y, lado, codigo):
    """
    La impresora completa un código corto hasta 14×14; la librería arma el
    más chico posible (ej. 12×12) y no deja elegir el tamaño. Se estira al
    lado real para que se vea del mismo tamaño: el dibujo de puntos puede no
    ser idéntico al impreso, pero se lee igual.
    """
    filas = DataMatrix(codigo).matrix
    m = lado / len(filas)
    partes = [
        f'<rect x="{x + j * m:.2f}" y="{y + i * m:.2f}" width="{m:.2f}" height="{m:.2f}"/>'
        for i, fila in enumerate(filas)
        for j, punto in enumerate(fila)
        if punto
    ]
    return f'<g fill="#000">{"".join(partes)}</g>'


def _texto(x, y, ancho, letra, renglones, texto, motor: Motor):
    partes = []
    for i, linea in enumerate(motor.partir(texto, renglones)):
        base = y + letra * (i + 1) - letra * 0.18
        partes.append(
            f'<text x="{x + ancho / 2:.1f}" y="{base:.1f}" font-size="{letra * 0.95:.1f}" '
            f'font-family="Arial Narrow, Arial, sans-serif" font-weight="700" text-anchor="middle" '
            f'textLength="{min(ancho, len(linea) * letra * 0.55):.1f}" lengthAdjust="spacingAndGlyphs">'
            f"{escape(linea)}</text>"
        )
    return "".join(partes)


def _fijo(x, y, ancho, fuente, codigo):
    alto, w, g = FUENTES_FIJAS[fuente]
    x0 = x + (ancho - (len(codigo) * (w + g) - g)) / 2
    return "".join(
        f'<text x="{x0 + i * (w + g) + w / 2:.1f}" y="{y + alto * 0.86:.1f}" font-size="{alto * 1.05:.1f}" '
        f'font-family="Consolas, Courier New, monospace" font-weight="700" text-anchor="middle" '
        f'textLength="{w:.1f}" lengthAdjust="spacingAndGlyphs">{escape(ch)}</text>'
        for i, ch in enumerate(codigo)
    )


def svg_fila(motor: Motor, fila) -> str:
    """
    SVG de una fila del rollo: el contorno de cada etiqueta (siempre la fila
    entera, para que todas queden a la misma escala), la colita en gris y el
    doblez punteado.
    """
    f = motor.f
    alto = motor.p(f["etiqueta"]["alto_mm"])
    ancho_et = motor.p(f["etiqueta"]["ancho_mm"])
    paso = motor.p(f["paso_mm"])
    cols = f["columnas"]
    total = paso * (cols - 1) + ancho_et
    a = motor.armar_fila(fila)
    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-4 -4 {total + 8} {alto + 8}" '
        f'class="w-full h-auto" role="img" aria-label="Vista previa de la etiqueta">'
    ]
    for i in range(cols):
        x = i * paso
        vacia = i >= len(fila)  # lugar de la fila que queda sin etiqueta
        relleno = "#f1f3f5" if vacia else "#fff"
        punteado = ' stroke-dasharray="4 3"' if vacia else ""
        partes.append(
            f'<rect x="{x}" y="0" width="{ancho_et}" height="{alto}" rx="6" '
            f'fill="{relleno}" stroke="#9aa5b1" stroke-width="1.5"{punteado}/>'
        )
        z1 = motor.p(f["zona_mm"][1])
        if z1 < ancho_et:  # la colita no se imprime
            partes.append(
                f'<rect x="{x + z1}" y="1" width="{ancho_et - z1 - 1}" height="{alto - 2}" '
                f'fill="{GRIS_COLITA}"/>'
            )
        if f.get("doblez_mm") is not None:
            xd = x + motor.p(f["zona_mm"][0] + f["doblez_mm"])
            partes.append(
                f'<line x1="{xd}" y1="-3" x2="{xd}" y2="{alto + 3}" stroke="#c0392b" '
                f'stroke-width="1" stroke-dasharray="4 3"/>'
            )
    for e in a.elementos:
        if e[0] == "matriz":
            _, x, y, lado, _m, c = e
            partes.append(_matriz(x, y, lado, c))
        elif e[0] == "fijo":
            _, x, y, w, fuente, c = e
            partes.append(_fijo(x, y, w, fuente, c))
        else:
            _, x, y, w, letra, ren, t = e
            partes.append(_texto(x, y, w, letra, ren, t, motor))
    partes.append("</svg>")
    return "".join(partes)
