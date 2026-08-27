/**
 * Flujo de carga de compra a proveedor.
 *
 * Una sola pantalla: cabecera (proveedor, punto de venta, fecha, notas) →
 * búsqueda de productos → tabla de ítems → cierre. Todo se guarda como
 * borrador en el servidor; el operador puede cerrar el navegador y retomar.
 */
function flujoCompra({ compraId = null, estadoInicial = 'borrador' } = {}) {
    return {
        /* --- Catálogos --- */
        proveedores: [],
        puntos: [],
        categorias: [],

        /* --- Cabecera --- */
        proveedor_id: '',
        punto_de_venta_id: '',
        fecha_compra: '',
        notas: '',
        /* Nombres resueltos del API (para compras cerradas / solo lectura) */
        _nombreProveedor: '',
        _nombrePunto: '',

        /* --- Estado de la compra --- */
        compraId,
        compraIniciada: !!compraId,
        estado: estadoInicial,
        iniciando: false,
        cerrando: false,
        ultimoGuardado: '',

        /* --- Búsqueda de productos --- */
        busqueda: { texto: '', resultados: [] },

        /* --- Ítems cargados --- */
        items: [],

        /* --- Modal confirmación de precio --- */
        confirmacionPrecio: {
            abierto: false,
            itemId: null,
            descripcion: '',
            anterior: '',
            nuevo: '',
            porcentaje: '',
        },

        /* --- Modal confirmación de cierre --- */
        confirmacionCierre: { abierto: false },

        /* --- Modal confirmación genérica (quitar item, eliminar borrador) --- */
        confirmacion: {
            abierta: false, titulo: '', mensaje: '',
            _cb: null,
            accion() { if (this._cb) this._cb(); this.abierta = false; },
        },

        /* --- Trigger para el form compartido de producto nuevo --- */
        abrirFormProducto: false,

        /* --- Variantes (al crear producto con variantes) --- */
        productoParaVariantes: null,
        variante: {
            abierto: false, guardando: false,
            reemplazaBase: false,
            sufijo: '', descripcion_sufijo: '',
            sku_proveedor: '', ubicacion_deposito: '',
            stock_inicial: '',
        },

        /* ================================================================
           Init
           ================================================================ */

        async init() {
            await this.cargarCatalogos();

            if (this.compraId) {
                await this.cargarCompra();
            }
        },

        async cargarCatalogos() {
            const [rProv, rPtos, rCats] = await Promise.all([
                fetch('/api/v1/proveedores?tamano=200', { credentials: 'same-origin' }),
                fetch('/api/v1/stock/ubicaciones', { credentials: 'same-origin' }),
                fetch('/api/v1/categorias', { credentials: 'same-origin' }),
            ]);
            if (rProv.ok) {
                const d = await rProv.json();
                this.proveedores = (d.resultados || d).filter((p) => p.estado === 'activo');
            }
            if (rPtos.ok) {
                this.puntos = await rPtos.json();
                // En compra nueva, preseleccionar el Centro de Distribución.
                if (!this.compraId && !this.punto_de_venta_id) {
                    const cd = this.puntos.find((p) => p.tipo === 'cd');
                    if (cd) this.punto_de_venta_id = cd.id;
                }
            }
            if (rCats.ok) this.categorias = await rCats.json();
        },

        async cargarCompra() {
            try {
                const resp = await fetch(`/api/v1/compras/${this.compraId}`, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo cargar la compra');
                const data = await resp.json();

                this.proveedor_id = data.proveedor?.id || '';
                this.punto_de_venta_id = data.punto_de_venta?.id || '';
                this.fecha_compra = data.fecha_compra || '';
                this.notas = data.notas || '';
                this._nombreProveedor = data.proveedor?.nombre || '';
                this._nombrePunto = data.punto_de_venta?.nombre || '';
                this.items = data.items || [];
                this.estado = data.estado || 'borrador';
                this.compraIniciada = true;
                this.ultimoGuardado = new Date(data.updated_at).toLocaleTimeString('es-AR', {
                    hour: '2-digit', minute: '2-digit',
                });
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        /* ================================================================
           Helpers
           ================================================================ */

        nombreProveedor() {
            if (!this.proveedor_id) return '';
            const p = this.proveedores.find((x) => x.id === Number(this.proveedor_id));
            return p ? p.nombre : this._nombreProveedor;
        },

        nombrePunto() {
            if (!this.punto_de_venta_id) return '';
            const p = this.puntos.find((x) => x.id === Number(this.punto_de_venta_id));
            return p ? p.nombre : this._nombrePunto;
        },

        onProveedorCambiado() {
            // Limpiar resultados de búsqueda al cambiar proveedor.
            this.busqueda.texto = '';
            this.busqueda.resultados = [];
        },

        /* ================================================================
           Iniciar compra
           ================================================================ */

        async iniciarCompra() {
            if (!this.proveedor_id || !this.punto_de_venta_id) return;
            this.iniciando = true;
            try {
                const resp = await fetch('/api/v1/compras', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        proveedor_id: Number(this.proveedor_id),
                        punto_de_venta_id: Number(this.punto_de_venta_id),
                        fecha_compra: this.fecha_compra || null,
                        notas: this.notas || null,
                    }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo iniciar la compra');
                }
                const data = await resp.json();
                // Redirigir a la URL con id para que se pueda retomar.
                window.location = `/compras/${data.id}`;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.iniciando = false;
            }
        },

        /* ================================================================
           Búsqueda de productos
           ================================================================ */

        async buscarProductos() {
            const texto = (this.busqueda.texto || '').trim();
            if (texto.length < 2) {
                this.busqueda.resultados = [];
                return;
            }
            try {
                const params = new URLSearchParams({
                    busqueda: texto,
                    proveedor_id: this.proveedor_id,
                    tamano: '10',
                });
                const resp = await fetch(`/api/v1/productos/variantes?${params}`, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) return;
                const data = await resp.json();
                this.busqueda.resultados = data.resultados || [];
            } catch {
                // Silencioso: no bloquear la carga.
            }
        },

        /* ================================================================
           Ítems
           ================================================================ */

        async agregarDesdeResultado(variante) {
            this.busqueda.resultados = [];
            this.busqueda.texto = '';

            try {
                const precioUsd = variante.producto?.precio_usd || variante.precio_usd || '0';
                const resp = await fetch(`/api/v1/compras/${this.compraId}/items`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        variante_id: variante.id,
                        cantidad: 1,
                        precio_usd: Number(precioUsd),
                    }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo agregar el producto');
                }
                const item = await resp.json();
                this._actualizarOAgregarItem(item);
                this._marcarGuardado();

                if (item.requiere_confirmacion_precio) {
                    this._abrirConfirmacionPrecio(item);
                }
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        async actualizarItem(item) {
            try {
                const resp = await fetch(
                    `/api/v1/compras/${this.compraId}/items/${item.id}`,
                    {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify({
                            cantidad: Number(item.cantidad) || 1,
                            precio_usd: Number(item.precio_usd_nuevo) || null,
                        }),
                    }
                );
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo actualizar');
                }
                const actualizado = await resp.json();
                this._actualizarOAgregarItem(actualizado);
                this._marcarGuardado();

                if (actualizado.requiere_confirmacion_precio) {
                    this._abrirConfirmacionPrecio(actualizado);
                }
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        quitarItem(item) {
            this.confirmacion.titulo = 'Quitar producto';
            this.confirmacion.mensaje = '¿Quitar este producto de la compra?';
            this.confirmacion._cb = async () => {
                try {
                    const resp = await fetch(
                        `/api/v1/compras/${this.compraId}/items/${item.id}`,
                        { method: 'DELETE', credentials: 'same-origin' }
                    );
                    if (!resp.ok) {
                        const err = await resp.json().catch(() => ({}));
                        throw new Error(err.detail || 'No se pudo quitar');
                    }
                    this.items = this.items.filter((i) => i.id !== item.id);
                    this._marcarGuardado();
                } catch (e) {
                    window.toast(e.message, 'error');
                }
            };
            this.confirmacion.abierta = true;
        },

        /* ================================================================
           Confirmación de precio (>30%)
           ================================================================ */

        _abrirConfirmacionPrecio(item) {
            const anterior = Number(item.precio_usd_anterior) || 0;
            const nuevo = Number(item.precio_usd_nuevo);
            const diff = anterior > 0 ? Math.abs(((nuevo - anterior) / anterior) * 100) : 0;

            const desc = item.variante?.producto?.descripcion || '';
            const sufijo = item.variante?.descripcion_sufijo;
            this.confirmacionPrecio = {
                abierto: true,
                itemId: item.id,
                descripcion: desc + (sufijo ? ' — ' + sufijo : ''),
                anterior: anterior.toFixed(2),
                nuevo: nuevo.toFixed(2),
                porcentaje: diff.toFixed(0),
            };
        },

        async resolverPrecio(confirmar) {
            const itemId = this.confirmacionPrecio.itemId;
            this.confirmacionPrecio.abierto = false;
            try {
                const resp = await fetch(
                    `/api/v1/compras/${this.compraId}/items/${itemId}/confirmar-precio`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify({ confirmar }),
                    }
                );
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'Error al confirmar precio');
                }
                const actualizado = await resp.json();
                this._actualizarOAgregarItem(actualizado);
                this._marcarGuardado();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        /* ================================================================
           Cierre
           ================================================================ */

        confirmarCierre() {
            this.confirmacionCierre.abierto = true;
        },

        async cerrarCompra() {
            this.cerrando = true;
            this.confirmacionCierre.abierto = false;
            try {
                const resp = await fetch(`/api/v1/compras/${this.compraId}/cerrar`, {
                    method: 'POST',
                    credentials: 'same-origin',
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo cerrar la compra');
                }
                window.toast('Compra cerrada correctamente', 'exito');
                window.location = '/compras';
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cerrando = false;
            }
        },

        /* ================================================================
           Eliminar borrador
           ================================================================ */

        confirmarEliminarBorrador() {
            this.confirmacion.titulo = 'Eliminar borrador';
            this.confirmacion.mensaje = '¿Eliminar el borrador? Esta acción no se puede deshacer.';
            this.confirmacion._cb = async () => {
                try {
                    const resp = await fetch(`/api/v1/compras/${this.compraId}`, {
                        method: 'DELETE',
                        credentials: 'same-origin',
                    });
                    if (!resp.ok) {
                        const err = await resp.json().catch(() => ({}));
                        throw new Error(err.detail || 'No se pudo eliminar');
                    }
                    window.toast('Borrador eliminado', 'exito');
                    window.location = '/compras';
                } catch (e) {
                    window.toast(e.message, 'error');
                }
            };
            this.confirmacion.abierta = true;
        },

        /* ================================================================
           Variantes (crear producto con variantes desde la compra)
           ================================================================ */

        async abrirVarianteCompra(producto) {
            // Re-leer el producto completo para tener las variantes actuales.
            try {
                const resp = await fetch(`/api/v1/productos/${producto.id}`, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error();
                this.productoParaVariantes = await resp.json();
            } catch {
                this.productoParaVariantes = producto;
            }
            const variantes = this.productoParaVariantes.variantes || [];
            this.variante = {
                abierto: true, guardando: false,
                reemplazaBase: variantes.some((v) => v.es_base),
                sufijo: '', descripcion_sufijo: '',
                sku_proveedor: '', ubicacion_deposito: '',
                stock_inicial: '',
            };
        },

        sufijosUsados() {
            return (this.productoParaVariantes?.variantes || [])
                .filter((v) => !v.es_base)
                .map((v) => v.sufijo);
        },

        codigoPrevisto() {
            const sufijo = (this.variante.sufijo || '').toUpperCase();
            if (!sufijo) return '';
            const alguna = (this.productoParaVariantes?.variantes || [])[0];
            if (!alguna) return '';
            const base = alguna.es_base
                ? alguna.codigo_completo
                : alguna.codigo_completo.slice(0, -1);
            return base + sufijo;
        },

        async guardarVarianteCompra() {
            const sufijo = (this.variante.sufijo || '').trim().toUpperCase();
            if (!sufijo) return;

            this.variante.guardando = true;
            try {
                const productoId = this.productoParaVariantes.id;

                // 1. Crear la variante.
                const resp = await fetch(
                    `/api/v1/productos/${productoId}/variantes`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify({
                            sufijo,
                            descripcion_sufijo: this.variante.descripcion_sufijo,
                            sku_proveedor: this.variante.sku_proveedor || null,
                            ubicacion_deposito: this.variante.ubicacion_deposito || null,
                            stock_inicial: this.variante.stock_inicial
                                ? Number(this.variante.stock_inicial) : null,
                        }),
                    }
                );
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo agregar la variante');
                }
                const nuevaVariante = await resp.json();

                // 2. Agregar la variante como ítem de la compra.
                const respItem = await fetch(
                    `/api/v1/compras/${this.compraId}/items`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify({
                            variante_id: nuevaVariante.id,
                            cantidad: 1,
                            precio_usd: Number(this.productoParaVariantes.precio_usd),
                            es_producto_nuevo: true,
                        }),
                    }
                );
                if (respItem.ok) {
                    const item = await respItem.json();
                    this._actualizarOAgregarItem(item);
                    this._marcarGuardado();
                }

                window.toast('Variante agregada a la compra', 'exito');

                // 3. Re-leer el producto para ver las variantes actualizadas.
                const respProd = await fetch(`/api/v1/productos/${productoId}`, {
                    credentials: 'same-origin',
                });
                if (respProd.ok) this.productoParaVariantes = await respProd.json();

                // Resetear el formulario para la siguiente variante.
                const variantes = this.productoParaVariantes?.variantes || [];
                this.variante = {
                    abierto: true, guardando: false,
                    reemplazaBase: variantes.some((v) => v.es_base),
                    sufijo: '', descripcion_sufijo: '',
                    sku_proveedor: '', ubicacion_deposito: '',
                    stock_inicial: '',
                };
            } catch (e) {
                window.toast(e.message, 'error');
                this.variante.guardando = false;
            }
        },

        /* ================================================================
           Internos
           ================================================================ */

        _actualizarOAgregarItem(item) {
            const idx = this.items.findIndex((i) => i.id === item.id);
            if (idx >= 0) {
                this.items[idx] = item;
            } else {
                this.items.push(item);
            }
        },

        _marcarGuardado() {
            this.ultimoGuardado = new Date().toLocaleTimeString('es-AR', {
                hour: '2-digit', minute: '2-digit',
            });
        },
    };
}
