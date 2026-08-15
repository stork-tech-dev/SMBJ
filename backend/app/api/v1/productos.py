"""Endpoints de productos y variantes."""

from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permisos import Modulo, requiere_permiso
from app.core.utils import ip_de_request
from app.models.proveedor import Proveedor
from app.schemas.comunes import RespuestaPaginada
from app.schemas.productos import (
    FotoResponse,
    PrecioPreview,
    ProductoCrear,
    ProductoEditar,
    ProductoEstado,
    ProductoResponse,
    ProductoSimilar,
    VarianteCrear,
    VarianteEditar,
    VarianteListadoResponse,
    VarianteResponse,
)
from app.services import producto_fotos as servicio_fotos
from app.services import productos as servicio
from app.services.roles import NoEncontrado, ReglaDeNegocio

router = APIRouter(prefix="/productos", tags=["productos"])


def _404(exc):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _403(exc):
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


def _409(exc):
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("", response_model=RespuestaPaginada[ProductoResponse], summary="Listado")
def listar(
    sku: str | None = Query(default=None),
    descripcion: str | None = Query(default=None),
    categoria_id: int | None = Query(default=None),
    proveedor_id: int | None = Query(default=None),
    temporada: str | None = Query(default=None),
    activo: bool | None = Query(default=None),
    precio_desde: Decimal | None = Query(default=None),
    precio_hasta: Decimal | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.PRODUCTOS, "ver")),
):
    """Filtros del Principio 5, todos resueltos en el backend."""
    filas, total = servicio.listar_productos(
        db,
        sku=sku,
        descripcion=descripcion,
        categoria_id=categoria_id,
        proveedor_id=proveedor_id,
        temporada=temporada,
        activo=activo,
        precio_desde=precio_desde,
        precio_hasta=precio_hasta,
        pagina=pagina,
        tamano=tamano,
    )
    return RespuestaPaginada[ProductoResponse](
        total=total, pagina=pagina, tamano=tamano, resultados=filas
    )


@router.get(
    "/precio-preview",
    response_model=PrecioPreview,
    summary="Precio en pesos que resultaría, sin guardar nada",
)
def precio_preview(
    proveedor_id: int = Query(..., description="Proveedor del que sale la cotización"),
    precio_usd: Decimal = Query(..., gt=0),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.PRODUCTOS, "ver")),
):
    """
    Alimenta los valores informativos del formulario de alta/edición.

    Existe para que el cálculo viva en UN solo lugar: el múltiplo de
    redondeo está en `configuracion_sistema` y la fórmula usa CEIL. Si el
    frontend lo replicara, la vista previa dejaría de coincidir con lo que
    el backend guarda apenas cambie la configuración (Principio 2).

    Va declarado ANTES de `/{producto_id}`: si no, FastAPI intentaría leer
    "precio-preview" como un id.
    """
    proveedor = db.get(Proveedor, proveedor_id)
    if proveedor is None:
        raise _404(NoEncontrado("Proveedor inexistente"))

    return PrecioPreview(
        dolar_proveedor=proveedor.dolar_actual,
        precio_venta=servicio.calcular_precio_venta(db, precio_usd, proveedor.dolar_actual),
    )


@router.get(
    "/similares",
    response_model=list[ProductoSimilar],
    summary="Productos ya cargados con descripción parecida",
)
def similares(
    descripcion: str = Query(..., description="Lo que se está tipeando en Descripción"),
    categoria_id: int | None = Query(default=None),
    proveedor_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.PRODUCTOS, "ver")),
):
    """
    Alimenta el desplegable del formulario de alta.

    Sirve para dos cosas a la vez: ver que el producto tal vez ya existe
    antes de duplicarlo —el alta lo rechaza si la descripción, la categoría
    y el proveedor coinciden— y poder adoptar el nombre con el que ya quedó
    cargado, para que el catálogo no tenga "Cadena plata 925" y "cadena de
    plata 925" como si fueran cosas distintas.

    Con menos de `MINIMO_CARACTERES_SIMILARES` devuelve una lista vacía en
    lugar de un error: el umbral es parte de la búsqueda, no una condición
    de uso, y el formulario consulta mientras se escribe.

    Va declarado ANTES de `/{producto_id}`, igual que `/precio-preview`: si
    no, FastAPI intentaría leer "similares" como un id.
    """
    return servicio.buscar_similares(
        db,
        descripcion=descripcion,
        categoria_id=categoria_id,
        proveedor_id=proveedor_id,
    )


