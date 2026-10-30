"""
Endpoints del módulo de etiquetas (`/api/v1/etiquetas`).

Imprimir pide el permiso de ver Productos (el mismo que pedía el PDF de
etiquetas); administrar impresoras y diseños es de la Cuenta Maestra, como
el resto de Ajustes.

El servidor devuelve el ZPL listo: el navegador solo se lo pasa a Zebra
Browser Print (`static/js/browserprint.js`).
"""

import json

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permisos import Modulo, requiere_cuenta_maestra, requiere_permiso
from app.core.utils import ip_de_request
from app.schemas.etiquetas import (
    AsignarImpresora,
    DisenoArchivo,
    DisenoCrear,
    DisenoEditar,
    DisenoResponse,
    DisenoVersionResponse,
    DisenoVistaPreviaRequest,
    DisenoVistaPreviaResponse,
    FormatoResponse,
    ImpresoraCrear,
    ImpresoraEditar,
    ImpresoraResponse,
    OrigenResponse,
    PrepararRequest,
    PrepararResponse,
    ZplResponse,
)
from app.services import etiquetas as servicio
from app.services.roles import NoEncontrado, ReglaDeNegocio

router = APIRouter(prefix="/etiquetas", tags=["etiquetas"])

_puede_imprimir = requiere_permiso(Modulo.PRODUCTOS, "ver")


def _404(exc):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _409(exc):
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ---------------------------------------------------------------------------
# Imprimir
# ---------------------------------------------------------------------------


@router.get("/formatos", response_model=list[FormatoResponse], summary="Rollos de etiquetas")
def formatos(db: Session = Depends(get_db), _=Depends(_puede_imprimir)):
    """Los rollos, cada uno con la impresora que lo imprime."""
    return servicio.listar_formatos(db)


@router.get("/disenos", response_model=list[DisenoResponse], summary="Diseños de etiqueta")
def disenos(
    archivados: bool = False,
    db: Session = Depends(get_db),
    _=Depends(_puede_imprimir),
):
    return servicio.listar_disenos(db, archivados)


@router.get("/origen", response_model=OrigenResponse, summary="Productos para imprimir")
def origen(
    compra_id: int | None = Query(default=None, description="Todos los productos de una compra."),
    variante_id: int | None = Query(default=None, description="Una variante."),
    copias: int = Query(default=1, ge=1, le=999, description="Copias de la variante."),
    codigo: str | None = Query(default=None, description="Código de etiqueta, con o sin dígito verificador."),
    db: Session = Depends(get_db),
    _=Depends(_puede_imprimir),
):
    """
    Los renglones para la pantalla de impresión, de UNO de tres orígenes:
    una compra (la cantidad comprada = copias), una variante o un código
    escaneado o tipeado.
    """
    if sum(x is not None for x in (compra_id, variante_id, codigo)) != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Hay que indicar una compra, una variante o un código (uno solo).",
        )
    try:
        if compra_id is not None:
            renglones = servicio.renglones_de_compra(db, compra_id)
        elif variante_id is not None:
            renglones = [servicio.renglon_de_variante(db, variante_id, copias)]
        else:
            renglones = [servicio.renglon_de_codigo(db, codigo)]
    except NoEncontrado as exc:
        raise _404(exc) from exc
    return {"renglones": renglones}


@router.post("/preparar", response_model=PrepararResponse, summary="Armar el ZPL de las etiquetas")
def preparar(datos: PrepararRequest, db: Session = Depends(get_db), _=Depends(_puede_imprimir)):
    """
    Arma todas las etiquetas, repartidas por rollo: cada grupo trae la
    impresora asignada, las órdenes ZPL (una por fila; las filas iguales en
    una sola con `^PQ`), los avisos y la vista previa. No imprime: eso lo
    hace el navegador con Browser Print.
    """
    try:
        return servicio.preparar(db, datos.diseno_id, datos.etiquetas)
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc


# ---------------------------------------------------------------------------
# Impresoras y rollos (Cuenta Maestra)
# ---------------------------------------------------------------------------


@router.get("/impresoras", response_model=list[ImpresoraResponse], summary="Impresoras")
def impresoras(db: Session = Depends(get_db), _=Depends(requiere_cuenta_maestra)):
    return servicio.listar_impresoras(db)


