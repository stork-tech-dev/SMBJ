"""Schemas del módulo de productos."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

_TEMPORADA = "^(atemporal|otoño_invierno|primavera_verano)$"


class ProductoCrear(BaseModel):
    """
    `sku`, `precio_venta` y las variantes no están: los genera el backend.

    Si el cliente pudiera mandar el SKU rompería el correlativo de la
    secuencia; si pudiera mandar el precio de venta, ese precio dejaría de
    derivarse del dólar del proveedor y la cascada quedaría inservible.
    """

    categoria_id: int
    proveedor_id: int
    precio_usd: Decimal = Field(gt=0, description="Precio en dólares, mayor a cero")
    # Obligatoria: es por donde se lee y se ordena el catálogo. `min_length`
    # sobre el valor ya sin espacios, para que " " no pase por descripción.
    descripcion: str = Field(min_length=1, description="Cómo se identifica el producto")
    sku_proveedor: str | None = Field(default=None, max_length=30)
    descuento_producto: Decimal | None = Field(default=None, ge=0, le=100)
    peso_gramos: Decimal | None = Field(default=None, gt=0)
    temporada: str = Field(default="atemporal", pattern=_TEMPORADA)
    stock_infinito: bool = False


class ProductoEditar(BaseModel):
    """
    Todo opcional. El SKU y el proveedor no se editan: el SKU está impreso
    en las etiquetas y cambiar de proveedor movería la base del precio.
    """

    categoria_id: int | None = None
    # Opcional porque la edición es parcial: no mandarla es "no la cambies".
    # Pero mandarla vacía sería dejar el producto sin identificación, y la
    # columna ya no lo admite.
    descripcion: str | None = Field(default=None, min_length=1)
    sku_proveedor: str | None = Field(default=None, max_length=30)
    precio_usd: Decimal | None = Field(default=None, gt=0)
    descuento_producto: Decimal | None = Field(default=None, ge=0, le=100)
    peso_gramos: Decimal | None = Field(default=None, gt=0)
    temporada: str | None = Field(default=None, pattern=_TEMPORADA)
    stock_infinito: bool | None = None


class PrecioPreview(BaseModel):
    """
    Valores informativos del formulario, calculados por el backend.

    Ambos crudos: el formato de moneda lo pone el frontend (Principio 1).
    """

    dolar_proveedor: Decimal
    precio_venta: Decimal


class ProductoEstado(BaseModel):
    activo: bool


class VarianteCrear(BaseModel):
    sufijo: str = Field(min_length=1, max_length=1, description="Un carácter alfanumérico")
    # Cómo se nombra la variante en pantalla ("Rojo", "Talle 42"). Obligatoria:
    # es lo que reemplaza al "variante R" que no dice nada.
    descripcion_sufijo: str = Field(
        min_length=1, max_length=60, description="Nombre legible de la variante"
    )
    ubicacion_deposito: str | None = Field(default=None, max_length=100)
    stock_minimo: int = Field(default=0, ge=0)


class VarianteEditar(BaseModel):
    """
    Lo único editable de una variante.

    `sufijo`, `codigo_completo` y `verificador` NO están: el código se congela
    al crearse porque la etiqueta ya se imprimió y está pegada a la
    mercadería. Cambiarlo dejaría sin producto a lo que hay en el depósito.
    """

    descripcion_sufijo: str | None = Field(default=None, min_length=1, max_length=60)
    ubicacion_deposito: str | None = Field(default=None, max_length=100)
    stock_minimo: int | None = Field(default=None, ge=0)
    # Precio propio de la variante. Mandarlo en NULL la devuelve al precio
    # del producto; no mandarlo es "no lo toques". El endpoint distingue los
    # dos casos con `model_fields_set`.
    precio_usd: Decimal | None = Field(default=None, gt=0)


class VarianteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    producto_id: int
    sufijo: str | None
    descripcion_sufijo: str | None
    es_base: bool
    codigo_completo: str
    verificador: str
    stock_actual: int
    stock_minimo: int
    ubicacion_deposito: str | None
    activo: bool
    # Precio propio; NULL = usa el del producto.
    precio_usd: Decimal | None
    precio_venta: Decimal | None
    # Cuál de los dos precios manda lo resuelve el backend: es una regla de
    # negocio, no formato de pantalla (Principio 1).
    precio_usd_efectivo: Decimal
    precio_venta_efectivo: Decimal
    tiene_precio_propio: bool


class FotoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    # Ruta relativa: el frontend la usa tal cual como src.
    url: str
    es_principal: bool
    orden: int


class CategoriaResumen(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    nivel: int


class ProveedorResumen(BaseModel):
    """
    Datos mínimos del proveedor. No expone `dolar_actual` ni datos de
    contacto: en el listado de productos solo hace falta identificarlo.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str


class ProductoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    sku_proveedor: str | None
    descripcion: str
    categoria_id: int
    categoria: CategoriaResumen
    proveedor_id: int
    proveedor: ProveedorResumen
    # Ambos crudos: el formato de moneda lo pone el frontend (Principio 1).
    precio_usd: Decimal
    precio_venta: Decimal
    descuento_producto: Decimal
    peso_gramos: Decimal | None
    temporada: str
    stock_infinito: bool
    tiene_variantes: bool
    activo: bool
    variantes: list[VarianteResponse]
    fotos: list[FotoResponse]
    created_at: datetime
    updated_at: datetime


class ProductoSimilar(BaseModel):
    """
    Lo mínimo para reconocer un producto ya cargado desde el formulario de
    alta, mientras se tipea la descripción.

    Ni `ProductoResponse` ni `ProductoResumen`: el primero arrastra
    variantes y fotos y el segundo la categoría, el proveedor y los
    precios. Nada de eso se muestra en el desplegable —la lista ya viene
    acotada a la categoría y el proveedor elegidos— y se pagaría en cada
    tecleo.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    descripcion: str
    # Un producto inactivo sigue siendo un duplicado. La pantalla lo marca
    # para que se entienda por qué aparece.
    activo: bool


class ProductoResumen(BaseModel):
    """
    Datos del producto que necesita una fila del listado de variantes.

    No es `ProductoResponse` recortado: ese trae `variantes` y `fotos`, que
    acá sobran —la fila YA es una variante— y harían que cada fila cargara
    todas sus hermanas.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    descripcion: str
    categoria: CategoriaResumen
    proveedor: ProveedorResumen
    # Crudos: el formato lo pone el frontend (Principio 1).
    precio_usd: Decimal
    precio_venta: Decimal
    temporada: str
    stock_infinito: bool
    activo: bool


class VarianteListadoResponse(BaseModel):
    """
    Una fila del listado de /productos, que es una VARIANTE: lo que tiene
    stock, código de barras y etiqueta propia.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    producto_id: int
    sufijo: str | None
    descripcion_sufijo: str | None
    es_base: bool
    codigo_completo: str
    verificador: str
    stock_actual: int
    stock_minimo: int
    ubicacion_deposito: str | None
    activo: bool
    # Precio propio; NULL = usa el del producto.
    precio_usd: Decimal | None
    precio_venta: Decimal | None
    # Cuál de los dos precios manda lo resuelve el backend: es una regla de
    # negocio, no formato de pantalla (Principio 1).
    precio_usd_efectivo: Decimal
    precio_venta_efectivo: Decimal
    tiene_precio_propio: bool
    producto: ProductoResumen