@router.get(
    "/variantes",
    response_model=RespuestaPaginada[VarianteListadoResponse],
    summary="Listado a nivel variante (lo que tiene stock y etiqueta)",
)
def listar_variantes(
    busqueda: str | None = Query(
        default=None, description="Código de etiqueta, SKU o parte de la descripción"
    ),
    categoria_id: int | None = Query(default=None),
    proveedor_id: int | None = Query(default=None),
    temporada: str | None = Query(default=None),
    activo: bool | None = Query(default=None),
    precio_desde: Decimal | None = Query(default=None),
    precio_hasta: Decimal | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.PRODUCTOS, "ver")),
):
    """
    Una fila por variante: es lo que tiene stock y lo que dice la etiqueta.
    El listado de productos (`GET /productos`) sigue existiendo para el
    formulario y el detalle, que trabajan sobre el producto entero.

    Va declarado ANTES de `/{producto_id}`, igual que `/precio-preview`: si
    no, FastAPI intentaría leer "variantes" como un id y devolvería 422.
    """
    filas, total = servicio.listar_variantes(
        db,
        busqueda=busqueda,
        categoria_id=categoria_id,
        proveedor_id=proveedor_id,
        temporada=temporada,
        activo=activo,
        precio_desde=precio_desde,
        precio_hasta=precio_hasta,
        pagina=pagina,
        tamano=tamano,
    )
    return RespuestaPaginada[VarianteListadoResponse](
        total=total, pagina=pagina, tamano=tamano, resultados=filas
    )


@router.get("/{producto_id}", response_model=ProductoResponse, summary="Detalle")
def detalle(
    producto_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.PRODUCTOS, "ver")),
):
    try:
        return servicio.obtener_producto(db, producto_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc


@router.post(
    "", response_model=ProductoResponse, status_code=status.HTTP_201_CREATED, summary="Alta"
)
def crear(
    datos: ProductoCrear,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PRODUCTOS, "crear")),
):
    """Genera el SKU, calcula el precio de venta y crea la variante BASE."""
    try:
        producto = servicio.crear_producto(
            db,
            autor,
            categoria_id=datos.categoria_id,
            proveedor_id=datos.proveedor_id,
            precio_usd=datos.precio_usd,
            descripcion=datos.descripcion,
            sku_proveedor=datos.sku_proveedor,
            descuento_producto=datos.descuento_producto,
            peso_gramos=datos.peso_gramos,
            temporada=datos.temporada,
            stock_infinito=datos.stock_infinito,
            ip_origen=ip_de_request(request),
        )
    except servicio.SinPermiso as exc:
        raise _403(exc) from exc
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return producto


@router.put("/{producto_id}", response_model=ProductoResponse, summary="Editar")
def editar(
    producto_id: int,
    datos: ProductoEditar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PRODUCTOS, "editar")),
):
    try:
        producto = servicio.editar_producto(
            db,
            autor,
            producto_id,
            categoria_id=datos.categoria_id,
            descripcion=datos.descripcion,
            sku_proveedor=datos.sku_proveedor,
            precio_usd=datos.precio_usd,
            descuento_producto=datos.descuento_producto,
            peso_gramos=datos.peso_gramos,
            temporada=datos.temporada,
            stock_infinito=datos.stock_infinito,
            ip_origen=ip_de_request(request),
        )
    except servicio.SinPermiso as exc:
        raise _403(exc) from exc
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return producto