@router.post(
    "/impresoras", response_model=ImpresoraResponse, status_code=status.HTTP_201_CREATED,
    summary="Agregar una impresora",
)
def crear_impresora(
    datos: ImpresoraCrear, request: Request,
    db: Session = Depends(get_db), autor=Depends(requiere_cuenta_maestra),
):
    """Ficha nueva con los ajustes de siempre; después se le asigna qué rollo imprime."""
    try:
        impresora = servicio.crear_impresora(
            db, autor.id, datos.nombre, datos.browser_print, ip_origen=ip_de_request(request)
        )
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc
    db.commit()
    return impresora


@router.put("/impresoras/{impresora_id}", response_model=ImpresoraResponse, summary="Editar la ficha")
def editar_impresora(
    impresora_id: int, datos: ImpresoraEditar, request: Request,
    db: Session = Depends(get_db), autor=Depends(requiere_cuenta_maestra),
):
    """Nombre, nombre en Browser Print, corrimiento, oscuridad y velocidad: van dentro de cada ZPL."""
    try:
        impresora = servicio.editar_impresora(
            db, autor.id, impresora_id, datos.model_dump(exclude_unset=True), ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc
    db.commit()
    return impresora


@router.delete(
    "/impresoras/{impresora_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Quitar una impresora"
)
def quitar_impresora(
    impresora_id: int, request: Request,
    db: Session = Depends(get_db), autor=Depends(requiere_cuenta_maestra),
):
    """Solo si no imprime ningún rollo: así ningún rollo queda sin impresora sin que nadie lo decida."""
    try:
        servicio.quitar_impresora(db, autor.id, impresora_id, ip_origen=ip_de_request(request))
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/formatos/{formato_id}/impresora", response_model=FormatoResponse,
    summary="Asignar la impresora de un rollo",
)
def asignar_impresora(
    formato_id: int, datos: AsignarImpresora, request: Request,
    db: Session = Depends(get_db), autor=Depends(requiere_cuenta_maestra),
):
    try:
        formato = servicio.asignar_impresora(
            db, autor.id, formato_id, datos.impresora_id, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    db.commit()
    return formato


@router.post("/impresoras/{impresora_id}/prueba", response_model=ZplResponse, summary="Etiqueta de prueba")
def prueba(impresora_id: int, db: Session = Depends(get_db), _=Depends(requiere_cuenta_maestra)):
    """ZPL de una fila de prueba del rollo de esa impresora, con los ajustes de su ficha."""
    try:
        zpl, svg = servicio.zpl_prueba(db, impresora_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc
    return {"zpl": zpl, "vista_previa": svg}


@router.post("/impresoras/{impresora_id}/calibrar", response_model=ZplResponse, summary="Calibrar el rollo")
def calibrar(impresora_id: int, db: Session = Depends(get_db), _=Depends(requiere_cuenta_maestra)):
    """La orden para que la Zebra mida el rollo: cuando se cambia el rollo o la cinta."""
    try:
        return {"zpl": servicio.zpl_calibracion(db, impresora_id)}
    except NoEncontrado as exc:
        raise _404(exc) from exc


# ---------------------------------------------------------------------------
# Diseños (Cuenta Maestra)
# ---------------------------------------------------------------------------


@router.post(
    "/disenos", response_model=DisenoResponse, status_code=status.HTTP_201_CREATED, summary="Crear un diseño"
)
def crear_diseno(
    datos: DisenoCrear, request: Request,
    db: Session = Depends(get_db), autor=Depends(requiere_cuenta_maestra),
):
    diseno = servicio.crear_diseno(db, autor.id, datos.nombre, datos.parametros, ip_origen=ip_de_request(request))
    db.commit()
    return diseno


@router.post(
    "/disenos/vista-previa", response_model=DisenoVistaPreviaResponse, summary="Vista previa sin guardar"
)
def vista_previa(
    datos: DisenoVistaPreviaRequest, db: Session = Depends(get_db), _=Depends(requiere_cuenta_maestra)
):
    """Las tres opciones en cada rollo con estos parámetros, su ZPL y avisos. No guarda nada."""
    try:
        return {"rollos": servicio.vista_previa_diseno(db, datos.parametros)}
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc


@router.post(
    "/disenos/importar", response_model=DisenoResponse, status_code=status.HTTP_201_CREATED,
    summary="Subir un diseño desde un archivo",
)
async def importar_diseno(
    request: Request,
    archivo: UploadFile = File(description="JSON con `nombre` y `parametros`, como el que se baja."),
    db: Session = Depends(get_db),
    autor=Depends(requiere_cuenta_maestra),
):
    """Crea un diseño nuevo desde un archivo bajado (y quizás editado afuera). Se valida campo por campo."""
    try:
        contenido = DisenoArchivo.model_validate(json.loads(await archivo.read()))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=422, detail="El archivo no es un JSON válido.") from exc
    except ValidationError as exc:
        errores = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise HTTPException(status_code=422, detail=f"El archivo tiene errores: {errores}") from exc
    diseno = servicio.crear_diseno(
        db, autor.id, contenido.nombre, contenido.parametros,
        ip_origen=ip_de_request(request), accion="etiqueta_diseno.importar",
    )
    db.commit()
    return diseno


@router.put("/disenos/{diseno_id}", response_model=DisenoResponse, summary="Editar un diseño")
def editar_diseno(
    diseno_id: int, datos: DisenoEditar, request: Request,
    db: Session = Depends(get_db), autor=Depends(requiere_cuenta_maestra),
):
    """Cada cambio guarda una versión nueva; la anterior queda con quién y cuándo."""
    try:
        diseno = servicio.editar_diseno(
            db, autor.id, diseno_id, datos.nombre, datos.parametros, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    db.commit()
    return diseno


@router.post("/disenos/{diseno_id}/duplicar", response_model=DisenoResponse, status_code=status.HTTP_201_CREATED)
def duplicar_diseno(
    diseno_id: int, request: Request,
    db: Session = Depends(get_db), autor=Depends(requiere_cuenta_maestra),
):
    try:
        diseno = servicio.duplicar_diseno(db, autor.id, diseno_id, ip_origen=ip_de_request(request))
    except NoEncontrado as exc:
        raise _404(exc) from exc
    db.commit()
    return diseno


def _archivado(diseno_id: int, archivado: bool, request: Request, db: Session, autor):
    try:
        diseno = servicio.cambiar_archivado(db, autor.id, diseno_id, archivado, ip_origen=ip_de_request(request))
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc
    db.commit()
    return diseno


@router.post("/disenos/{diseno_id}/archivar", response_model=DisenoResponse, summary="Archivar un diseño")
def archivar_diseno(
    diseno_id: int, request: Request,
    db: Session = Depends(get_db), autor=Depends(requiere_cuenta_maestra),
):
    """Borrar = archivar: deja de ofrecerse al imprimir, pero no se pierde."""
    return _archivado(diseno_id, True, request, db, autor)


@router.post("/disenos/{diseno_id}/desarchivar", response_model=DisenoResponse, summary="Desarchivar un diseño")
def desarchivar_diseno(
    diseno_id: int, request: Request,
    db: Session = Depends(get_db), autor=Depends(requiere_cuenta_maestra),
):
    return _archivado(diseno_id, False, request, db, autor)


@router.get(
    "/disenos/{diseno_id}/versiones", response_model=list[DisenoVersionResponse], summary="Versiones de un diseño"
)
def versiones(diseno_id: int, db: Session = Depends(get_db), _=Depends(requiere_cuenta_maestra)):
    try:
        filas = servicio.versiones_diseno(db, diseno_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc
    return [
        {
            "version": v.version, "nombre": v.nombre, "parametros": v.parametros,
            "usuario": v.usuario.nombre if v.usuario else None, "creado_en": v.creado_en,
        }
        for v in filas
    ]


@router.post(
    "/disenos/{diseno_id}/versiones/{version}/restaurar", response_model=DisenoResponse,
    summary="Volver a una versión",
)
def restaurar(
    diseno_id: int, version: int, request: Request,
    db: Session = Depends(get_db), autor=Depends(requiere_cuenta_maestra),
):
    """Es una edición nueva con los parámetros de esa versión: no se borra historia."""
    try:
        diseno = servicio.restaurar_version(db, autor.id, diseno_id, version, ip_origen=ip_de_request(request))
    except NoEncontrado as exc:
        raise _404(exc) from exc
    db.commit()
    return diseno


@router.get("/disenos/{diseno_id}/archivo", summary="Bajar un diseño como archivo")
def bajar_diseno(diseno_id: int, db: Session = Depends(get_db), _=Depends(requiere_cuenta_maestra)):
    """JSON con `nombre` y `parametros`: se edita afuera y se vuelve a subir con `/disenos/importar`."""
    try:
        contenido = servicio.exportar_diseno(db, diseno_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc
    return Response(
        content=json.dumps(contenido, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="diseno-etiqueta-{diseno_id}.json"'},
    )
