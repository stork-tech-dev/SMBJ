"""
Schemas del flujo de venta y del catálogo de motivos de descuento.

Todos los importes viajan como `Decimal` crudo: el símbolo de peso, los
separadores de miles y el redondeo de pantalla los pone el frontend
(Principio 1).
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.venta import EstadoVenta
from app.schemas.clientes import ClienteResumen
from app.schemas.stock import PuntoResumen
from app.schemas.promociones import PromocionResumen
from app.schemas.stock import PuntoResumen, VarianteEnStock


# ============================================================================
# MOTIVOS DE DESCUENTO (Configuración)
# ============================================================================


class RestriccionItem(BaseModel):
    """Una restricción de sucursal o medio de pago para un motivo."""

    tipo: str  # 'punto_de_venta' | 'medio_de_pago'
    referencia_id: int


class MotivoDescuentoCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    nota: str | None = Field(default=None, max_length=500)
    porcentaje_sugerido: Decimal | None = Field(
        default=None,
        description="Se preselecciona al elegir el motivo. NULL = la vendedora elige",
    )
    habilita_cuotas_sin_interes: bool = Field(
        default=False,
        description="Ofrece los planes sin interés aunque la venta no llegue al mínimo",
    )
    es_descuento_empleada: bool = Field(
        default=False,
        description="El motivo que se aplica en los retiros de mercadería de empleadas (uno solo)",
    )
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    restricciones: list[RestriccionItem] = Field(default_factory=list)


class MotivoDescuentoEditar(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    nota: str | None = None
    porcentaje_sugerido: Decimal | None = None
    habilita_cuotas_sin_interes: bool | None = None
    es_descuento_empleada: bool | None = None
    activo: bool | None = None
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    restricciones: list[RestriccionItem] | None = None


class MotivoDescuentoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    nota: str | None
    porcentaje_sugerido: Decimal | None
    habilita_cuotas_sin_interes: bool
    es_descuento_empleada: bool = False
    activo: bool
    fecha_inicio: date | None
    fecha_fin: date | None
    restricciones: list[RestriccionItem]

    @classmethod
    def from_orm_motivo(cls, motivo) -> "MotivoDescuentoResponse":
        return cls(
            id=motivo.id,
            nombre=motivo.nombre,
            nota=motivo.nota,
            porcentaje_sugerido=motivo.porcentaje_sugerido,
            habilita_cuotas_sin_interes=motivo.habilita_cuotas_sin_interes,
            es_descuento_empleada=motivo.es_descuento_empleada,
            activo=motivo.activo,
            fecha_inicio=motivo.fecha_inicio,
            fecha_fin=motivo.fecha_fin,
            restricciones=[
                RestriccionItem(tipo=r.tipo, referencia_id=r.referencia_id)
                for r in motivo.restricciones
            ],
        )


class EstadoCambio(BaseModel):
    activo: bool


class OpcionesDescuento(BaseModel):
    """
    Lo que la pantalla de descuento necesita para dibujarse: los motivos
    activos y la lista de porcentajes.

    Los porcentajes salen del backend y no de una constante en el
    JavaScript. Son una regla de negocio, y dos listas que puedan separarse
    terminarían ofreciendo un valor que la API rechaza.
    """

    motivos: list[MotivoDescuentoResponse]
    porcentajes: list[int]
    tope: Decimal


# ============================================================================
# VENTA
# ============================================================================


class ProductoEscaneado(BaseModel):
    """
    Lo que la pantalla de escaneo muestra apenas encuentra el producto.

    Existe como respuesta propia en vez de reusar el listado de variantes por
    una razón concreta: acá el stock es el de ESTE local, no el total del
    sistema. A la vendedora no le sirve saber que hay 12 unidades repartidas
    en seis locales — le sirve saber cuántas hay donde está parada.

    Junta en una llamada lo que si no serían tres (producto, foto, stock):
    la pantalla se dibuja entera de una vez, con el lector esperando el
    código siguiente.
    """

    variante_id: int
    codigo: str
    descripcion: str
    categoria: str | None
    # Precio de la etiqueta: el de lista con el descuento propio del
    # producto ya aplicado. Es lo que la vendedora tiene que poder comparar
    # contra el cartel.
    precio: Decimal
    precio_lista: Decimal
    stock: int
    stock_infinito: bool
    # URL de la foto principal. La vendedora la mira para confirmar que
    # escaneó lo que tiene en la mano.
    foto: str | None


class ItemAgregar(BaseModel):
    """
    Una unidad al carrito, por código escaneado o por id de variante.

    El código es el camino normal —es lo que emite el lector—; el
    `variante_id` existe para las pantallas que ya resolvieron el producto y
    no tendrían por qué volver a mandar el texto de la etiqueta.
    """

    codigo: str | None = Field(
        default=None, description="Código de la etiqueta, con o sin dígito verificador"
    )
    variante_id: int | None = None


class ClienteAsociar(BaseModel):
    """`cliente_id` en NULL desasocia: la venta vuelve a ser sin cliente."""

    cliente_id: int | None = None


class DescuentoAplicar(BaseModel):
    """
    Descuento sobre una unidad.

    El motivo va primero y es obligatorio: sin él no hay descuento, porque
    un descuento que no se puede explicar no sirve en el reporte de fin de
    mes. `motivo_id` en NULL saca el descuento del ítem.

    `porcentaje` es opcional cuando el motivo trae uno sugerido.
    """

    item_id: int
    motivo_id: int | None = None
    porcentaje: Decimal | None = None


class PromocionAplicar(BaseModel):
    """
    Fija a mano la promoción, o la saca con NULL.

    Vale hasta el próximo cambio del carrito: agregar o quitar un producto
    vuelve a disparar la elección automática de la que más conviene.
    """

    promocion_id: int | None = None


class PagoItem(BaseModel):
    """
    Un medio de pago de la venta.

    `monto` es la parte que cubre este medio ANTES del recargo. El recargo
    lo calcula el sistema sobre este monto y lo suma después: pedirle a la
    vendedora que lo incluya sería pedirle que haga la cuenta que el
    sistema tiene que hacer.
    """

    medio_de_pago_id: int
    monto: Decimal = Field(gt=0)
    plan_cuotas_id: int | None = None


class PagosRegistrar(BaseModel):
    """
    Reemplaza los medios de pago de la venta. Hasta dos, sin contar la seña.

    Con `usar_sena`, el sistema aplica las señas vigentes del cliente (se
    consumen enteras, cubriendo como máximo el total) y `pagos` cubre el
    resto. Si la seña alcanza, `pagos` va vacío.
    """

    pagos: list[PagoItem] = Field(default_factory=list, max_length=2)
    usar_sena: bool = False


class VentaAnular(BaseModel):
    motivo: str | None = None


class VentaItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    orden: int
    variante: VarianteEnStock
    # Los tres precios son distintos y los tres importan: `precio_lista` es
    # el de la etiqueta sin ningún descuento —el que vale para un cambio—,
    # `precio_unitario` el que ya trae el descuento propio del producto, y
    # `precio_final` lo que efectivamente se cobra.
    precio_lista: Decimal
    precio_unitario: Decimal
    precio_final: Decimal
    descuento_item: Decimal
    motivo_descuento_id: int | None
    porcentaje_modificado: bool
    en_promocion: bool


class VentaPagoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    medio_de_pago_id: int
    plan_cuotas_id: int | None
    monto: Decimal
    recargo: Decimal
    monto_total: Decimal
    sena_id: int | None
    # Lo que se descontó de la seña; si es más que `monto`, la diferencia
    # se perdió por el uso total.
    sena_consumido: Decimal | None = None


class VentaResumen(BaseModel):
    """La fila del listado. Sin ítems: la tabla no los muestra."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    numero: str
    estado: EstadoVenta
    subtotal: Decimal
    descuento_total: Decimal
    recargo_total: Decimal
    total: Decimal
    codigo_cambio: str | None
    codigo_cambio_activo: bool
    puntos_acumulados: int
    created_at: datetime
    cliente: ClienteResumen | None
    punto_de_venta: PuntoResumen
    usuario_id: int
    # Nombres de los medios con los que se cobró (ver `Venta.medios_pago`).
    # Vacío en una venta `en_curso`, que todavía no cobró nada.
    medios_pago: list[str]


