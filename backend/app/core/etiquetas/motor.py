"""
Arma cada etiqueta (posiciones en puntos) y genera el ZPL.

Es el diseño APROBADO el 19/10/2026 (código cuadrado DataMatrix + número con
letra de mapa de puntos), probado en papel en las dos Zebra GC420t y leído
con un Samsung A04. Se portó del prototipo del cliente
(`prototipo-etiquetas/app/motor.py`) con dos correcciones para que salga
exactamente el ZPL de su documento: 203 dpi son 8 puntos por mm justos (no
203/25,4) y la velocidad va como `^PRv,v,v`.

Reglas generales:
  - Todo se define en MILÍMETROS (rollo y diseño) y se pasa a puntos con
    los dpi de la ficha de la impresora.
  - El armado devuelve una lista de ELEMENTOS en puntos. De esa misma lista
    salen el ZPL (`zpl_fila`) y la vista previa (`vista_previa.py`): lo que
    se ve es lo que se imprime.
  - Los ajustes de la impresora (oscuridad, velocidad, corrimiento, giro)
    van DENTRO del ZPL. Browser Print no regula nada: solo entrega el texto.

Tipos de elemento (en puntos; x/y = esquina de arriba a la izquierda):
  ("matriz", x, y, lado, modulo, codigo)                 DataMatrix ECC 200 de tamaño fijo
  ("texto",  x, y, ancho, alto_letra, renglones, texto)  letra 0 (escalable), centrado
  ("fijo",   x, y, ancho, fuente, codigo)                letra de mapa de puntos (D, F), centrado

Las tres opciones de cada etiqueta salen solas:
  1 = solo código (cuadradito + número)   2 = código + texto   3 = solo texto
"""

import re
from dataclasses import dataclass, field

# Puntos por mm según la resolución. Las Zebra de 203 dpi son de 8 puntos
# por mm exactos: con 203/25,4 = 7,99 el ancho del rollo de 102 mm daba 815
# puntos en vez de los 816 que se probaron. Solo 203 dpi por ahora: las
# letras de mapa de puntos (`FUENTES_FIJAS`) cambian de tamaño con los dpi.
PUNTOS_POR_MM = {203: 8}

# Letras de mapa de puntos de la Zebra a 203 dpi: (alto, ancho, espacio
# entre caracteres) en puntos. A 300 dpi miden otra cosa: por ahora el motor
# solo acepta 203 dpi (ver `DpiNoSoportado`).
FUENTES_FIJAS = {"D": (18, 10, 2), "F": (26, 13, 3)}

# DataMatrix ECC 200 cuadrados: (lado en módulos, palabras de datos que entran).
DM_TAMANOS = [(10, 3), (12, 5), (14, 8), (16, 12), (18, 18), (20, 22), (22, 30), (24, 36)]

CARACTERES_VALIDOS = re.compile(r"^[A-Z0-9]+$")
# Por debajo de 1,5 mm (12 puntos) la letra 0 ya no se lee bien.
LETRA_MIN = 12


class DpiNoSoportado(ValueError):
    """La ficha pide una resolución para la que el motor no tiene letras."""


@dataclass
class Aviso:
    nivel: str  # "error" (no deja imprimir) | "ojo" (imprime, pero revisar)
    texto: str


@dataclass
class Etiqueta:
    """Una etiqueta pedida: código (o None = solo texto), texto y copias."""

    codigo: str | None
    texto: str | None = None
    copias: int = 1


@dataclass
class Armado:
    elementos: list = field(default_factory=list)
    avisos: list = field(default_factory=list)


def avisos_sin_repetir(avisos: list[Aviso]) -> list[dict]:
    """Los avisos como diccionarios, sin el mismo texto dos veces."""
    vistos, salida = set(), []
    for a in avisos:
        if a.texto not in vistos:
            vistos.add(a.texto)
            salida.append({"nivel": a.nivel, "texto": a.texto})
    return salida


