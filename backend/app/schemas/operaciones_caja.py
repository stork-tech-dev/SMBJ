"""
Schemas de las operaciones de caja (sesión 09): retiros de efectivo,
novedades de caja, retiros de mercadería y cobros de joyero.

Ningún schema expone `codigo_retiro_hash`. Los importes viajan crudos
(Decimal); el formato de moneda lo pone el frontend (Principio 1).
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.stock import PuntoResumen

# ── Código de retiro (Cuenta Maestra) ──────────────────────────────────────


class CodigoRetiroAsignar(BaseModel):
    codigo: str = Field(pattern=r"^\d{4}$", description="4 dígitos")


# ── Retiros de efectivo ────────────────────────────────────────────────────


class RetiroEfectivoRequest(BaseModel):
    monto: Decimal = Field(gt=0)
    codigo: str = Field(min_length=1, max_length=10, description="Código de 4 dígitos de quien retira")


class EfectivoDisponibleResponse(BaseModel):
    turno_id: int
    disponible: Decimal


class RetiroEfectivoResponse(BaseModel):
    id: int
    turno_id: int
    punto_de_venta_id: int
    punto_de_venta_nombre: str
    usuario_id: int
    usuario_nombre: str
    registrado_por_id: int
    registrado_por_nombre: str
    monto: Decimal
    timestamp: datetime

    @classmethod
    def de(cls, r) -> "RetiroEfectivoResponse":
        return cls(
            id=r.id,
            turno_id=r.turno_id,
            punto_de_venta_id=r.punto_de_venta_id,
            punto_de_venta_nombre=r.punto_de_venta.nombre,
            usuario_id=r.usuario_id,
            usuario_nombre=r.usuario.nombre,
            registrado_por_id=r.registrado_por_id,
            registrado_por_nombre=r.registrado_por.nombre,
            monto=r.monto,
            timestamp=r.timestamp,
        )


# ── Novedades de caja ──────────────────────────────────────────────────────

_TIPO_NOVEDAD = "^(entrada|salida)$"


class ConceptoNovedadCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    tipo: str = Field(pattern=_TIPO_NOVEDAD)


class ConceptoNovedadEditar(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    tipo: str | None = Field(default=None, pattern=_TIPO_NOVEDAD)


class ConceptoNovedadEstado(BaseModel):
    activo: bool


class ConceptoNovedadResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    nombre: str
    tipo: str
    activo: bool


class NovedadCajaRequest(BaseModel):
    concepto_id: int
    monto: Decimal = Field(gt=0)
    autorizador_id: int
    notas: str | None = Field(default=None, max_length=500)


class NovedadCajaResponse(BaseModel):
    id: int
    turno_id: int
    punto_de_venta_id: int
    punto_de_venta_nombre: str
    concepto_id: int
    concepto_nombre: str
    tipo: str
    monto: Decimal
    autorizador_id: int
    autorizador_nombre: str
    registrado_por_nombre: str
    timestamp: datetime
    notas: str | None

    @classmethod
    def de(cls, n) -> "NovedadCajaResponse":
        return cls(
            id=n.id,
            turno_id=n.turno_id,
            punto_de_venta_id=n.punto_de_venta_id,
            punto_de_venta_nombre=n.punto_de_venta.nombre,
            concepto_id=n.concepto_id,
            concepto_nombre=n.concepto.nombre,
            tipo=n.tipo.value,
            monto=n.monto,
            autorizador_id=n.autorizador_id,
            autorizador_nombre=n.autorizador.nombre,
            registrado_por_nombre=n.registrado_por.nombre,
            timestamp=n.timestamp,
            notas=n.notas,
        )


# ── Retiros de mercadería ──────────────────────────────────────────────────


class EmpleadaResumen(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    username: str
    nombre: str


class CotizacionRetiroResponse(BaseModel):
    """Lo que la pantalla muestra antes de confirmar."""

    variante_id: int
    codigo: str
    descripcion: str
    foto: str | None
    precio_lista: Decimal
    descuento: Decimal
    precio_con_descuento: Decimal
    motivo_nombre: str
    stock: int
    stock_infinito: bool


class RetiroMercaderiaRequest(BaseModel):
    variante_id: int
    # Empleada de esta empresa: su usuario. De la otra: nombre (y DNI) a mano.
    empleada_usuario_id: int | None = None
    empleada_nombre: str | None = Field(default=None, max_length=150)
    empleada_dni: str | None = Field(default=None, max_length=15)


class RetiroMercaderiaResponse(BaseModel):
    id: int
    turno_id: int
    punto_de_venta_id: int
    punto_de_venta_nombre: str
    es_empresa_propia: bool
    empleada_usuario_id: int | None
    empleada_nombre: str
    empleada_dni: str | None
    variante_id: int
    codigo: str
    descripcion: str
    precio_lista: Decimal
    descuento_aplicado: Decimal
    precio_con_descuento: Decimal
    codigo_cambio: str
    registrado_por_nombre: str
    timestamp: datetime

    @classmethod
    def de(cls, r) -> "RetiroMercaderiaResponse":
        variante = r.variante
        descripcion = variante.producto.descripcion
        if variante.descripcion_sufijo:
            descripcion = f"{descripcion} — {variante.descripcion_sufijo}"
        return cls(
            id=r.id,
            turno_id=r.turno_id,
            punto_de_venta_id=r.punto_de_venta_id,
            punto_de_venta_nombre=r.punto_de_venta.nombre,
            es_empresa_propia=r.es_empresa_propia,
            empleada_usuario_id=r.empleada_usuario_id,
            empleada_nombre=r.nombre_empleada,
            empleada_dni=r.empleada_dni,
            variante_id=r.variante_id,
            codigo=variante.codigo_con_verificador,
            descripcion=descripcion,
            precio_lista=r.precio_lista,
            descuento_aplicado=r.descuento_aplicado,
            precio_con_descuento=r.precio_con_descuento,
            codigo_cambio=r.codigo_cambio,
            registrado_por_nombre=r.registrado_por.nombre,
            timestamp=r.timestamp,
        )


# ── Cobros de joyero ───────────────────────────────────────────────────────


class MedioCobroResponse(BaseModel):
    id: int
    nombre: str
    es_efectivo: bool


class CobroJoyeroRequest(BaseModel):
    medio_de_pago_id: int
    monto_efectivo: Decimal = Field(default=Decimal("0"), ge=0)
    monto_otros: Decimal = Field(default=Decimal("0"), ge=0)
    numero_reclamo: str | None = Field(default=None, max_length=50)
    notas: str | None = Field(default=None, max_length=500)


class CobroJoyeroResponse(BaseModel):
    id: int
    turno_id: int
    punto_de_venta_id: int
    punto_de_venta_nombre: str
    medio_de_pago_id: int
    medio_de_pago_nombre: str
    monto_efectivo: Decimal
    monto_otros: Decimal
    monto_cobrado: Decimal
    numero_reclamo: str | None
    registrado_por_nombre: str
    timestamp: datetime
    notas: str | None

    @classmethod
    def de(cls, c) -> "CobroJoyeroResponse":
        return cls(
            id=c.id,
            turno_id=c.turno_id,
            punto_de_venta_id=c.punto_de_venta_id,
            punto_de_venta_nombre=c.punto_de_venta.nombre,
            medio_de_pago_id=c.medio_de_pago_id,
            medio_de_pago_nombre=c.medio_de_pago.nombre,
            monto_efectivo=c.monto_efectivo,
            monto_otros=c.monto_otros,
            monto_cobrado=c.monto_cobrado,
            numero_reclamo=c.numero_reclamo,
            registrado_por_nombre=c.registrado_por.nombre,
            timestamp=c.timestamp,
            notas=c.notas,
        )


class ReporteRetirosMercaderiaResponse(BaseModel):
    """Reporte para liquidar sueldos: primero esta empresa, después la otra."""

    resultados: list[RetiroMercaderiaResponse]
    total: int
    pagina: int
    tamano: int
    opciones_locales: list[PuntoResumen]