class VentaResponse(VentaResumen):
    """El detalle completo, que es lo que dibuja el carrito y el cobro."""

    dispositivo_id: int
    updated_at: datetime
    promocion: PromocionResumen | None
    items: list[VentaItemResponse] = []
    pagos: list[VentaPagoResponse] = []

    # Lo que hay que cubrir con medios de pago: la suma de los `precio_final`
    # SIN recargos. Es el número contra el que se validan los pagos, y va
    # calculado para que la pantalla no tenga que sumar la lista de ítems.
    a_cobrar: Decimal = Decimal("0")


class ItemAgregadoResponse(BaseModel):
    """
    La respuesta de agregar al carrito: la venta completa más el aviso.

    El aviso de stock en cero viaja acá y no como un error HTTP porque NO
    bloquea: la vendedora tiene el producto en la mano, y lo que el sistema
    le pide es que controle el código, no que frene la venta.
    """

    venta: VentaResponse
    item_id: int
    aviso: str | None = None


class VentaEnCursoResponse(BaseModel):
    """
    Lo que el home mobile necesita para el banner "venta sin concluir".

    Devuelve `venta` en NULL en vez de un 404 cuando no hay ninguna: "no hay
    venta abierta" es una respuesta válida a esa pregunta, no un error.
    """

    venta: VentaResumen | None = None


