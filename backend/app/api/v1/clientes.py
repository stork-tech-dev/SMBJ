"""
Endpoints de clientes y de su cuenta de puntos.

El ABM lo hacen Cuenta Maestra, Dueño y Supervisor (permiso `crear`/`editar`
sobre el módulo CLIENTES). La BÚSQUEDA, en cambio, solo pide permiso de
`ver`: la usa la vendedora desde el punto de venta para asociar un cliente a
la venta, y sin eso no podría hacerlo.
"""


from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permisos import Modulo, requiere_permiso
from app.core.utils import ip_de_request
from app.models.cliente import TipoPunto
from app.schemas.clientes import (
    ClienteCrear,
    ClienteEditar,
    ClienteEstado,
    ClienteFicha,
    ClienteResponse,
    ClienteResumen,
    PromocionDeCliente,
    PuntoMovimientoResponse,
    PuntosAjuste,
    PuntosCanje,
    SenaDeCliente,
)
from app.schemas.comunes import MensajeResponse, RespuestaPaginada
from app.schemas.promociones import ClientePromocionCrear
from app.services import clientes as servicio
from app.services import promociones as servicio_promociones
from app.services import senas as servicio_senas
from app.services.roles import NoEncontrado, ReglaDeNegocio

router = APIRouter(prefix="/clientes", tags=["clientes"])


def _404(exc):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _409(exc):
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _con_puntos(db: Session, cliente) -> ClienteResponse:
    """Una fila del listado con su saldo de puntos ya resuelto."""
    respuesta = ClienteResponse.model_validate(cliente)
    respuesta.puntos = servicio.saldo_puntos(db, cliente.id)
    return respuesta


@router.get("", response_model=RespuestaPaginada[ClienteResponse], summary="Listado")
def listar(
    busqueda: str | None = Query(default=None, description="Nombre o DNI"),
    localidad: str | None = Query(default=None),
    activo: bool | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.CLIENTES, "ver")),
):
    """Filtros del Principio 5, todos resueltos en el backend."""
    filas, total = servicio.listar_clientes(
        db,
        busqueda=busqueda,
        localidad=localidad,
        activo=activo,
        pagina=pagina,
        tamano=tamano,
    )

    # Los saldos de la página, en UNA consulta: pedirlos de a uno serían
    # cincuenta consultas por pantalla.
    saldos = servicio.saldos_puntos(db, [c.id for c in filas])
    resultados = []
    for cliente in filas:
        fila = ClienteResponse.model_validate(cliente)
        fila.puntos = saldos.get(cliente.id, 0)
        resultados.append(fila)

    return RespuestaPaginada[ClienteResponse](
        total=total, pagina=pagina, tamano=tamano, resultados=resultados
    )


@router.get("/buscar", response_model=list[ClienteResumen], summary="Búsqueda rápida")
def buscar(
    q: str = Query(min_length=1, description="Parte del nombre o del DNI"),
    limite: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.CLIENTES, "ver")),
):
    """
    El desplegable de sugerencias del punto de venta.

    Va declarado ANTES de `/{cliente_id}` para que `/buscar` no se lea como
    un id, igual que en el resto de los módulos.
    """
    return servicio.buscar(db, q, limite=limite)


@router.get("/{cliente_id}", response_model=ClienteFicha, summary="Ficha completa")
def ficha(
    cliente_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.CLIENTES, "ver")),
):
    """
    El cliente con todo lo que cuelga de él: puntos, señas con saldo y
    promociones asignadas.

    En una sola respuesta porque la pantalla los muestra juntos: pedirlos
    por separado sería dibujar la ficha cuatro veces mientras llegan.
    """
    try:
        cliente = servicio.obtener_cliente(db, cliente_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc

    respuesta = ClienteFicha.model_validate(cliente)
    respuesta.puntos = servicio.saldo_puntos(db, cliente_id)
    respuesta.saldo_senas = servicio_senas.saldo_total(db, cliente_id)
    respuesta.senas = [
        SenaDeCliente.model_validate(s)
        for s in servicio_senas.senas_disponibles(db, cliente_id)
    ]
    respuesta.promociones = [
        PromocionDeCliente.model_validate(p)
        for p in servicio_promociones.promociones_de_cliente(db, cliente_id)
    ]
    return respuesta


@router.post(
    "",
    response_model=ClienteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Alta de cliente",
)
def crear(
    datos: ClienteCrear,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CLIENTES, "crear")),
):
    try:
        cliente = servicio.crear_cliente(
            db, autor, ip_origen=ip_de_request(request), **datos.model_dump()
        )
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return _con_puntos(db, cliente)


