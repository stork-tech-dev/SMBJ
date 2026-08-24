"""
Endpoints del flujo de venta.

Todos llevan `get_device_scope`: una vendedora solo ve y opera las ventas de
su local. Va como dependency y no como lógica dentro de cada handler porque
un endpoint que se olvide del filtro no falla — simplemente deja ver todo, y
eso no se nota hasta que ya pasó.

Cada endpoint que modifica hace UN commit al final. Los services no
commitean: así el stock, los puntos, la seña y la auditoría de una
confirmación se guardan o se descartan juntos.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.device_deps import get_active_device
from app.core.device_scope import DeviceScope, get_device_scope
from app.core.permisos import Modulo, Recurso, requiere_permiso
from app.core.utils import ip_de_request
from app.models.venta import EstadoVenta, Venta
from app.schemas.comunes import MensajeResponse, RespuestaPaginada
from app.schemas.medios_pago import MedioDisponible, PlanCuotasResponse
from app.schemas.ventas import (
    ClienteAsociar,
    DescuentoAplicar,
    ItemAgregadoResponse,
    ItemAgregar,
    MotivoDescuentoResponse,
    OpcionesDescuento,
    PagosRegistrar,
    ProductoEscaneado,
    PromocionAplicar,
    VentaAnular,
    VentaEnCursoResponse,
    VentaResponse,
    VentaResumen,
)
from app.schemas.promociones import PromocionResumen
from app.services import descuentos as servicio_descuentos
from app.services import medios_pago as servicio_medios
from app.services import promociones as servicio_promociones
from app.services import ventas as servicio
from app.services.roles import NoEncontrado, ReglaDeNegocio

router = APIRouter(prefix="/ventas", tags=["ventas"])

_ESTADOS = "|".join(e.value for e in EstadoVenta)


def _404(exc):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _409(exc):
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _respuesta(venta: Venta) -> VentaResponse:
    """
    La venta como la ve el frontend, con `a_cobrar` ya calculado.

    Es la suma de los `precio_final` sin recargos: el número contra el que se
    validan los pagos. Va resuelto en el backend para que la pantalla no
    tenga que sumar la lista de ítems y arriesgarse a dar otro resultado
    (Principio 1).
    """
    respuesta = VentaResponse.model_validate(venta)
    respuesta.a_cobrar = sum(
        (Decimal(i.precio_final) for i in venta.items), Decimal("0")
    )
    return respuesta


def _venta(db: Session, venta_id: int, scope: DeviceScope) -> Venta:
    try:
        return servicio.obtener_venta(db, venta_id, scope)
    except NoEncontrado as exc:
        raise _404(exc) from exc


# ============================================================================
# CONSULTA
# ============================================================================


@router.get("", response_model=RespuestaPaginada[VentaResumen], summary="Listado")
def listar(
    punto_de_venta_id: int | None = Query(default=None),
    cliente_id: int | None = Query(default=None),
    usuario_id: int | None = Query(default=None),
    estado: str | None = Query(default=None, pattern=f"^({_ESTADOS})$"),
    numero: str | None = Query(default=None),
    total_desde: Decimal | None = Query(default=None),
    total_hasta: Decimal | None = Query(default=None),
    fecha_desde: date | None = Query(default=None),
    fecha_hasta: date | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    tamano: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.VENTAS, "ver")),
):
    """
    Filtros del Principio 5, todos resueltos en el backend.

    Un vendedor sin local asignado recibe la lista vacía y no un 403: tiene
    que poder abrir la pantalla y leer por qué no hay nada.
    """
    filas, total = servicio.listar_ventas(
        db,
        scope,
        punto_de_venta_id=punto_de_venta_id,
        cliente_id=cliente_id,
        usuario_id=usuario_id,
        estado=EstadoVenta(estado) if estado else None,
        numero=numero,
        total_desde=total_desde,
        total_hasta=total_hasta,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        pagina=pagina,
        tamano=tamano,
    )
    return RespuestaPaginada[VentaResumen](
        total=total, pagina=pagina, tamano=tamano, resultados=filas
    )


@router.get(
    "/en-curso",
    response_model=VentaEnCursoResponse,
    summary="La venta sin concluir de este equipo",
)
def en_curso(
    db: Session = Depends(get_db),
    dispositivo=Depends(get_active_device),
    autor=Depends(requiere_permiso(Modulo.VENTAS, "ver")),
):
    """
    Alimenta el banner "tenés una venta sin concluir" del home mobile.

    Devuelve `venta: null` en vez de un 404 cuando no hay ninguna: "no hay
    venta abierta" es una respuesta válida a esa pregunta, no un error.

    Va antes de `/{venta_id}` para que `en-curso` no se lea como un id.
    """
    abierta = servicio.venta_en_curso(db, autor.id, dispositivo.punto_de_venta_id)
    return VentaEnCursoResponse(venta=abierta)


@router.get(
    "/opciones-descuento",
    response_model=OpcionesDescuento,
    summary="Motivos y porcentajes válidos",
)
def opciones_descuento(
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.VENTAS, "ver")),
):
    """
    Lo que la pantalla de descuento necesita para dibujarse.

    Los porcentajes salen de acá y no de una constante en el JavaScript: son
    una regla de negocio, y dos listas que puedan separarse terminarían
    ofreciendo un valor que la API rechaza.
    """
    return OpcionesDescuento(
        motivos=[
            MotivoDescuentoResponse.model_validate(m)
            for m in servicio_descuentos.listar_motivos(db, activo=True)
        ],
        porcentajes=list(servicio_descuentos.PORCENTAJES_VALIDOS),
        tope=servicio_descuentos.TOPE_DESCUENTO,
    )


@router.get(
    "/producto",
    response_model=ProductoEscaneado,
    summary="El producto de un código, con el stock de ESTE local",
)
def producto_escaneado(
    codigo: str = Query(min_length=1, description="Código de la etiqueta, con o sin dígito"),
    db: Session = Depends(get_db),
    dispositivo=Depends(get_active_device),
    _=Depends(requiere_permiso(Modulo.VENTAS, "ver")),
):
    """
    Lo que la pantalla de escaneo dibuja apenas el lector emite el código.

    El stock que devuelve es el del local del dispositivo, no el total del
    sistema: a la vendedora no le sirve saber que hay 12 unidades repartidas
    en seis locales. Que sea 0 NO es un error — se devuelve igual, y la
    pantalla avisa sin bloquear.

    Va antes de `/{venta_id}` para que `producto` no se lea como un id.
    """
    from app.services import stock as servicio_stock

    try:
        variante = servicio.buscar_variante(db, codigo)
    except NoEncontrado as exc:
        raise _404(exc) from exc

    producto = variante.producto
    foto = next(
        (f.url for f in producto.fotos if f.es_principal),
        producto.fotos[0].url if producto.fotos else None,
    )

    # El precio de la etiqueta: el de lista con el descuento propio del
    # producto ya aplicado. Se calcula con la MISMA función que usa el
    # carrito, o la pantalla mostraría un número y el ticket otro.
    precio_lista = Decimal(variante.precio_venta_efectivo)
    precio = servicio_descuentos.aplicar_descuentos(
        precio_lista,
        Decimal(producto.descuento_producto),
        Decimal("0"),
        servicio._redondeo(db),
    )

    return ProductoEscaneado(
        variante_id=variante.id,
        codigo=variante.codigo_con_verificador,
        descripcion=producto.descripcion
        + (f" — {variante.descripcion_sufijo}" if variante.descripcion_sufijo else ""),
        categoria=producto.categoria.nombre if producto.categoria else None,
        precio=precio,
        precio_lista=precio_lista,
        stock=servicio_stock.cantidad_en(
            db, variante.id, dispositivo.punto_de_venta_id
        ),
        stock_infinito=producto.stock_infinito,
        foto=foto,
    )


@router.get(
    "/por-codigo-cambio/{codigo}",
    response_model=VentaResponse,
    summary="Buscar la venta original por su código de cambio",
)
def por_codigo_cambio(
    codigo: str,
    db: Session = Depends(get_db),
    _=Depends(requiere_permiso(Modulo.VENTAS, "ver")),
):
    """
    Lo que se tipea del ticket de papel para hacer un cambio.

    NO aplica el filtro por dispositivo, y es a propósito: un cambio se
    puede hacer en cualquier local, no solo en el que vendió. Justamente por
    eso el ticket lleva un código y no un número de venta correlativo.
    """
    try:
        return _respuesta(servicio.por_codigo_cambio(db, codigo))
    except NoEncontrado as exc:
        raise _404(exc) from exc


@router.get("/{venta_id}", response_model=VentaResponse, summary="Detalle de venta")
def detalle(
    venta_id: int,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.VENTAS, "ver")),
):
    return _respuesta(_venta(db, venta_id, scope))


@router.get(
    "/{venta_id}/medios-de-pago",
    response_model=list[MedioDisponible],
    summary="Medios y planes que habilita esta venta",
)
def medios_de_pago(
    venta_id: int,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.VENTAS, "ver")),
):
    """
    Los medios activos, cada uno con los planes que ESTE monto habilita.

    Filtrado en el backend: la vendedora no tiene que conocer las reglas de
    montos mínimos, solo elegir entre lo que se le ofrece. Y si algún motivo
    de descuento de la venta habilita las cuotas sin interés, esos planes
    aparecen aunque la venta no llegue al mínimo.
    """
    venta = _venta(db, venta_id, scope)
    a_cobrar = sum((Decimal(i.precio_final) for i in venta.items), Decimal("0"))
    habilita = servicio._habilita_cuotas_sin_interes(venta)

    disponibles = []
    for medio in servicio_medios.listar_medios(db, activo=True):
        # La seña solo se ofrece si la venta tiene cliente y ese cliente
        # tiene saldo: mostrarla vacía sería ofrecer un camino sin salida.
        if medio.es_sena and venta.cliente_id is None:
            continue

        planes = servicio_medios.planes_disponibles(db, medio.id, a_cobrar, habilita)
        fila = MedioDisponible.model_validate(medio)
        fila.planes = [PlanCuotasResponse.model_validate(p) for p in planes]
        disponibles.append(fila)

    return disponibles


@router.get(
    "/{venta_id}/promociones",
    response_model=list[PromocionResumen],
    summary="Promociones que se pueden aplicar a esta venta",
)
def promociones_de_venta(
    venta_id: int,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    _=Depends(requiere_permiso(Modulo.VENTAS, "ver")),
):
    """Las vigentes hoy, más las asignadas al cliente de la venta."""
    venta = _venta(db, venta_id, scope)
    return servicio_promociones.promociones_aplicables(db, venta.cliente_id)


# ============================================================================
# ARMADO DEL CARRITO
# ============================================================================


@router.post(
    "",
    response_model=VentaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Iniciar una venta",
)
def iniciar(
    request: Request,
    db: Session = Depends(get_db),
    dispositivo=Depends(get_active_device),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.VENTAS, "crear")),
):
    """
    Abre una venta, o devuelve la que ya estaba abierta en este local.

    Devolver la existente en vez de crear otra evita dejar carritos
    huérfanos: dos ventas `en_curso` de la misma vendedora significan que
    una tiene productos que nadie va a cobrar.
    """
    try:
        venta = servicio.iniciar_venta(
            db, autor, dispositivo, scope, ip_origen=ip_de_request(request)
        )
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return _respuesta(venta)


@router.post(
    "/{venta_id}/items",
    response_model=ItemAgregadoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar una unidad al carrito",
)
def agregar_item(
    venta_id: int,
    datos: ItemAgregar,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.VENTAS, "crear")),
):
    """
    Una unidad por llamada. Dos anillos iguales son dos ítems, porque la
    promoción 2x1 tiene que poder dejar uno en $0 y cobrar el otro.

    El aviso de stock en cero viaja en el cuerpo, no como error: NO bloquea.
    La vendedora tiene el producto en la mano, así que lo que corresponde es
    pedirle que controle el código, no frenarle la venta.
    """
    if datos.codigo is None and datos.variante_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Hay que mandar el código de la etiqueta o el id de la variante",
        )

    venta = _venta(db, venta_id, scope)
    try:
        item, aviso = servicio.agregar_item(
            db,
            autor,
            venta,
            codigo=datos.codigo,
            variante_id=datos.variante_id,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    db.refresh(venta)
    return ItemAgregadoResponse(venta=_respuesta(venta), item_id=item.id, aviso=aviso)


@router.delete(
    "/{venta_id}/items/{item_id}",
    response_model=VentaResponse,
    summary="Quitar una unidad del carrito",
)
def quitar_item(
    venta_id: int,
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.VENTAS, "crear")),
):
    venta = _venta(db, venta_id, scope)
    try:
        servicio.quitar_item(db, autor, venta, item_id, ip_origen=ip_de_request(request))
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    db.refresh(venta)
    return _respuesta(venta)


@router.post(
    "/{venta_id}/cliente", response_model=VentaResponse, summary="Asociar el cliente"
)
def asociar_cliente(
    venta_id: int,
    datos: ClienteAsociar,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.VENTAS, "crear")),
):
    """
    El cliente es opcional: `cliente_id` en NULL lo desasocia.

    Vuelve a calcular la venta porque el cliente puede traer promociones
    propias: la misma bolsa de productos puede valer distinto según quién
    compre.
    """
    venta = _venta(db, venta_id, scope)
    try:
        servicio.asociar_cliente(
            db, autor, venta, datos.cliente_id, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    db.refresh(venta)
    return _respuesta(venta)


@router.post(
    "/{venta_id}/descuento",
    response_model=VentaResponse,
    summary="Aplicar o sacar el descuento de una unidad",
)
def aplicar_descuento(
    venta_id: int,
    datos: DescuentoAplicar,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(
        requiere_permiso(Modulo.VENTAS, "crear", Recurso.VENTA_DESCUENTO)
    ),
):
    """
    Pide el permiso `venta.descuento`, aparte del de vender: descontar es
    una decisión comercial y no todas las vendedoras la tienen.

    `motivo_id` en NULL saca el descuento del ítem.
    """
    venta = _venta(db, venta_id, scope)
    try:
        servicio.aplicar_descuento_item(
            db,
            autor,
            venta,
            datos.item_id,
            motivo_id=datos.motivo_id,
            porcentaje=datos.porcentaje,
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    db.refresh(venta)
    return _respuesta(venta)


@router.post(
    "/{venta_id}/promocion",
    response_model=VentaResponse,
    summary="Elegir la promoción a mano",
)
def aplicar_promocion(
    venta_id: int,
    datos: PromocionAplicar,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.VENTAS, "crear")),
):
    """
    El sistema ya elige sola la promoción que más conviene cada vez que
    cambia el carrito. Esto sirve para forzar otra —o ninguna— y **vale
    hasta el próximo cambio del carrito**: agregar o quitar un producto
    vuelve a disparar la elección automática, para que el total nunca quede
    peor de lo que corresponde por una promo elegida a mano y olvidada.
    """
    venta = _venta(db, venta_id, scope)
    try:
        servicio.elegir_promocion(
            db, autor, venta, datos.promocion_id, ip_origen=ip_de_request(request)
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    db.refresh(venta)
    return _respuesta(venta)


# ============================================================================
# COBRO Y CIERRE
# ============================================================================


@router.post(
    "/{venta_id}/pagos", response_model=VentaResponse, summary="Registrar los medios de pago"
)
def registrar_pagos(
    venta_id: int,
    datos: PagosRegistrar,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.VENTAS, "crear")),
):
    """
    Reemplaza lo que hubiera cargado antes. Hasta dos medios.

    Los montos suman lo que valen los productos, SIN recargos: el recargo lo
    calcula el sistema sobre cada parte financiada y lo suma después.
    """
    venta = _venta(db, venta_id, scope)
    try:
        servicio.registrar_pagos(
            db,
            autor,
            venta,
            [p.model_dump() for p in datos.pagos],
            ip_origen=ip_de_request(request),
        )
    except NoEncontrado as exc:
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    db.refresh(venta)
    return _respuesta(venta)


@router.post(
    "/{venta_id}/confirmar", response_model=VentaResponse, summary="Confirmar la venta"
)
def confirmar(
    venta_id: int,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.VENTAS, "crear")),
):
    """
    Descuenta el stock, suma los puntos, consume las señas y genera el
    código de cambio. Todo en UNA transacción: si algo falla, no queda nada
    aplicado.

    El único commit está acá abajo, y es lo que da esa garantía.
    """
    venta = _venta(db, venta_id, scope)
    try:
        servicio.confirmar_venta(db, autor, venta, scope, ip_origen=ip_de_request(request))
    except NoEncontrado as exc:
        db.rollback()
        raise _404(exc) from exc
    except ReglaDeNegocio as exc:
        db.rollback()
        raise _409(exc) from exc

    db.commit()
    db.refresh(venta)
    return _respuesta(venta)


@router.patch(
    "/{venta_id}/anular", response_model=VentaResponse, summary="Anular una venta"
)
def anular(
    venta_id: int,
    datos: VentaAnular,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.VENTAS, "eliminar", Recurso.VENTA_ANULAR)),
):
    """
    Solo Supervisor y Dueño (permiso `venta.anular`).

    Devuelve el stock, saca los puntos y repone el saldo de las señas usadas.
    La fila NO se borra: la venta ocurrió, y la caja de ese día tiene que
    poder explicarse.
    """
    venta = _venta(db, venta_id, scope)
    try:
        servicio.anular_venta(
            db, autor, venta, datos.motivo, ip_origen=ip_de_request(request)
        )
    except ReglaDeNegocio as exc:
        db.rollback()
        raise _409(exc) from exc

    db.commit()
    db.refresh(venta)
    return _respuesta(venta)


@router.delete(
    "/{venta_id}", response_model=MensajeResponse, summary="Descartar una venta en curso"
)
def descartar(
    venta_id: int,
    request: Request,
    db: Session = Depends(get_db),
    scope: DeviceScope = Depends(get_device_scope),
    autor=Depends(requiere_permiso(Modulo.VENTAS, "crear")),
):
    """
    Tira el carrito.

    Se borra de verdad, a diferencia de la anulación: nunca tocó el stock ni
    los puntos, así que no hay nada que revertir. Lo que queda es el registro
    de auditoría de que se descartó.
    """
    venta = _venta(db, venta_id, scope)
    try:
        servicio.descartar_venta(db, autor, venta, ip_origen=ip_de_request(request))
    except ReglaDeNegocio as exc:
        raise _409(exc) from exc

    db.commit()
    return MensajeResponse(mensaje="Venta descartada")