# ---------------------------------------------------------------------------
# Reporte: análisis de ventas por producto
# ---------------------------------------------------------------------------


class AnalisisProductoFila(BaseModel):
    """
    Una variante y cuánto vendió. Las fechas son sobre TODO el historial de
    ventas confirmadas (con los filtros de ubicación/categoría/proveedor
    aplicados), no solo la ventana de 90 días que define qué filas entran.
    """

    variante_id: int
    codigo_completo: str
    verificador: str
    descripcion: str
    descripcion_sufijo: str | None
    categoria_nombre: str
    proveedor_nombre: str
    cantidad_30_dias: int
    cantidad_90_dias: int
    fecha_primera_venta: datetime
    fecha_ultima_venta: datetime


class AnalisisVentasResponse(BaseModel):
    resultados: list[AnalisisProductoFila]
    total: int
    pagina: int
    tamano: int
    # Mismo motivo que en StockBajoMinimoResponse: no depender de
    # /api/v1/puntos-de-venta, que exige permiso de Configuración.
    opciones_locales: list[PuntoResumen]


# ---------------------------------------------------------------------------
# Reporte: resumen por punto de venta
# ---------------------------------------------------------------------------


class ResumenPuntoVentaFila(BaseModel):
    """Un local: cuánto vendió y qué porcentaje cobró con cada medio de pago."""

    punto_de_venta_id: int
    punto_de_venta_nombre: str
    total: Decimal
    # Clave = nombre del medio de pago, valor = porcentaje (0-100) del total
    # cobrado con ese medio. Solo trae los medios usados en el período.
    porcentajes: dict[str, Decimal]


class ResumenPuntoVentaResponse(BaseModel):
    filas: list[ResumenPuntoVentaFila]
    # Columnas de medio de pago a dibujar, ya ordenadas: solo las que
    # de verdad se usaron en el período filtrado.
    columnas_medios: list[str]


# ---------------------------------------------------------------------------
# Reporte: resumen diario consolidado
# ---------------------------------------------------------------------------


class ResumenDiarioFila(BaseModel):
    """Un turno: su local, su franja horaria y cuánto vendió."""

    turno_id: int
    punto_de_venta_id: int
    punto_de_venta_nombre: str
    fecha_apertura: datetime
    # NULL si el turno todavía está abierto.
    fecha_cierre: datetime | None
    cantidad_ventas: int
    total: Decimal


class ResumenDiarioResponse(BaseModel):
    filas: list[ResumenDiarioFila]
    opciones_locales: list[PuntoResumen]