class Motor:
    """
    `formato` es el rollo: {nombre, ancho_rollo_mm, columnas, paso_mm,
    etiqueta: {ancho_mm, alto_mm}, zona_mm: [desde, hasta], doblez_mm, giro}.
    `diseno` son los parámetros del diseño (ver `ParametrosDiseno` en
    `app/schemas/etiquetas.py`).
    """

    def __init__(self, formato: dict, diseno: dict, dpi: int = 203):
        if dpi not in PUNTOS_POR_MM:
            raise DpiNoSoportado(
                f"Por ahora solo se imprime en impresoras de 203 dpi (la ficha dice {dpi})."
            )
        self.f = formato
        self.d = diseno
        self.dpmm = PUNTOS_POR_MM[dpi]
        self.colita = formato.get("doblez_mm") is not None
        self.cfg = diseno["colita"] if self.colita else diseno["multiple"]

    # ------------------------------------------------------------ utilidades

    def p(self, mm: float) -> int:
        """Milímetros → puntos de la impresora."""
        return round(mm * self.dpmm)

    def mm(self, puntos: int) -> float:
        return round(puntos / self.dpmm, 2)

    @staticmethod
    def partir(texto: str, renglones: int) -> list[str]:
        """
        Reparte las palabras en N renglones parejos. El mismo corte va al ZPL
        (con `\\&`) y a la vista previa, así se ven iguales.
        """
        if renglones <= 1:
            return [texto]
        objetivo = len(texto) / renglones
        filas, actual = [], ""
        for palabra in texto.split():
            if actual and len(actual) + 1 + len(palabra) > objetivo and len(filas) < renglones - 1:
                filas.append(actual)
                actual = palabra
            else:
                actual = (actual + " " + palabra).strip()
        filas.append(actual)
        return filas

    def letra_que_entra(
        self, texto: str, ancho: int, alto_max: int, tope_mm: float, max_renglones: int, avisos: list
    ) -> tuple[int, int]:
        """
        Alto de letra (puntos) y renglones para que el texto entre sin pasar
        el tope. En la letra 0 de la Zebra cada carácter ocupa ~0,6 del alto.
        Se queda con la cantidad de renglones que da la letra más grande.
        """
        tope = self.p(tope_mm)
        mejor = (0, 1)
        for ren in range(1, max_renglones + 1):
            largo = max(len(f) for f in self.partir(texto, ren))
            alto = min(int(ancho / (largo * 0.6)), alto_max // ren, tope)
            if alto > mejor[0]:
                mejor = (alto, ren)
        letra, ren = mejor
        if letra < LETRA_MIN:
            avisos.append(Aviso("error", f'"{texto}" no entra en la etiqueta: acortalo.'))
            letra = LETRA_MIN
        elif letra < tope:
            avisos.append(Aviso("ojo", f'"{texto}" se achicó a {self.mm(letra)} mm para entrar.'))
        if ren > 1:
            avisos.append(Aviso("ojo", f'"{texto}" va en {ren} renglones.'))
        return letra, ren

    @staticmethod
    def datamatrix_modulos(codigo: str) -> int:
        """
        Lado (módulos) del DataMatrix más chico donde entra el código, en
        modo ASCII: cada par de dígitos es 1 palabra, cada letra es 1.
        """
        palabras, i = 0, 0
        while i < len(codigo):
            i += 2 if codigo[i : i + 2].isdigit() and i + 1 < len(codigo) else 1
            palabras += 1
        return next(lado for lado, cap in DM_TAMANOS if cap >= palabras)

    def matriz(self, codigo: str, ancho: int, alto: int, blanco_mm: float):
        """
        Lado (módulos), módulo (puntos) y lado (puntos) del cuadradito:
        SIEMPRE el mismo tamaño (14×14), el más grande que entra dejando el
        blanco pedido, sin pasar el módulo del diseño.
        """
        cfg = self.d["matriz"]
        n = max(cfg["modulos"], self.datamatrix_modulos(codigo))
        modulo = min(self.p(cfg["modulo_mm"]), (min(ancho, alto) - 2 * self.p(blanco_mm)) // n)
        return n, modulo, n * modulo

    @staticmethod
    def ancho_fijo(fuente: str, texto: str) -> int:
        _, w, g = FUENTES_FIJAS[fuente]
        return len(texto) * (w + g) - g

    def validar_codigo(self, codigo: str, avisos: list) -> bool:
        if not CARACTERES_VALIDOS.match(codigo):
            avisos.append(Aviso(
                "error", f'El código "{codigo}" tiene caracteres no válidos (solo letras A-Z y números).'
            ))
            return False
        if len(codigo) > self.d["codigo_max"]:
            avisos.append(Aviso(
                "error", f'El código "{codigo}" tiene más de {self.d["codigo_max"]} caracteres.'
            ))
            return False
        return True

    def texto_y_numero(self, x, ancho, alto, texto, codigo, avisos) -> list:
        """
        Texto libre + número abajo (letra de mapa de puntos, más grande que
        el texto), como UN bloque centrado de arriba a abajo.
        """
        fuente = self.cfg["numero_fuente"]
        an = FUENTES_FIJAS[fuente][0]
        sep, borde = self.p(self.d["separacion_texto_numero_mm"]), self.p(0.5)
        letra, ren = self.letra_que_entra(
            texto, ancho, alto - 2 * borde - sep - an, self.cfg["texto_max_mm"], 2, avisos
        )
        y0 = (alto - (letra * ren + sep + an)) // 2
        return [
            ("texto", x, y0, ancho, letra, ren, texto),
            ("fijo", x, y0 + letra * ren + sep, ancho, fuente, codigo),
        ]

    # ------------------------------------------------------------ armado

    def armar(self, x0: int, et: Etiqueta) -> Armado:
        """Elementos de UNA etiqueta. `x0` = dónde empieza en el rollo (puntos)."""
        a = Armado()
        codigo = (et.codigo or "").strip().upper() or None
        # ^ y ~ son comandos de ZPL: en un texto libre romperían la etiqueta.
        texto = (et.texto or "").replace("^", "").replace("~", "").strip() or None
        if not codigo and not texto:
            a.avisos.append(Aviso("error", "Una etiqueta no tiene ni código ni texto."))
            return a
        if codigo and not self.validar_codigo(codigo, a.avisos):
            return a
        if self.colita:
            self._armar_colita(x0, codigo, texto, a)
        else:
            self._armar_multiple(x0, codigo, texto, a)
        return a

    def _armar_multiple(self, x0, codigo, texto, a: Armado):
        """Múltiple: cuadradito a la izquierda y lo escrito al costado."""
        zx0, zx1 = x0 + self.p(self.f["zona_mm"][0]), x0 + self.p(self.f["zona_mm"][1])
        alto, margen = self.p(self.f["etiqueta"]["alto_mm"]), self.p(self.cfg["margen_mm"])
        if not codigo:  # opción 3: solo texto
            aw, ah = zx1 - zx0 - 2 * margen, alto - 2 * margen
            letra, ren = self.letra_que_entra(texto, aw, ah, self.cfg["texto_max_mm"], 3, a.avisos)
            a.elementos.append(("texto", zx0 + margen, (alto - letra * ren) // 2, aw, letra, ren, texto))
            return
        blanco = self.p(self.d["matriz"]["blanco_min_mm"])
        n, modulo, lado = self.matriz(codigo, zx1 - zx0, alto, self.d["matriz"]["blanco_min_mm"])
        a.elementos.append(("matriz", zx0 + blanco, (alto - lado) // 2, lado, modulo, codigo))
        xd = zx0 + blanco + lado + blanco  # lo escrito, después del blanco
        aw = zx1 - margen - xd
        if not texto:  # opción 1
            fuente = self.cfg["numero_solo_fuente"]
            if self.ancho_fijo(fuente, codigo) > aw:
                fuente = self.cfg["numero_fuente"]
            an = FUENTES_FIJAS[fuente][0]
            a.elementos.append(("fijo", xd, (alto - an) // 2, aw, fuente, codigo))
            return
        a.elementos += self.texto_y_numero(xd, aw, alto, texto, codigo, a.avisos)  # opción 2

    def _armar_colita(self, x0, codigo, texto, a: Armado):
        """
        Colita: se pega DOBLADA al medio. Cara 1 (la punta) = cuadradito
        solo; cara 2 = número, o texto + número. Lo escrito, lejos del doblez.
        """
        zx0, zx1 = x0 + self.p(self.f["zona_mm"][0]), x0 + self.p(self.f["zona_mm"][1])
        alto, margen = self.p(self.f["etiqueta"]["alto_mm"]), self.p(self.cfg["margen_mm"])
        mitad, md = self.p(self.f["doblez_mm"]), self.p(self.cfg["margen_doblez_mm"])
        if not codigo:  # opción 3: el texto en las dos caras
            for xc, xf in ((zx0 + margen, zx0 + mitad - md), (zx0 + mitad + md, zx1 - margen)):
                aw, ah = xf - xc, alto - 2 * margen
                letra, ren = self.letra_que_entra(texto, aw, ah, self.cfg["texto_max_mm"], 3, a.avisos)
                a.elementos.append(("texto", xc, (alto - letra * ren) // 2, aw, letra, ren, texto))
            return
        n, modulo, lado = self.matriz(codigo, mitad, alto, self.cfg["blanco_mm"])
        a.elementos.append(("matriz", zx0 + (mitad - lado) // 2, (alto - lado) // 2, lado, modulo, codigo))
        xc, aw = zx0 + mitad + md, zx1 - margen - (zx0 + mitad + md)
        if not texto:  # opción 1
            fuente = self.cfg["numero_fuente"]
            an = FUENTES_FIJAS[fuente][0]
            a.elementos.append(("fijo", xc, (alto - an) // 2, aw, fuente, codigo))
            return
        a.elementos += self.texto_y_numero(xc, aw, alto, texto, codigo, a.avisos)  # opción 2

    # ------------------------------------------------------------ filas y ZPL

    def filas(self, etiquetas: list[Etiqueta]) -> list[list[Etiqueta]]:
        """Reparte las etiquetas (con sus copias) en filas del rollo: de a 3 en la múltiple."""
        todas = [Etiqueta(e.codigo, e.texto, 1) for e in etiquetas for _ in range(max(0, e.copias))]
        c = self.f["columnas"]
        return [todas[i : i + c] for i in range(0, len(todas), c)]

    def armar_fila(self, fila: list[Etiqueta]) -> Armado:
        total = Armado()
        for i, et in enumerate(fila):
            a = self.armar(i * self.p(self.f["paso_mm"]), et)
            total.elementos += a.elementos
            total.avisos += a.avisos
        return total

    def zpl_fila(self, fila: list[Etiqueta], ficha: dict, copias: int = 1) -> tuple[str, list]:
        """
        ZPL de UNA fila del rollo con los ajustes de la ficha. `copias` va
        como `^PQ`: filas iguales seguidas son una sola orden.
        """
        a = self.armar_fila(fila)
        # El corrimiento se SUMA a cada posición: `^LH` no acepta negativos.
        dx, dy = self.p(ficha.get("corrimiento_x_mm", 0)), self.p(ficha.get("corrimiento_y_mm", 0))

        def fo(x, y):
            return f"^FO{max(0, x + dx)},{max(0, y + dy)}"

        velocidad = int(ficha.get("velocidad", 2))
        z = [
            "^XA",
            "^CI28",  # UTF-8: ñ y tildes
            f"~SD{int(ficha.get('oscuridad', 14)):02d}",
            f"^PR{velocidad},{velocidad},{velocidad}",
            f"^PW{self.p(self.f['ancho_rollo_mm'])}",
            f"^LL{self.p(self.f['etiqueta']['alto_mm'])}",
            "^LH0,0",
            "^POI" if self.f["giro"] == "invertido" else "^PON",
        ]
        for e in a.elementos:
            if e[0] == "matriz":
                _, x, y, lado, m, c = e
                n = lado // m
                z.append(f"{fo(x, y)}^BXN,{m},200,{n},{n}^FD{c}^FS")
            elif e[0] == "fijo":
                _, x, y, w, fuente, c = e
                h, ancho_f, _ = FUENTES_FIJAS[fuente]
                z.append(f"{fo(x, y)}^A{fuente}N,{h},{ancho_f}^FB{w},1,0,C^FD{c}^FS")
            else:
                _, x, y, w, letra, ren, t = e
                lineas = "\\&".join(self.partir(t, ren))  # \& = salto de renglón en ^FB
                z.append(f"{fo(x, y)}^A0N,{letra},{letra}^FB{w},{ren},0,C^FD{lineas}^FS")
        z += [f"^PQ{max(1, copias)}", "^XZ"]
        return "\n".join(z) + "\n", a.avisos

    def trabajos(self, etiquetas: list[Etiqueta], ficha: dict) -> tuple[list[str], list, list]:
        """
        Las órdenes ZPL de todas las etiquetas: una por fila del rollo, y
        las filas IGUALES seguidas en UNA sola orden con `^PQ`. Diez colitas
        del mismo producto son 1 orden, no 10: menos envíos a Browser Print
        y menos chance de que algo quede a medias.

        Devuelve (órdenes ZPL, avisos, filas).
        """
        filas = self.filas(etiquetas)
        ordenes, avisos, i = [], [], 0
        while i < len(filas):
            clave = [(e.codigo, e.texto) for e in filas[i]]
            n = 1
            while i + n < len(filas) and [(e.codigo, e.texto) for e in filas[i + n]] == clave:
                n += 1
            zpl, av = self.zpl_fila(filas[i], ficha, copias=n)
            ordenes.append(zpl)
            avisos += av
            i += n
        return ordenes, avisos, filas


def zpl_calibrar() -> str:
    """Calibrar el rollo: la Zebra avanza unas etiquetas y mide el largo y el espacio."""
    return "~JC\n"