@router.patch(
    "/{producto_id}/estado", response_model=ProductoResponse, summary="Activar o desactivar"
)
def cambiar_estado(
    producto_id: int,
    datos: ProductoEstado,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PRODUCTOS, "editar")),
):
    try:
        producto = servicio.cambiar_estado_producto(
            db, autor, producto_id, activo=datos.activo, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc

    db.commit()
    return producto


@router.post(
    "/{producto_id}/variantes",
    response_model=VarianteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar variante",
)
def agregar_variante(
    producto_id: int,
    datos: VarianteCrear,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PRODUCTOS, "editar")),
):
    """La primera variante real reemplaza a la BASE del producto."""
    try:
        variante = servicio.agregar_variante(
            db,
            autor,
            producto_id,
            sufijo=datos.sufijo,
            descripcion_sufijo=datos.descripcion_sufijo,
            ubicacion_deposito=datos.ubicacion_deposito,
            stock_minimo=datos.stock_minimo,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return variante


@router.patch(
    "/variantes/{variante_id}",
    response_model=VarianteResponse,
    summary="Editar una variante",
)
def editar_variante(
    variante_id: int,
    datos: VarianteEditar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PRODUCTOS, "editar")),
):
    """
    Cambia el nombre de la variante, su ubicación y su stock mínimo.

    El sufijo no se toca: forma parte del código impreso en la etiqueta.
    """
    try:
        variante = servicio.editar_variante(
            db,
            autor,
            variante_id,
            descripcion_sufijo=datos.descripcion_sufijo,
            ubicacion_deposito=datos.ubicacion_deposito,
            stock_minimo=datos.stock_minimo,
            precio_usd=datos.precio_usd,
            # Distingue "no mandes el precio" de "ponelo en NULL", que acá
            # significa volver al precio del producto. Mismo patrón que usan
            # usuarios.py y admin_dispositivos.py.
            editar_precio="precio_usd" in datos.model_fields_set,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return variante


@router.get(
    "/variantes/{variante_id}/barcode",
    response_class=Response,
    summary="Code128 de la variante, en SVG",
)
def barcode(
    variante_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.PRODUCTOS, "ver")),
):
    """
    Devuelve la imagen lista para imprimir.

    El checksum módulo 103 de Code128 lo agrega la librería al codificar;
    lo que se le pasa es `codigo_completo + verificador`, así que el dígito
    módulo 11 también viaja dentro del código de barras.
    """
    try:
        svg = servicio.barcode_svg(db, variante_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc

    return Response(content=svg, media_type="image/svg+xml")


# ============================================================================
# FOTOS
# ============================================================================


@router.post(
    "/{producto_id}/fotos",
    response_model=FotoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subir una foto",
)
async def subir_foto(
    producto_id: int,
    request: Request,
    archivo: UploadFile = File(..., description="JPG, PNG, GIF o WebP, hasta 5 MB"),
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PRODUCTOS, "editar")),
):
    """
    Máximo 5 por producto. La primera queda como principal.

    El tipo se valida por los bytes del archivo, no por su extensión ni por
    el Content-Type: los dos los manda el cliente.
    """
    contenido = await archivo.read()
    try:
        foto = servicio_fotos.subir_foto(
            db, autor, producto_id, contenido, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return foto


@router.patch(
    "/fotos/{foto_id}/principal",
    response_model=FotoResponse,
    summary="Marcar como principal",
)
def marcar_principal(
    foto_id: int,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PRODUCTOS, "editar")),
):
    """Marcar una desmarca la anterior: hay una sola principal por producto."""
    try:
        foto = servicio_fotos.marcar_principal(
            db, autor, foto_id, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc

    db.commit()
    return foto


@router.delete(
    "/fotos/{foto_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Eliminar una foto"
)
def eliminar_foto(
    foto_id: int,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.PRODUCTOS, "editar")),
):
    """Si era la principal, la más antigua de las que quedan toma su lugar."""
    try:
        servicio_fotos.eliminar_foto(db, autor, foto_id, ip_origen=ip_de_request(request))
    except NoEncontrado as exc:
        raise _404(exc) from exc

    db.commit()
