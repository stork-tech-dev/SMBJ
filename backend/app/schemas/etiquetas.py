"""
Schemas del módulo de etiquetas (`/api/v1/etiquetas`).

`ParametrosDiseno` es el "archivo que explica cada campo" que pide el
cliente: cada parámetro lleva su `description`, que se ve en Swagger y en
la pantalla de Diseños. Todas las medidas van en milímetros.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Letras de mapa de puntos que trae la Zebra (ver `FUENTES_FIJAS` en el motor).
FuenteFija = Literal["D", "F"]


# ---------------------------------------------------------------------------
# Diseño: los parámetros
# ---------------------------------------------------------------------------


class _Estricto(BaseModel):
    # Un campo desconocido en un archivo subido es casi siempre un error de
    # tipeo: mejor rechazarlo que ignorarlo en silencio.
    model_config = ConfigDict(extra="forbid")


class ParametrosMatriz(_Estricto):
    modulos: int = Field(
        default=14, ge=10, le=24, title="Lado en módulos",
        description="Lado del código cuadrado (DataMatrix), en módulos. Siempre el mismo para "
                    "cualquier código: el aprobado es 14×14, que alcanza para 8 caracteres.",
    )
    modulo_mm: float = Field(
        default=0.5, gt=0, le=2, title="Tamaño del módulo (mm)",
        description="Tamaño de cada cuadradito (módulo), en mm. Se redondea a puntos enteros de la "
                    "impresora: 0,5 mm son 4 puntos a 203 dpi. 14 × 0,5 = código de 7 mm.",
    )
    blanco_min_mm: float = Field(
        default=1, ge=0, le=5, title="Blanco alrededor (mm)",
        description="Blanco mínimo alrededor del código en la etiqueta múltiple, en mm. Sin blanco "
                    "el celular no lo encuentra.",
    )


class ParametrosMultiple(_Estricto):
    numero_solo_fuente: FuenteFija = Field(
        default="F", title="Letra del número solo",
        description="Letra del número cuando la etiqueta no lleva texto (opción 1). F = 3,25 mm de "
                    "alto, D = 2,25 mm. Si el número no entra con esta, se usa la del número con texto.",
    )
    numero_fuente: FuenteFija = Field(
        default="D", title="Letra del número con texto",
        description="Letra del número debajo del texto (opción 2). D = 2,25 mm de alto.",
    )
    texto_max_mm: float = Field(
        default=2, gt=0, le=10, title="Alto máximo del texto (mm)",
        description="Alto máximo del texto libre, en mm. El texto se achica solo hasta entrar, sin "
                    "pasar este tope; siempre queda más chico que el número.",
    )
    margen_mm: float = Field(
        default=1, ge=0, le=5, title="Margen (mm)", description="Margen a los costados de lo escrito, en mm."
    )


class ParametrosColita(_Estricto):
    numero_fuente: FuenteFija = Field(
        default="D", title="Letra del número", description="Letra del número. D = 2,25 mm de alto."
    )
    texto_max_mm: float = Field(
        default=1.75, gt=0, le=10, title="Alto máximo del texto (mm)",
        description="Alto máximo del texto libre, en mm (se achica solo hasta entrar).",
    )
    blanco_mm: float = Field(
        default=2, ge=0, le=5, title="Blanco alrededor del código (mm)",
        description="Blanco mínimo alrededor del código cuadrado, en mm.",
    )
    margen_doblez_mm: float = Field(
        default=2, ge=0, le=8, title="Distancia al doblez (mm)",
        description="Distancia de lo escrito al doblez, en mm: la colita se pega doblada y lo que "
                    "quede encima del doblez se pierde si se dobla un poco corrida.",
    )
    margen_mm: float = Field(
        default=1, ge=0, le=5, title="Margen (mm)", description="Margen del lado opuesto al doblez, en mm."
    )


class ParametrosDiseno(_Estricto):
    """
    Parámetros de un diseño. El sistema completa los datos de cada etiqueta
    (código y texto) y aplica las reglas fijas para todos los diseños: pasar
    mm a puntos con los dpi, girar según el rollo, achicar el texto con su
    tope y avisar si algo no entra.
    """

    codigo_max: int = Field(
        default=8, ge=1, le=20, title="Máximo de caracteres del código",
        description="Máximo de caracteres del código del producto que acepta la etiqueta.",
    )
    separacion_texto_numero_mm: float = Field(
        default=0.5, ge=0, le=5, title="Separación texto-número (mm)",
        description="Separación entre el texto y el número de abajo (opción 2), en mm.",
    )
    matriz: ParametrosMatriz = Field(default_factory=ParametrosMatriz, description="El código cuadrado.")
    multiple: ParametrosMultiple = Field(
        default_factory=ParametrosMultiple, description="Rollos sin doblez (múltiple 32×10)."
    )
    colita: ParametrosColita = Field(
        default_factory=ParametrosColita, description="Rollos con doblez (colita 66×11)."
    )


# Grupos del formulario de la pantalla Diseños: (clave en los parámetros o
# None para los de primer nivel, título, modelo).
_GRUPOS_FORMULARIO = [
    (None, "General", ParametrosDiseno),
    ("matriz", "Código cuadrado", ParametrosMatriz),
    ("multiple", "Múltiple (3 por fila)", ParametrosMultiple),
    ("colita", "Colita (se pega doblada)", ParametrosColita),
]


def campos_de_diseno() -> list[dict]:
    """
    Los campos de `ParametrosDiseno` agrupados para armar el formulario:
    título, ayuda, límites y opciones salen de cada `Field`, así la pantalla
    no repite la explicación ni los rangos (Principio 2).
    """
    grupos = []
    for clave, titulo, modelo in _GRUPOS_FORMULARIO:
        esquema = modelo.model_json_schema()
        campos = []
        for nombre, prop in esquema["properties"].items():
            if "$ref" in prop or "allOf" in prop:  # los grupos anidados van aparte
                continue
            campos.append({
                "ruta": f"{clave}.{nombre}" if clave else nombre,
                "titulo": prop.get("title", nombre),
                "ayuda": prop.get("description", ""),
                "opciones": prop.get("enum"),
                "minimo": prop.get("minimum", prop.get("exclusiveMinimum")),
                "maximo": prop.get("maximum"),
                "entero": prop.get("type") == "integer",
            })
        grupos.append({"titulo": titulo, "campos": campos})
    return grupos


class DisenoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    parametros: ParametrosDiseno
    version: int
    archivado: bool
    updated_at: datetime


class DisenoCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    parametros: ParametrosDiseno


class DisenoEditar(BaseModel):
    """Edición parcial: lo que no viene no cambia. Cada edición es una versión nueva."""

    nombre: str | None = Field(default=None, min_length=1, max_length=80)
    parametros: ParametrosDiseno | None = None


class DisenoArchivo(_Estricto):
    """Lo que se baja y se sube como archivo: el nombre y sus parámetros."""

    nombre: str = Field(min_length=1, max_length=80)
    parametros: ParametrosDiseno


class DisenoVersionResponse(BaseModel):
    version: int
    nombre: str
    parametros: ParametrosDiseno
    usuario: str | None = Field(description="Quién la guardó; null = la cargó el sistema.")
    creado_en: datetime


class DisenoVistaPreviaRequest(BaseModel):
    """Parámetros SIN guardar, para ver cómo sale antes de guardar."""

    parametros: ParametrosDiseno


# ---------------------------------------------------------------------------
# Rollos e impresoras
# ---------------------------------------------------------------------------


class ImpresoraResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    browser_print: str
    dpi: int
    corrimiento_x_mm: Decimal
    corrimiento_y_mm: Decimal
    oscuridad: int
    velocidad: int


class ImpresoraCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=60)
    browser_print: str = Field(
        min_length=1, max_length=200,
        description="Nombre con el que la ve Zebra Browser Print (ej. \\\\STELLA\\ZDesigner GC420t (EPL)).",
    )


class ImpresoraEditar(BaseModel):
    """Edición parcial de la ficha."""

    nombre: str | None = Field(default=None, min_length=1, max_length=60)
    browser_print: str | None = Field(default=None, min_length=1, max_length=200)
    corrimiento_x_mm: Decimal | None = Field(default=None, ge=-10, le=10)
    corrimiento_y_mm: Decimal | None = Field(default=None, ge=-10, le=10)
    oscuridad: int | None = Field(default=None, ge=0, le=30)
    velocidad: int | None = Field(default=None, ge=2, le=6)


class FormatoResponse(BaseModel):
    """Un rollo, con la impresora que lo imprime."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    clave: str
    nombre: str
    ancho_rollo_mm: Decimal
    columnas: int
    paso_mm: Decimal
    ancho_mm: Decimal
    alto_mm: Decimal
    zona_desde_mm: Decimal
    zona_hasta_mm: Decimal
    doblez_mm: Decimal | None
    giro: str
    impresora_id: int | None


