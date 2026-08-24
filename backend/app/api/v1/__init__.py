"""
Router agregador de la API v1.

Cada módulo nuevo crea su archivo de router en este paquete y lo
registra acá con `api_router.include_router(...)`. main.py monta
únicamente `api_router`, nunca routers sueltos.
"""

from fastapi import APIRouter

from app.api.v1 import (
    admin_dispositivos,
    auditoria,
    auditoria_inventario,
    auth,
    categorias,
    clientes,
    configuracion_ventas,
    dispositivos,
    health,
    productos,
    proveedores,
    puntos_de_venta,
    remitos,
    roles,
    senas,
    stock,
    usuarios,
    ventas,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(roles.router)
api_router.include_router(usuarios.router)
api_router.include_router(proveedores.router)
api_router.include_router(clientes.router)
api_router.include_router(categorias.router)
api_router.include_router(productos.router)
api_router.include_router(stock.router)
api_router.include_router(remitos.router)
api_router.include_router(auditoria_inventario.router)
api_router.include_router(puntos_de_venta.router)
api_router.include_router(dispositivos.router)
api_router.include_router(admin_dispositivos.router)
api_router.include_router(ventas.router)
api_router.include_router(senas.router)
api_router.include_router(configuracion_ventas.router)
api_router.include_router(auditoria.router)

__all__ = ["api_router"]
