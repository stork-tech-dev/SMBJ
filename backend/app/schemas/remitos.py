"""Schemas de remitos: el traslado de mercadería entre ubicaciones."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.stock import PuntoResumen, VarianteEnStock

_ESTADO = "^(pendiente|en_camino|confirmado|con_diferencia)$"


class RemitoItemCrear(BaseModel):
    variante_id: int
    cantidad: int = Field(gt=0)


class RemitoCrear(BaseModel):
    """
    El envío que se arma. Descuenta el stock del origen en el acto: la
    mercadería se baja de la estantería ahora, no cuando llegue.
    """

    punto_venta_origen_id: int
    punto_venta_destino_id: int
    items: list[RemitoItemCrear] = Field(min_length=1)
    notas: str | None = None


class RemitoRecepcionItem(BaseModel):
    variante_id: int
    cantidad_recibida: int = Field(ge=0)


class RemitoConfirmar(BaseModel):
    """
    La recepción.

    `numero_confirmacion` es el número del remito, el que viene impreso en el
    papel que viaja con la carga: tenerlo es la prueba de que la mercadería
    llegó a destino. Si no coincide, 403.

    `items` es opcional: las variantes que no vengan se toman como recibidas
    completas. Lo normal es que todo llegue, y obligar a tipear cada línea
    para el caso habitual invita a equivocarse.
    """

    numero_confirmacion: str = Field(min_length=1, max_length=12)
    items: list[RemitoRecepcionItem] = []
    notas: str | None = None


class RemitoItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cantidad_enviada: int
    # NULL hasta que alguien cuente. NULL y 0 no son lo mismo: NULL es
    # "todavía no se contó", 0 es "se contó y no llegó nada".
    cantidad_recibida: int | None
    # Lo que falta (negativo) o sobra (positivo). Lo resuelve el backend.
    diferencia: int | None
    variante: VarianteEnStock


class RemitoResumen(BaseModel):
    """Una fila del listado: sin los ítems, que son del detalle."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    numero: str
    estado: str
    fecha_envio: datetime
    fecha_recepcion: datetime | None
    origen: PuntoResumen
    destino: PuntoResumen
    pdf_url: str | None


class RemitoResponse(RemitoResumen):
    """El detalle, con sus ítems y quién intervino."""

    model_config = ConfigDict(from_attributes=True)

    usuario_envio_id: int
    usuario_recepcion_id: int | None
    notas: str | None
    created_at: datetime
    updated_at: datetime
    items: list[RemitoItemResponse]