class AsignarImpresora(BaseModel):
    impresora_id: int | None = Field(description="La impresora que imprime este rollo; null = ninguna.")


class ZplResponse(BaseModel):
    """ZPL listo para mandar a la impresora (prueba o calibrar)."""

    zpl: str
    vista_previa: str | None = None


# ---------------------------------------------------------------------------
# Imprimir
# ---------------------------------------------------------------------------


class RenglonOrigen(BaseModel):
    """Un producto para imprimir, tal como llega de una compra o de un código."""

    variante_id: int
    codigo: str = Field(description="Código de la etiqueta, con su dígito verificador.")
    descripcion: str
    variante: str | None = Field(description="Descripción de la variante; null = la variante base.")
    copias: int


class OrigenResponse(BaseModel):
    renglones: list[RenglonOrigen]


class EtiquetaPedida(BaseModel):
    """
    Un renglón a imprimir. El código NO viaja: lo pone el servidor desde
    `variante_id`, así no se imprime un código que no existe.
    """

    variante_id: int | None = Field(default=None, description="null = etiqueta solo texto.")
    texto: str | None = Field(default=None, max_length=60)
    copias: int = Field(1, ge=0, le=999)
    formato_id: int = Field(description="El rollo de ESTE renglón.")


class PrepararRequest(BaseModel):
    diseno_id: int
    etiquetas: list[EtiquetaPedida] = Field(max_length=500)


