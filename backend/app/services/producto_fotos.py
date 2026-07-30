"""
Fotos de producto: subida, borrado y marcado de la principal.

Es la primera entrada de archivos subidos por el usuario en el sistema, así
que las validaciones son deliberadamente desconfiadas:

- El nombre del archivo NUNCA se usa: lo elige el cliente y puede traer
  `../` para escapar del directorio, o repetirse y pisar otra foto. Se
  genera un nombre propio.
- El tipo NO se decide por la extensión ni por el `Content-Type`: los dos
  los manda el cliente y se falsifican en un segundo. Se leen los bytes
  mágicos del archivo.
- El tamaño se corta antes de escribir nada en disco.
"""

import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_auditoria, snapshot
from app.models.producto import Producto
from app.models.producto_foto import MAX_FOTOS_POR_PRODUCTO, ProductoFoto
from app.models.usuario import Usuario
from app.services.roles import NoEncontrado, ReglaDeNegocio

# Directorio de las fotos, servido por el StaticFiles ya montado en main.py.
# Se resuelve desde este archivo y no relativo al CWD, por el mismo motivo
# que en core/templates.py: una ruta relativa que falla lo hace en silencio.
_DIRECTORIO = Path(__file__).resolve().parents[1] / "static" / "productos"
_URL_BASE = "/static/productos"

TAMANO_MAXIMO = 5 * 1024 * 1024  # 5 MB

# Firmas de archivo (bytes mágicos) de los formatos aceptados. Es la única
# forma confiable de saber qué se subió: la extensión y el Content-Type los
# controla el cliente.
_FIRMAS: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
]


def _detectar_formato(contenido: bytes) -> str:
    """
    Extensión real del archivo según sus bytes mágicos.

    WebP no entra en la tabla porque su firma está partida: 'RIFF' en los
    bytes 0-3 y 'WEBP' en los 8-11, con el tamaño en el medio.
    """
    for firma, extension in _FIRMAS:
        if contenido.startswith(firma):
            return extension

    if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "webp"

    raise ReglaDeNegocio(
        "El archivo no es una imagen válida (se aceptan JPG, PNG, GIF y WebP)"
    )


def _obtener_producto(db: Session, producto_id: int) -> Producto:
    producto = db.get(Producto, producto_id)
    if producto is None:
        raise NoEncontrado("Producto inexistente")
    return producto


def obtener_foto(db: Session, foto_id: int) -> ProductoFoto:
    foto = db.get(ProductoFoto, foto_id)
    if foto is None:
        raise NoEncontrado("Foto inexistente")
    return foto


# ============================================================================
# SUBIDA
# ============================================================================


def subir_foto(
    db: Session,
    autor: Usuario,
    producto_id: int,
    contenido: bytes,
    ip_origen: str | None = None,
) -> ProductoFoto:
    """
    Guarda una foto en disco y registra su fila.

    Valida ANTES de escribir: si algo falla, no queda un archivo huérfano
    en el directorio sin fila que lo referencie.
    """
    producto = _obtener_producto(db, producto_id)

    if not contenido:
        raise ReglaDeNegocio("El archivo está vacío")

    if len(contenido) > TAMANO_MAXIMO:
        mb = TAMANO_MAXIMO // (1024 * 1024)
        raise ReglaDeNegocio(f"La imagen supera el máximo de {mb} MB")

    extension = _detectar_formato(contenido)

    cuantas = db.execute(
        select(func.count(ProductoFoto.id)).where(ProductoFoto.producto_id == producto.id)
    ).scalar_one()
    if cuantas >= MAX_FOTOS_POR_PRODUCTO:
        raise ReglaDeNegocio(
            f"El producto ya tiene {MAX_FOTOS_POR_PRODUCTO} fotos: hay que "
            "borrar una antes de subir otra"
        )

    # Nombre propio, nunca el del cliente: evita el path traversal ('../')
    # y que dos subidas con el mismo nombre se pisen entre sí.
    nombre = f"{producto.sku}_{uuid.uuid4().hex[:12]}.{extension}"

    _DIRECTORIO.mkdir(parents=True, exist_ok=True)
    (_DIRECTORIO / nombre).write_bytes(contenido)

    foto = ProductoFoto(
        producto_id=producto.id,
        url=f"{_URL_BASE}/{nombre}",
        # La primera foto queda principal sola: un producto con fotos pero
        # sin principal no tendría qué mostrar en el listado.
        es_principal=(cuantas == 0),
        orden=cuantas,
    )
    db.add(foto)
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="producto.foto_subir",
        entidad="producto_fotos",
        entidad_id=foto.id,
        estado_nuevo=foto,
        ip_origen=ip_origen,
    )
    return foto


# ============================================================================
# PRINCIPAL Y BORRADO
# ============================================================================


def marcar_principal(
    db: Session, autor: Usuario, foto_id: int, ip_origen: str | None = None
) -> ProductoFoto:
    """
    Marca una foto como principal y desmarca la anterior.

    El desmarcado va PRIMERO y con un flush: el índice único parcial de la
    base rechazaría dos principales simultáneas del mismo producto.
    """
    foto = obtener_foto(db, foto_id)
    antes = snapshot(foto)

    anteriores = list(
        db.execute(
            select(ProductoFoto).where(
                ProductoFoto.producto_id == foto.producto_id,
                ProductoFoto.es_principal.is_(True),
                ProductoFoto.id != foto.id,
            )
        )
        .scalars()
        .all()
    )
    for otra in anteriores:
        otra.es_principal = False
    if anteriores:
        db.flush()

    foto.es_principal = True
    db.flush()

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="producto.foto_principal",
        entidad="producto_fotos",
        entidad_id=foto.id,
        estado_anterior=antes,
        estado_nuevo=foto,
        ip_origen=ip_origen,
    )
    return foto


def eliminar_foto(
    db: Session, autor: Usuario, foto_id: int, ip_origen: str | None = None
) -> None:
    """
    Borra la fila y el archivo.

    Si la borrada era la principal, la más antigua de las que quedan toma
    su lugar: el producto no puede quedar con fotos y ninguna principal.
    """
    foto = obtener_foto(db, foto_id)
    antes = snapshot(foto)
    producto_id = foto.producto_id
    era_principal = foto.es_principal

    ruta = _DIRECTORIO / Path(foto.url).name

    db.delete(foto)
    db.flush()

    if era_principal:
        siguiente = (
            db.execute(
                select(ProductoFoto)
                .where(ProductoFoto.producto_id == producto_id)
                .order_by(ProductoFoto.orden, ProductoFoto.id)
            )
            .scalars()
            .first()
        )
        if siguiente is not None:
            siguiente.es_principal = True
            db.flush()

    # El archivo se borra al final, cuando la fila ya se fue: si esto falla,
    # queda un archivo suelto en disco (inofensivo) en lugar de una fila
    # apuntando a un archivo que no existe (una imagen rota en pantalla).
    # `Path(foto.url).name` descarta cualquier directorio de la URL, así que
    # el borrado no puede salirse del directorio de fotos.
    ruta.unlink(missing_ok=True)

    registrar_auditoria(
        db,
        usuario_id=autor.id,
        accion="producto.foto_eliminar",
        entidad="producto_fotos",
        entidad_id=foto_id,
        estado_anterior=antes,
        ip_origen=ip_origen,
    )
