"""
Registro central de modelos SQLAlchemy.

Importar acá todo modelo nuevo: Alembic usa este paquete para descubrir
las tablas al autogenerar migraciones.
"""

from app.core.database import Base
from app.models.auditoria import Auditoria
from app.models.categoria import NIVEL_MAXIMO, Categoria
from app.models.configuracion import ConfiguracionSistema
from app.models.dispositivo import Dispositivo
from app.models.motivo_baja import MotivoBaja
from app.models.permiso import RolPermiso, UsuarioPermiso
from app.models.producto import Producto, Temporada, Variante
from app.models.producto_foto import MAX_FOTOS_POR_PRODUCTO, ProductoFoto
from app.models.punto_de_venta import PuntoDeVenta, TipoPuntoVenta
from app.models.proveedor import (
    EstadoProveedor,
    OrigenCambioDolar,
    Proveedor,
    ProveedorDolarHistorial,
)
from app.models.rol import Rol
from app.models.sesion import Sesion
from app.models.usuario import HistorialAcceso, ResultadoAcceso, Usuario

__all__ = [
    "Base",
    "Auditoria",
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
]
