"""
Registro central de modelos SQLAlchemy.

Importar acá todo modelo nuevo: Alembic usa este paquete para descubrir
las tablas al autogenerar migraciones.
"""

from app.core.database import Base
from app.models.auditoria import Auditoria
from app.models.compra import Compra, CompraItem, EstadoCompra
from app.models.auditoria_inventario import (
    AuditoriaInventario,
    AuditoriaItem,
    EstadoAuditoria,
)
from app.models.categoria import NIVEL_MAXIMO, Categoria
from app.models.cliente import Cliente, ClientePromocion, PuntoCliente, TipoPunto
from app.models.configuracion import ConfiguracionSistema
from app.models.dispositivo import Dispositivo
from app.models.medio_pago import MedioDePago, PlanCuotas
from app.models.motivo_baja import MotivoBaja
from app.models.permiso import RolPermiso, UsuarioPermiso
from app.models.producto import Producto, Temporada, Variante
from app.models.producto_foto import MAX_FOTOS_POR_PRODUCTO, ProductoFoto
from app.models.promocion import (
    PAGAS_POR_GRUPO,
    TAMANO_GRUPO,
    Promocion,
    PromocionAlcance,
    TipoAlcance,
    TipoPromocion,
)
from app.models.punto_de_venta import PuntoDeVenta, TipoPuntoVenta
from app.models.proveedor import (
    EstadoProveedor,
    OrigenCambioDolar,
    Proveedor,
    ProveedorDolarHistorial,
)
from app.models.remito import EstadoRemito, Remito, RemitoItem
from app.models.rol import Rol
from app.models.sena import Sena
from app.models.sesion import Sesion
from app.models.stock import MovimientoStock, Stock, TipoMovimiento
from app.models.usuario import HistorialAcceso, ResultadoAcceso, Usuario
from app.models.venta import (
    EstadoVenta,
    MotivoDescuento,
    Venta,
    VentaItem,
    VentaPago,
)
from app.models.turno import (
    Arqueo,
    ArqueoItem,
    EstadoTurno,
    GiftCardVirtualUso,
    MedioPagoArqueoConfig,
    Notificacion,
    PlataformaGiftCard,
    RetiroEfectivo,
    TipoNotificacion,
    Turno,
    TurnoVendedora,
)

__all__ = [
    "Base",
    "Auditoria",
    "Compra",
    "CompraItem",
    "EstadoCompra",
    "Categoria",
    "Producto",
    "Variante",
    "ProductoFoto",
    "MAX_FOTOS_POR_PRODUCTO",
    "Temporada",
    "NIVEL_MAXIMO",
    "ConfiguracionSistema",
    "MotivoBaja",
    "Rol",
    "RolPermiso",
    "UsuarioPermiso",
    "Usuario",
    "HistorialAcceso",
    "ResultadoAcceso",
    "Sesion",
    "Proveedor",
    "ProveedorDolarHistorial",
    "EstadoProveedor",
    "OrigenCambioDolar",
    "PuntoDeVenta",
    "TipoPuntoVenta",
    "Dispositivo",
    "Stock",
    "MovimientoStock",
    "TipoMovimiento",
    "Remito",
    "RemitoItem",
    "EstadoRemito",
    "AuditoriaInventario",
    "AuditoriaItem",
    "EstadoAuditoria",
    "Cliente",
    "PuntoCliente",
    "TipoPunto",
    "ClientePromocion",
    "MedioDePago",
    "PlanCuotas",
    "Promocion",
    "PromocionAlcance",
    "TipoPromocion",
    "TipoAlcance",
    "TAMANO_GRUPO",
    "PAGAS_POR_GRUPO",
    "Sena",
    "Venta",
    "VentaItem",
    "VentaPago",
    "EstadoVenta",
    "MotivoDescuento",
    "Turno",
    "TurnoVendedora",
    "RetiroEfectivo",
    "MedioPagoArqueoConfig",
    "Arqueo",
    "ArqueoItem",
    "PlataformaGiftCard",
    "GiftCardVirtualUso",
    "Notificacion",
    "EstadoTurno",
    "TipoNotificacion",
]