class AvisoEtiqueta(BaseModel):
    nivel: Literal["error", "ojo"] = Field(description="error = no deja imprimir; ojo = revisar.")
    texto: str


class ImpresoraDelGrupo(BaseModel):
    id: int
    nombre: str
    browser_print: str


class GrupoPreparado(BaseModel):
    """Las etiquetas de UN rollo, listas para su impresora."""

    formato_id: int
    formato_nombre: str
    impresora: ImpresoraDelGrupo | None
    trabajos: list[str] = Field(description="Órdenes ZPL, una por fila (las filas iguales, con ^PQ).")
    filas: int
    total_etiquetas: int
    avisos: list[AvisoEtiqueta]
    vista_previa: list[str] = Field(description="SVG de cada fila distinta, hasta 6.")
    puede_imprimir: bool


class PrepararResponse(BaseModel):
    grupos: list[GrupoPreparado]
    avisos: list[AvisoEtiqueta]
    total_etiquetas: int
    puede_imprimir: bool


class RolloVistaPrevia(BaseModel):
    formato_id: int
    formato_nombre: str
    vista_previa: list[str]
    zpl: list[str]
    avisos: list[AvisoEtiqueta]


class DisenoVistaPreviaResponse(BaseModel):
    rollos: list[RolloVistaPrevia]
