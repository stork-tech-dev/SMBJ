"""
Schemas de Reportes de Caja. Datos crudos: montos Decimal y fechas ISO; el
formato lo pone el frontend (Principio 1).

Cada respuesta trae `opciones_locales` para el combo de Local, mismo motivo
que los otros reportes: un perfil con solo Reportes no puede pedirle nada a
`/api/v1/puntos-de-venta`.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.operaciones_caja import RetiroMercaderiaResponse
from app.schemas.stock import PuntoResumen


class _ConLocales(BaseModel):
    opciones_locales: list[PuntoResumen]


class _Turno(BaseModel):
    turno_id: int
    punto_de_venta_id: int
    punto_de_venta_nombre: str
    fecha_apertura: datetime
    fecha_cierre: datetime | None


# --- Novedades de caja ---


class NovedadReporte(BaseModel):
    id: int
    timestamp: datetime
    concepto: str
    tipo: str
    monto: Decimal
    autorizador_nombre: str
    registrado_por_nombre: str
    notas: str | None


class NovedadesTurno(_Turno):
    novedades: list[NovedadReporte]
    total_entradas: Decimal
    total_salidas: Decimal
    neto: Decimal


class ReporteNovedades(_ConLocales):
    turnos: list[NovedadesTurno]
    total_entradas: Decimal
    total_salidas: Decimal
    neto: Decimal


# --- Arqueos de caja ---


class ArqueoItemReporte(BaseModel):
    columna: str
    monto_esperado: Decimal
    monto_declarado: Decimal
    diferencia: Decimal
    es_informativo: bool


class ArqueoReporte(_Turno):
    arqueo_id: int
    usuario_nombre: str
    items: list[ArqueoItemReporte]
    total_esperado: Decimal
    total_declarado: Decimal
    diferencia: Decimal


class ReporteArqueos(_ConLocales):
    columnas: list[str]
    filas: list[ArqueoReporte]


# --- Movimientos de caja por turno ---


class MovimientoCaja(BaseModel):
    timestamp: datetime
    # apertura | venta | cobro_joyero | sena | novedad | retiro_efectivo
    tipo: str
    detalle: str
    medio_de_pago: str | None
    ingreso: Decimal
    egreso: Decimal
    # Se muestra pero no suma: la parte de una venta pagada con seña (la
    # plata entró a la caja cuando se dejó la seña).
    informativo: Decimal = Decimal("0")


class MovimientosTurno(_Turno):
    movimientos: list[MovimientoCaja]
    total_ingresos: Decimal
    total_egresos: Decimal
    efectivo_esperado: Decimal


class ReporteMovimientos(_ConLocales):
    turnos: list[MovimientosTurno]


class MovimientosCajaLocal(BaseModel):
    """El mismo reporte desde el celular: un solo local, sin selector."""

    turnos: list[MovimientosTurno]


# --- Retiros de efectivo ---


class RetiroEfectivoReporte(BaseModel):
    id: int
    turno_id: int
    timestamp: datetime
    punto_de_venta_nombre: str
    usuario_nombre: str
    registrado_por_nombre: str
    monto: Decimal


class ReporteRetirosEfectivo(_ConLocales):
    filas: list[RetiroEfectivoReporte]
    total: Decimal


# --- Cobros de joyero ---


class CobroJoyeroReporte(BaseModel):
    id: int
    turno_id: int
    timestamp: datetime
    punto_de_venta_nombre: str
    vendedora_nombre: str
    numero_reclamo: str | None
    medio_de_pago: str
    monto: Decimal
    notas: str | None


class TotalPorMedio(BaseModel):
    medio_de_pago: str
    monto: Decimal


class ReporteCobrosJoyero(_ConLocales):
    filas: list[CobroJoyeroReporte]
    totales_por_medio: list[TotalPorMedio]
    total: Decimal


# --- Señas ---


class SenaReporte(BaseModel):
    id: int
    created_at: datetime
    cliente_nombre: str
    monto: Decimal
    saldo: Decimal
    fecha_vencimiento: date
    # activa | usada | vencida
    estado: str
    descripcion: str | None


class ReporteSenas(BaseModel):
    """Sin `opciones_locales`: las señas no son de un local."""

    dias_vigencia: int
    filas: list[SenaReporte]
    total_monto: Decimal
    total_saldo: Decimal


# --- Retiros de mercadería ---


class EmpleadaRetiros(BaseModel):
    empleada_nombre: str
    empleada_dni: str | None
    es_empresa_propia: bool
    retiros: list[RetiroMercaderiaResponse]
    subtotal_lista: Decimal
    # Lo que se descuenta del sueldo.
    subtotal: Decimal


class ReporteRetirosMercaderiaCaja(_ConLocales):
    empleadas: list[EmpleadaRetiros]
    total_lista: Decimal
    total: Decimal