@router.put("/{cliente_id}", response_model=ClienteResponse, summary="Editar cliente")
def editar(
    cliente_id: int,
    datos: ClienteEditar,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CLIENTES, "editar")),
):
    """
    `model_fields_set` distingue "no mandes el DNI" de "borrale el DNI": los
    dos llegan como None y significan cosas distintas.
    """
    try:
        cliente = servicio.editar_cliente(
            db,
            autor,
            cliente_id,
            editar_dni="dni" in datos.model_fields_set,
            ip_origen=ip_de_request(request),
            **datos.model_dump(),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return _con_puntos(db, cliente)


@router.patch(
    "/{cliente_id}/estado", response_model=ClienteResponse, summary="Activar o desactivar"
)
def cambiar_estado(
    cliente_id: int,
    datos: ClienteEstado,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CLIENTES, "editar")),
):
    """
    Baja lógica: no hay borrado. Las ventas, las señas y los puntos lo
    apuntan.
    """
    try:
        cliente = servicio.cambiar_estado(
            db, autor, cliente_id, datos.activo, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc

    db.commit()
    return _con_puntos(db, cliente)


@router.get(
    "/{cliente_id}/senas",
    response_model=list[SenaDeCliente],
    summary="Señas con saldo del cliente",
)
def senas_del_cliente(
    cliente_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.CLIENTES, "ver")),
):
    """
    Lo que el punto de venta ofrece como medio de pago.

    Solo las que tienen saldo: una seña gastada en la lista sería una opción
    que no cubre nada.
    """
    try:
        servicio.obtener_cliente(db, cliente_id)
    except NoEncontrado as exc:
        raise _404(exc) from exc

    return servicio_senas.senas_disponibles(db, cliente_id)


# ============================================================================
# PUNTOS
# ============================================================================


@router.get(
    "/{cliente_id}/puntos",
    response_model=list[PuntoMovimientoResponse],
    summary="Historial de puntos",
)
def puntos(
    cliente_id: int,
    limite: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.CLIENTES, "ver")),
):
    try:
        return servicio.historial_puntos(db, cliente_id, limite=limite)
    except NoEncontrado as exc:
        raise _404(exc) from exc


@router.post(
    "/{cliente_id}/puntos/ajuste",
    response_model=PuntoMovimientoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ajuste manual de puntos",
)
def ajustar_puntos(
    cliente_id: int,
    datos: PuntosAjuste,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CLIENTES, "editar")),
):
    """
    Corrige el saldo con un movimiento, no editando los anteriores:
    `puntos_cliente` es de solo inserción y la base lo hace cumplir.
    """
    try:
        movimiento = servicio.registrar_movimiento_puntos(
            db,
            autor,
            cliente_id=cliente_id,
            tipo=TipoPunto.AJUSTE,
            cantidad=datos.cantidad,
            descripcion=datos.descripcion,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return movimiento


@router.post(
    "/{cliente_id}/puntos/canje",
    response_model=PuntoMovimientoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Canje de puntos",
)
def canjear_puntos(
    cliente_id: int,
    datos: PuntosCanje,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CLIENTES, "editar")),
):
    """La cantidad va en positivo: el signo lo pone el service."""
    try:
        movimiento = servicio.registrar_movimiento_puntos(
            db,
            autor,
            cliente_id=cliente_id,
            tipo=TipoPunto.CANJE,
            cantidad=datos.cantidad,
            descripcion=datos.descripcion,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return movimiento


# ============================================================================
# PROMOCIONES ASIGNADAS
# ============================================================================


@router.post(
    "/{cliente_id}/promociones",
    response_model=list[PromocionDeCliente],
    status_code=status.HTTP_201_CREATED,
    summary="Asignar una promoción al cliente",
)
def asignar_promocion(
    cliente_id: int,
    datos: ClientePromocionCrear,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CLIENTES, "editar")),
):
    """
    Una promoción asignada a alguien deja de ser del catálogo: con al menos
    un cliente, solo se le ofrece a ellos.
    """
    try:
        servicio.obtener_cliente(db, cliente_id)
        servicio_promociones.asignar_a_cliente(
            db, autor, cliente_id, datos.promocion_id, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc

    db.commit()
    return servicio_promociones.promociones_de_cliente(db, cliente_id)


@router.delete(
    "/{cliente_id}/promociones/{promocion_id}",
    response_model=MensajeResponse,
    summary="Quitarle una promoción al cliente",
)
def quitar_promocion(
    cliente_id: int,
    promocion_id: int,
    request: Request,
    db: Session = Depends(get_db),
    autor=Depends(requiere_permiso(Modulo.CLIENTES, "editar")),
):
    try:
        servicio_promociones.quitar_de_cliente(
            db, autor, cliente_id, promocion_id, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc

    db.commit()
    return MensajeResponse(mensaje="Promoción quitada del cliente")
