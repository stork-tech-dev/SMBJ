"""
Endpoints del módulo de cambios de producto.

Flujo:
  1. POST /cambios                           → iniciar (estado: pendiente)
  2. POST /cambios/{id}/items-devueltos      → agregar ítems que devuelve el cliente
  3. POST /cambios/{id}/items-nuevos         → agregar ítems que se lleva el cliente
  4. GET  /cambios/{id}/diferencia           → calcular diferencia actual
  5. POST /cambios/{id}/confirmar            → confirmar (mueve stock, genera código)
  6. PATCH /cambios/{id}/cancelar            → cancelar sin efecto en stock

Permisos: cualquier vendedor con acceso a VENTAS puede crear y confirmar
cambios. Cancelar también.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.device_scope import DeviceScope, get_device_scope
from app.core.permisos import Modulo, requiere_permiso
from app.core.utils import ahora_db, ip_de_request
from app.models.cambio import Cambio, CambioItemDevuelto, CambioItemNuevo
from app.models.venta import Venta
from app.schemas.cambios import (
    BuscarVentaCambioRequest,
    CambioResponse,
    ConfirmarCambioRequest,
    DiferenciaResponse,
    IniciarCambioRequest,
    ItemDevueltoRequest,
    ItemDevueltoResponse,
    ItemNuevoRequest,
    ItemNuevoResponse,
    VentaParaCambioResponse,
)
from app.schemas.comunes import RespuestaPaginada
from app.services import cambios as servicio
from app.services.roles import NoEncontrado, ReglaDeNegocio

router = APIRouter(prefix="/cambios", tags=["cambios"])


def _404(exc):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _409(exc):
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ── Helpers de respuesta ────────────────────────────────────────────────────

def _desc_variante(variante) -> str:
    """Descripción legible de una variante: 'Producto · Talle/color'."""
    desc = variante.producto.descripcion
    if variante.descripcion_sufijo:
        desc = f"{desc} · {variante.descripcion_sufijo}"
    return desc


def _item_devuelto_response(item: CambioItemDevuelto) -> ItemDevueltoResponse:
    variante = item.variante
    return ItemDevueltoResponse(
        id=item.id,
        variante_id=item.variante_id,
        variante_descripcion=_desc_variante(variante),
        variante_sku=variante.codigo_completo,
        precio_reconocido=item.precio_reconocido,
        en_promocion=item.en_promocion,
        tipo_promo=item.tipo_promo.value if item.tipo_promo else None,
        material_id=item.material_id,
        material_nombre=item.material.nombre if item.material else None,
        foto_url=variante.foto_url,
    )


def _item_nuevo_response(item: CambioItemNuevo) -> ItemNuevoResponse:
    variante = item.variante
    return ItemNuevoResponse(
        id=item.id,
        variante_id=item.variante_id,
        variante_descripcion=_desc_variante(variante),
        variante_sku=variante.codigo_completo,
        precio_actual=item.precio_actual,
        material_id=item.material_id,
        material_nombre=item.material.nombre if item.material else None,
        foto_url=variante.foto_url,
    )


def _respuesta_cambio(cambio: Cambio) -> CambioResponse:
    return CambioResponse(
        id=cambio.id,
        tipo=cambio.tipo,
        estado=cambio.estado,
        venta_origen_id=cambio.venta_origen_id,
        codigo_venta_origen=(
            cambio.venta_origen.codigo_cambio if cambio.venta_origen else None
        ),
        punto_de_venta_id=cambio.punto_de_venta_id,
        punto_de_venta_nombre=cambio.punto_de_venta.nombre,
        usuario_id=cambio.usuario_id,
        usuario_nombre=cambio.usuario.nombre,
        autorizador_id=cambio.autorizador_id,
        autorizador_nombre=(
            cambio.autorizador.nombre if cambio.autorizador else None
        ),
        diferencia=cambio.diferencia,
        medio_pago_diferencia_id=cambio.medio_pago_diferencia_id,
        medio_pago_diferencia_nombre=(
            cambio.medio_pago_diferencia.nombre if cambio.medio_pago_diferencia else None
        ),
        plan_cuotas_diferencia_id=cambio.plan_cuotas_diferencia_id,
        contador_cambios_previos=cambio.contador_cambios_previos,
        codigo_cambio_nuevo=cambio.codigo_cambio_nuevo,
        notas=cambio.notas,
        items_devueltos=[_item_devuelto_response(i) for i in cambio.items_devueltos],
        items_nuevos=[_item_nuevo_response(i) for i in cambio.items_nuevos],
        created_at=cambio.created_at,
        updated_at=cambio.updated_at,
    )


def _respuesta_venta_cambio(venta: Venta) -> VentaParaCambioResponse:
    hoy = ahora_db().date()
    dias = (hoy - venta.created_at.date()).days
    total = sum(Decimal(i.precio_lista) for i in venta.items)
    items = [
        {
            "id": i.id,
            "variante_id": i.variante_id,
            "variante_descripcion": _desc_variante(i.variante),
            "variante_sku": i.variante.codigo_completo,
            "precio_lista": str(i.precio_lista),
            "precio_final": str(i.precio_final),
            "en_promocion": i.en_promocion,
        }
        for i in venta.items
    ]
    return VentaParaCambioResponse(
        id=venta.id,
        numero=venta.numero,
        fecha=venta.created_at,
        total=total,
        codigo_cambio=venta.codigo_cambio,
        dias_desde_venta=dias,
        plazo_vencido=dias > 30,
        items=items,
    )


def _obtener(db: Session, cambio_id: int) -> Cambio:
    try:
        return servicio.obtener_cambio(db, cambio_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc


# ── Búsqueda de ventas para cambio (en el router de ventas, pero acá el helper)
# El endpoint GET /ventas/buscar-para-cambio vive en ventas.py por el prefijo.
# Acá van todos los endpoints bajo /cambios.

# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=CambioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Iniciar un cambio de producto",
)
def iniciar(
    datos: IniciarCambioRequest,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.VENTAS, "crear")),
):
    """
    Crea un cambio en estado 'pendiente'. Validaciones:
    - comun/promocion/gift_card_fisica: requiere codigo_cambio válido y activo.
    - falla: requiere autorizador_id.

    El response incluye una lista `avisos` si hay alertas (plazo vencido, etc.)
    en el header `X-Avisos`.
    """
    try:
        cambio, avisos = servicio.iniciar_cambio(
            db,
            autor,
            tipo=datos.tipo,
            punto_de_venta_id=datos.punto_de_venta_id,
            codigo_cambio=datos.codigo_cambio,
            autorizador_id=datos.autorizador_id,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        db.rollback()
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        db.rollback()
        raise _409(exc) from exc

    db.commit()
    db.refresh(cambio)

    from fastapi.responses import JSONResponse
    respuesta = _respuesta_cambio(cambio)
    headers = {}
    if avisos:
        import json
        headers["X-Avisos"] = json.dumps(avisos, ensure_ascii=False)
    return respuesta


@router.post(
    "/{cambio_id}/items-devueltos",
    response_model=ItemDevueltoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar ítem devuelto por el cliente",
)
def agregar_item_devuelto(
    cambio_id: int,
    datos: ItemDevueltoRequest,
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.VENTAS, "crear")),
):
    cambio = _obtener(db, cambio_id)
    try:
        item, avisos = servicio.agregar_item_devuelto(
            db, cambio, datos.variante_id, datos.venta_item_id
        )
    except (NoEncontrado, ReglaDeNegocio) as exc:
        db.rollback()
        if isinstance(exc, NoEncontrado):
            raise _404(exc) from exc
        raise _409(exc) from exc

    db.commit()
    db.refresh(item)

    return _item_devuelto_response(item)


@router.post(
    "/{cambio_id}/items-nuevos",
    response_model=ItemNuevoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar ítem nuevo que se lleva el cliente",
)
def agregar_item_nuevo(
    cambio_id: int,
    datos: ItemNuevoRequest,
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.VENTAS, "crear")),
):
    cambio = _obtener(db, cambio_id)
    try:
        item = servicio.agregar_item_nuevo(db, cambio, datos.variante_id)
    except (NoEncontrado, ReglaDeNegocio) as exc:
        db.rollback()
        if isinstance(exc, NoEncontrado):
            raise _404(exc) from exc
        raise _409(exc) from exc

    db.commit()
    db.refresh(item)

    return _item_nuevo_response(item)


@router.get(
    "/{cambio_id}/diferencia",
    response_model=DiferenciaResponse,
    summary="Calcular diferencia actual del cambio",
)
def diferencia(
    cambio_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.VENTAS, "ver")),
):
    cambio = _obtener(db, cambio_id)
    calculo = servicio.calcular_diferencia(db, cambio)
    db.commit()  # persiste recálculo de precio_reconocido en ítems de promo
    return DiferenciaResponse(**calculo)


@router.post(
    "/{cambio_id}/confirmar",
    response_model=CambioResponse,
    summary="Confirmar el cambio",
)
def confirmar(
    cambio_id: int,
    datos: ConfirmarCambioRequest,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.VENTAS, "crear")),
):
    """
    Mueve el stock, ajusta puntos y genera el código de cambio para los
    nuevos ítems. Todo en una transacción.
    """
    cambio = _obtener(db, cambio_id)
    try:
        cambio = servicio.confirmar_cambio(
            db,
            autor,
            cambio,
            medio_pago_diferencia_id=datos.medio_pago_diferencia_id,
            plan_cuotas_diferencia_id=datos.plan_cuotas_diferencia_id,
            notas=datos.notas,
            ip_origen=ip_de_request(request),
        )
    except ReglaDeNegocio as exc:
        db.rollback()
        raise _409(exc) from exc

    db.commit()
    db.refresh(cambio)
    return _respuesta_cambio(cambio)


@router.patch(
    "/{cambio_id}/cancelar",
    response_model=CambioResponse,
    summary="Cancelar un cambio pendiente",
)
def cancelar(
    cambio_id: int,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.VENTAS, "crear")),
):
    cambio = _obtener(db, cambio_id)
    try:
        cambio = servicio.cancelar_cambio(
            db, autor, cambio, ip_origen=ip_de_request(request)
        )
    except ReglaDeNegocio as exc:
        db.rollback()
        raise _409(exc) from exc

    db.commit()
    db.refresh(cambio)
    return _respuesta_cambio(cambio)


@router.get(
    "/{cambio_id}",
    response_model=CambioResponse,
    summary="Obtener un cambio por ID",
)
def obtener(
    cambio_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.VENTAS, "ver")),
):
    return _respuesta_cambio(_obtener(db, cambio_id))


@router.get(
    "",
    response_model=RespuestaPaginada[CambioResponse],
    summary="Historial de cambios",
)
def listar(
    punto_de_venta_id: int | None = Query(default=None),
    tipo: str | None = Query(default=None),
    estado: str | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.VENTAS, "ver")),
):
    from app.models.cambio import EstadoCambio, TipoCambio

    tipo_enum = TipoCambio(tipo) if tipo else None
    estado_enum = EstadoCambio(estado) if estado else None

    filas, total = servicio.listar_cambios(
        db,
        punto_de_venta_id=punto_de_venta_id,
        tipo=tipo_enum,
        estado=estado_enum,
        pagina=pagina,
        tamano=tamano,
    )
    return RespuestaPaginada[CambioResponse](
        total=total,
        pagina=pagina,
        tamano=tamano,
        resultados=[_respuesta_cambio(c) for c in filas],
    )
