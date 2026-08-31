"""
Configuración del módulo de ventas: medios de pago, planes de cuotas,
motivos de descuento y promociones.

Los cuatro catálogos viven juntos porque se administran desde la misma
pantalla y piden el mismo permiso (`CONFIGURACION`), pero sobre todo porque
comparten una regla: **nada se borra, todo se desactiva**. Las ventas ya
cobradas apuntan a un medio, a un plan, a un motivo y a una promoción, y
borrar cualquiera de ellos dejaría pagos y descuentos sin decir de dónde
salieron.

Quién los ve y quién los edita lo decide el sistema de permisos, no este
archivo. Los medios de pago y los motivos de descuento piden el permiso
general de CONFIGURACION —son de la Cuenta Maestra—; las promociones piden
el recurso `configuracion.promociones`, que el Supervisor también tiene.

Ese recurso existe justamente por eso: darle a Supervisor el permiso general
de configuración le abriría además los medios de pago, que no le
corresponden. Y quien tiene el permiso general igual llega a las
promociones, porque `resolver_permiso` deja que el módulo habilite a sus
recursos.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permisos import Modulo, Recurso, requiere_permiso
from app.core.utils import ip_de_request
from app.models.categoria import Categoria
from app.models.producto import Producto
from app.models.promocion import Promocion, TipoAlcance, TipoPromocion
from app.models.turno import PlataformaGiftCard
from app.schemas.medios_pago import (
    EstadoCambio,
    MedioDePagoCrear,
    MedioDePagoEditar,
    MedioDePagoResponse,
    PlanCuotasCrear,
    PlanCuotasEditar,
    PlanCuotasResponse,
)
from app.schemas.promociones import (
    AlcanceResponse,
    PromocionCrear,
    PromocionEditar,
    PromocionEstado,
    PromocionResponse,
)
from app.schemas.turnos import PlataformaGiftCardRequest, PlataformaGiftCardResponse
from app.schemas.ventas import (
    MotivoDescuentoCrear,
    MotivoDescuentoEditar,
    MotivoDescuentoResponse,
)
from app.services import descuentos as servicio_descuentos
from app.services import medios_pago as servicio_medios
from app.services import promociones as servicio_promociones
from app.core.utils import ahora_db
from app.services.roles import NoEncontrado, ReglaDeNegocio

router = APIRouter(prefix="/configuracion", tags=["configuracion-ventas"])

_TIPOS_PROMO = "|".join(t.value for t in TipoPromocion)


def _404(exc):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _409(exc):
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ============================================================================
# MEDIOS DE PAGO
# ============================================================================


@router.get(
    "/medios-de-pago",
    response_model=list[MedioDePagoResponse],
    summary="Catálogo de medios de pago",
)
def listar_medios(
    nombre: str | None = Query(default=None),
    activo: bool | None = Query(default=None),
    soporta_cuotas: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.CONFIGURACION, "ver")),
):
    """Filtros del Principio 5. Tabla chica: sin paginación."""
    return servicio_medios.listar_medios(
        db, nombre=nombre, activo=activo, soporta_cuotas=soporta_cuotas
    )


@router.post(
    "/medios-de-pago",
    response_model=MedioDePagoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Alta de medio de pago",
)
def crear_medio(
    datos: MedioDePagoCrear,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CONFIGURACION, "editar")),
):
    try:
        medio = servicio_medios.crear_medio(
            db, autor, ip_origen=ip_de_request(request), **datos.model_dump()
        )
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return medio


@router.put(
    "/medios-de-pago/{medio_id}",
    response_model=MedioDePagoResponse,
    summary="Editar un medio de pago",
)
def editar_medio(
    medio_id: int,
    datos: MedioDePagoEditar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CONFIGURACION, "editar")),
):
    try:
        medio = servicio_medios.editar_medio(
            db, autor, medio_id, ip_origen=ip_de_request(request), **datos.model_dump()
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return medio


@router.patch(
    "/medios-de-pago/{medio_id}/estado",
    response_model=MedioDePagoResponse,
    summary="Activar o desactivar un medio de pago",
)
def estado_medio(
    medio_id: int,
    datos: EstadoCambio,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CONFIGURACION, "editar")),
):
    """No hay borrado: los pagos ya registrados apuntan al medio."""
    try:
        medio = servicio_medios.cambiar_estado_medio(
            db, autor, medio_id, datos.activo, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc

    db.commit()
    return medio


# ============================================================================
# PLANES DE CUOTAS
# ============================================================================


@router.get(
    "/medios-de-pago/{medio_id}/planes",
    response_model=list[PlanCuotasResponse],
    summary="Planes de cuotas de un medio",
)
def listar_planes(
    medio_id: int,
    activo: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.CONFIGURACION, "ver")),
):
    try:
        return servicio_medios.listar_planes(db, medio_id, activo=activo)
    except NoEncontrado as exc:
        raise _404(exc) from exc


@router.post(
    "/medios-de-pago/{medio_id}/planes",
    response_model=PlanCuotasResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar un plan de cuotas",
)
def crear_plan(
    medio_id: int,
    datos: PlanCuotasCrear,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CONFIGURACION, "editar")),
):
    """
    `recargo_cliente` es lo que paga de más el cliente; `costo_medio` es lo
    que cobra la terminal y NO afecta el precio. Nunca se combinan.
    """
    try:
        plan = servicio_medios.crear_plan(
            db, autor, medio_id, ip_origen=ip_de_request(request), **datos.model_dump()
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return plan


@router.put(
    "/planes-cuotas/{plan_id}",
    response_model=PlanCuotasResponse,
    summary="Editar un plan de cuotas",
)
def editar_plan(
    plan_id: int,
    datos: PlanCuotasEditar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CONFIGURACION, "editar")),
):
    """
    Las ventas ya cobradas no se tocan: `venta_pagos` guardó el recargo en
    pesos, no el porcentaje.
    """
    try:
        plan = servicio_medios.editar_plan(
            db, autor, plan_id, ip_origen=ip_de_request(request), **datos.model_dump()
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return plan


@router.patch(
    "/planes-cuotas/{plan_id}/estado",
    response_model=PlanCuotasResponse,
    summary="Activar o desactivar un plan",
)
def estado_plan(
    plan_id: int,
    datos: EstadoCambio,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CONFIGURACION, "editar")),
):
    try:
        plan = servicio_medios.cambiar_estado_plan(
            db, autor, plan_id, datos.activo, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc

    db.commit()
    return plan


# ============================================================================
# MOTIVOS DE DESCUENTO
# ============================================================================


@router.get(
    "/motivos-descuento",
    response_model=list[MotivoDescuentoResponse],
    summary="Catálogo de motivos de descuento",
)
def listar_motivos(
    nombre: str | None = Query(default=None),
    activo: bool | None = Query(default=None),
    habilita_cuotas_sin_interes: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.CONFIGURACION, "ver")),
):
    return servicio_descuentos.listar_motivos(
        db,
        nombre=nombre,
        activo=activo,
        habilita_cuotas_sin_interes=habilita_cuotas_sin_interes,
    )


@router.post(
    "/motivos-descuento",
    response_model=MotivoDescuentoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Alta de motivo de descuento",
)
def crear_motivo(
    datos: MotivoDescuentoCrear,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CONFIGURACION, "editar")),
):
    """
    El `porcentaje_sugerido` pasa por la MISMA lista de 5 en 5 que la
    vendedora: un motivo cargado con 12% sería un porcentaje libre entrando
    por la puerta de atrás, preseleccionado y sin que nadie lo eligiera.
    """
    try:
        motivo = servicio_descuentos.crear_motivo(
            db, autor, ip_origen=ip_de_request(request), **datos.model_dump()
        )
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return motivo


@router.put(
    "/motivos-descuento/{motivo_id}",
    response_model=MotivoDescuentoResponse,
    summary="Editar un motivo de descuento",
)
def editar_motivo(
    motivo_id: int,
    datos: MotivoDescuentoEditar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CONFIGURACION, "editar")),
):
    """
    `model_fields_set` distingue "no mandes el sugerido" de "sacale el
    sugerido": los dos llegan como None y significan cosas distintas.
    """
    try:
        motivo = servicio_descuentos.editar_motivo(
            db,
            autor,
            motivo_id,
            editar_sugerido="porcentaje_sugerido" in datos.model_fields_set,
            ip_origen=ip_de_request(request),
            **datos.model_dump(),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return motivo


@router.patch(
    "/motivos-descuento/{motivo_id}/estado",
    response_model=MotivoDescuentoResponse,
    summary="Activar o desactivar un motivo",
)
def estado_motivo(
    motivo_id: int,
    datos: EstadoCambio,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CONFIGURACION, "editar")),
):
    """No hay borrado: los ítems con descuento apuntan al motivo."""
    try:
        motivo = servicio_descuentos.cambiar_estado_motivo(
            db, autor, motivo_id, datos.activo, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc

    db.commit()
    return motivo


# ============================================================================
# PROMOCIONES
# ============================================================================


def _promocion_response(db: Session, promocion: Promocion) -> PromocionResponse:
    """
    La promoción con lo que el frontend no debería recalcular: si rige hoy,
    el tamaño de grupo y el nombre de cada alcance.

    Los nombres se resuelven acá y no con un endpoint por id: la pantalla de
    edición muestra una lista de productos y categorías, y pedir cada nombre
    por separado serían veinte llamadas para dibujar un formulario.
    """
    respuesta = PromocionResponse.model_validate(promocion)
    respuesta.vigente = promocion.vigente_el(ahora_db().date())
    respuesta.tamano_grupo = promocion.tamano_grupo
    respuesta.pagas_por_grupo = promocion.pagas_por_grupo
    respuesta.exclusiva_de_clientes = servicio_promociones.es_exclusiva_de_clientes(
        db, promocion
    )

    alcances = []
    for alcance in promocion.alcances:
        fila = AlcanceResponse.model_validate(alcance)
        if alcance.tipo_alcance == TipoAlcance.PRODUCTO:
            producto = db.get(Producto, alcance.referencia_id)
            fila.nombre = producto.descripcion if producto else None
        else:
            categoria = db.get(Categoria, alcance.referencia_id)
            fila.nombre = categoria.nombre if categoria else None
        alcances.append(fila)
    respuesta.alcances = alcances

    return respuesta


@router.get(
    "/promociones", response_model=list[PromocionResponse], summary="Catálogo de promociones"
)
def listar_promociones(
    nombre: str | None = Query(default=None),
    tipo: str | None = Query(default=None, pattern=f"^({_TIPOS_PROMO})$"),
    activo: bool | None = Query(default=None),
    vigente: bool | None = Query(
        default=None, description="Si rige HOY. Distinto de 'activo': puede estar vencida"
    ),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.CONFIGURACION, "ver", Recurso.PROMOCIONES)),
):
    filas = servicio_promociones.listar_promociones(
        db,
        nombre=nombre,
        tipo=TipoPromocion(tipo) if tipo else None,
        activo=activo,
        vigente=vigente,
    )
    return [_promocion_response(db, p) for p in filas]


@router.post(
    "/promociones",
    response_model=PromocionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Alta de promoción",
)
def crear_promocion(
    datos: PromocionCrear,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(
        requiere_permiso(Modulo.CONFIGURACION, "editar", Recurso.PROMOCIONES)
    ),
):
    """
    Una categoría en el alcance arrastra a toda su descendencia: quien pone
    "Plata" espera que entren "Plata > Anillos" y "Plata > Cadenas".
    """
    try:
        promocion = servicio_promociones.crear_promocion(
            db,
            autor,
            nombre=datos.nombre,
            tipo=datos.tipo,
            alcances=[a.model_dump() for a in datos.alcances],
            fecha_inicio=datos.fecha_inicio,
            fecha_fin=datos.fecha_fin,
            ip_origen=ip_de_request(request),
        )
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return _promocion_response(db, promocion)


@router.put(
    "/promociones/{promocion_id}",
    response_model=PromocionResponse,
    summary="Editar una promoción",
)
def editar_promocion(
    promocion_id: int,
    datos: PromocionEditar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(
        requiere_permiso(Modulo.CONFIGURACION, "editar", Recurso.PROMOCIONES)
    ),
):
    """
    Las ventas ya confirmadas no se tocan: guardaron su `promocion_id` y sus
    precios, así que cambiar la promo hoy no reescribe lo que se cobró ayer.
    """
    try:
        promocion = servicio_promociones.editar_promocion(
            db,
            autor,
            promocion_id,
            nombre=datos.nombre,
            tipo=datos.tipo,
            alcances=(
                [a.model_dump() for a in datos.alcances]
                if datos.alcances is not None
                else None
            ),
            fecha_inicio=datos.fecha_inicio,
            fecha_fin=datos.fecha_fin,
            # Las dos fechas se mandan juntas o no se mandan: son un rango,
            # y editar una sola dejaría una vigencia a medias.
            editar_fechas=bool(
                {"fecha_inicio", "fecha_fin"} & datos.model_fields_set
            ),
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return _promocion_response(db, promocion)


@router.patch(
    "/promociones/{promocion_id}/estado",
    response_model=PromocionResponse,
    summary="Activar o desactivar una promoción",
)
def estado_promocion(
    promocion_id: int,
    datos: PromocionEstado,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(
        requiere_permiso(Modulo.CONFIGURACION, "editar", Recurso.PROMOCIONES)
    ),
):
    """No hay borrado: las ventas confirmadas apuntan a la promoción."""
    try:
        promocion = servicio_promociones.cambiar_estado(
            db, autor, promocion_id, datos.activo, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc

    db.commit()
    return _promocion_response(db, promocion)


# ============================================================================
# PLATAFORMAS GIFT CARD VIRTUAL
# ============================================================================

pgc_router = APIRouter(prefix="/configuracion/plataformas-gift-card", tags=["configuracion"])


@pgc_router.get("", response_model=list[PlataformaGiftCardResponse])
def listar_plataformas(
    _=Depends(requiere_permiso(Modulo.CONFIGURACION, "ver")),
    db: Session = Depends(get_db),
):
    """Catálogo de plataformas de gift cards virtuales (ej: Naranja X, Mercado Pago)."""
    filas = db.execute(
        select(PlataformaGiftCard).order_by(PlataformaGiftCard.nombre)
    ).scalars().all()
    return [PlataformaGiftCardResponse(id=p.id, nombre=p.nombre, activo=p.activo) for p in filas]


@pgc_router.post("", response_model=PlataformaGiftCardResponse, status_code=201)
def crear_plataforma(
    body: PlataformaGiftCardRequest,
    _=Depends(requiere_permiso(Modulo.CONFIGURACION, "crear")),
    db: Session = Depends(get_db),
):
    """Alta de plataforma de gift card virtual."""
    ahora = ahora_db()
    p = PlataformaGiftCard(nombre=body.nombre, created_at=ahora, updated_at=ahora)
    db.add(p)
    db.commit()
    db.refresh(p)
    return PlataformaGiftCardResponse(id=p.id, nombre=p.nombre, activo=p.activo)


@pgc_router.put("/{pid}", response_model=PlataformaGiftCardResponse)
def editar_plataforma(
    pid: int,
    body: PlataformaGiftCardRequest,
    _=Depends(requiere_permiso(Modulo.CONFIGURACION, "editar")),
    db: Session = Depends(get_db),
):
    """Editar nombre de una plataforma de gift card virtual."""
    p = db.get(PlataformaGiftCard, pid)
    if not p:
        raise HTTPException(status_code=404, detail="Plataforma no encontrada")
    p.nombre = body.nombre
    p.updated_at = ahora_db()
    db.commit()
    db.refresh(p)
    return PlataformaGiftCardResponse(id=p.id, nombre=p.nombre, activo=p.activo)


@pgc_router.patch("/{pid}/estado", response_model=PlataformaGiftCardResponse)
def cambiar_estado_plataforma(
    pid: int,
    _=Depends(requiere_permiso(Modulo.CONFIGURACION, "editar")),
    db: Session = Depends(get_db),
):
    """Activa o desactiva una plataforma. No hay borrado: las ventas ya registradas apuntan a ella."""
    p = db.get(PlataformaGiftCard, pid)
    if not p:
        raise HTTPException(status_code=404, detail="Plataforma no encontrada")
    p.activo = not p.activo
    p.updated_at = ahora_db()
    db.commit()
    db.refresh(p)
    return PlataformaGiftCardResponse(id=p.id, nombre=p.nombre, activo=p.activo)
