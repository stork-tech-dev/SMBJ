/* ==========================================================================
   ABM de productos.

   El precio en pesos no se calcula acá: lo manda el backend ya resuelto
   con el dólar del proveedor (está desnormalizado en la tabla). El
   frontend solo le da formato — la API devuelve números crudos
   (Principio 1).

   El filtrado y la paginación también son del backend (Principio 5).
   ========================================================================== */

const ESTACIONES = ['permanente', 'verano', 'invierno', 'otoño', 'primavera'];

function abmProductos() {
    return {
        ESTACIONES,

        productos: [],
        categorias: [],
        proveedores: [],
        total: 0,
        cargando: false,

        filtros: {
            descripcion: '', categoria_id: '', proveedor_id: '', estacionalidad: '',
        },

        detalle: { abierto: false, producto: null },

        // Valores informativos del formulario. null = todavía sin datos
        // suficientes (falta el proveedor o el precio).
        preview: { dolar_proveedor: null, precio_venta: null },

        form: {
            abierto: false, guardando: false, id: null, sku: '',
            descripcion: '', categoria_id: '', proveedor_id: '', precio_usd: '',
            sku_proveedor: '', descuento_producto: '', peso_gramos: '',
            estacionalidad: 'permanente', stock_infinito: false,
        },

        /* --- Formato: la API manda números, no strings con símbolo --- */

        /**
         * Importe en pesos, mostrando EXACTAMENTE lo que guarda el backend.
         *
         * Los decimales aparecen solo si existen. La versión anterior usaba
         * `maximumFractionDigits: 0` y aplicaba su propio redondeo
         * half-expand: con el `redondeo` del sistema en 0,50 un precio
         * guardado como 2000,50 se mostraba "$2.001", y uno de 1234,49 se
         * mostraba "$1.234" — menos de lo que se cobra. El redondeo del
         * precio es CEIL y lo hace el backend; la pantalla no puede volver
         * a redondear por su cuenta.
         *
         * Hoy el redondeo configurado es 1000, así que los precios no
         * tienen decimales y el defecto no se veía. Depende de un valor de
         * configuración, no de una garantía.
         */
        pesos(valor) {
            if (valor === null || valor === undefined) return '—';
            const n = Number(valor);
            const decimales = Number.isInteger(n) ? 0 : 2;
            return n.toLocaleString('es-AR', {
                style: 'currency',
                currency: 'ARS',
                minimumFractionDigits: decimales,
                maximumFractionDigits: decimales,
            });
        },

        usd(valor) {
            if (valor === null || valor === undefined) return '—';
            return Number(valor).toLocaleString('es-AR', {
                style: 'currency', currency: 'USD',
            });
        },

        /* --- Categorías --- */

        /**
         * Camino completo de una categoría: "Calzado - Zapatillas - Deportivas".
         *
         * Se arma acá y no en la API porque `categorias` ya está cargado en
         * memoria con el `parent_id` de cada nodo: recorrer hacia arriba no
         * cuesta ninguna consulta, mientras que pedirle la ruta al backend
         * por cada fila del listado sería un N+1. Además el separador es
         * presentación, y la API devuelve datos crudos (Principio 1).
         *
         * Si el catálogo todavía no llegó, devuelve el nombre suelto; al
         * llegar, Alpine vuelve a renderizar con la ruta completa.
         */
        rutaCategoria(categoria) {
            if (!categoria) return '—';

            const porId = new Map(this.categorias.map((c) => [c.id, c]));
            const tramos = [];

            let actual = porId.get(categoria.id);
            if (!actual) return categoria.nombre || '—';

            // El árbol tiene 5 niveles como máximo; el tope corta igual por
            // si un dato quedara inconsistente.
            for (let i = 0; i < 5 && actual; i++) {
                tramos.unshift(actual.nombre);
                actual = actual.parent_id ? porId.get(actual.parent_id) : null;
            }
            return tramos.join(' - ');
        },

        /* --- Carga --- */

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams();
                for (const [clave, valor] of Object.entries(this.filtros)) {
                    if (valor !== '' && valor !== null) params.set(clave, valor);
                }

                const resp = await fetch('/api/v1/productos?' + params, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo cargar el listado');

                const datos = await resp.json();
                this.productos = datos.resultados;
                this.total = datos.total;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        /** Categorías y proveedores para los selectores de filtro y del form. */
        async cargarCatalogos() {
            const [cats, provs] = await Promise.all([
                fetch('/api/v1/categorias', { credentials: 'same-origin' }),
                fetch('/api/v1/proveedores', { credentials: 'same-origin' }),
            ]);
            if (cats.ok) this.categorias = await cats.json();
            if (provs.ok) {
                // Solo los activos: el backend rechaza cargar un producto
                // de un proveedor dado de baja.
                this.proveedores = (await provs.json()).filter((p) => p.estado === 'activo');
            }
        },

        limpiar() {
            this.filtros = {
                descripcion: '', categoria_id: '', proveedor_id: '', estacionalidad: '',
            };
            this.cargar();
        },

        /* --- Detalle --- */

        abrirDetalle(p) {
            this.detalle = { abierto: true, producto: p };
        },

        async abrirVariante() {
            const sufijo = window.prompt('Sufijo de la variante (un carácter):');
            if (!sufijo) return;

            try {
                const resp = await fetch(
                    `/api/v1/productos/${this.detalle.producto.id}/variantes`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify({ sufijo: sufijo.toUpperCase() }),
                    }
                );
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo agregar la variante');
                }
                window.toast('Variante agregada', 'exito');
                this.detalle.abierto = false;
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        /* --- Vista previa del precio --- */

        /**
         * Pide al backend el dólar del proveedor y el precio en pesos.
         *
         * No se calcula acá a propósito: el múltiplo de redondeo vive en
         * configuracion_sistema y la fórmula usa CEIL. Replicarla en JS
         * haría que la vista previa dejara de coincidir con lo que se
         * guarda apenas cambie la configuración (Principio 2).
         */
        async calcularPreview() {
            const proveedor = Number(this.form.proveedor_id);
            const usd = Number(this.form.precio_usd);

            if (!proveedor || !usd || usd <= 0) {
                this.preview = { dolar_proveedor: null, precio_venta: null };
                return;
            }

            try {
                const params = new URLSearchParams({
                    proveedor_id: proveedor,
                    precio_usd: this.form.precio_usd,
                });
                const resp = await fetch('/api/v1/productos/precio-preview?' + params, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error();
                this.preview = await resp.json();
            } catch {
                // Silencioso: es informativo y no puede trabar la carga.
                this.preview = { dolar_proveedor: null, precio_venta: null };
            }
        },

        /* --- Fotos --- */

        /**
         * Refresca el producto abierto en el panel.
         *
         * Tras subir o borrar una foto hace falta releer el producto: el
         * objeto del panel es el del listado, y su lista de fotos quedó
         * vieja. Se recarga el listado además, para que la miniatura del
         * producto también se actualice.
         */
        async refrescarDetalle() {
            const resp = await fetch('/api/v1/productos/' + this.detalle.producto.id, {
                credentials: 'same-origin',
            });
            if (resp.ok) this.detalle.producto = await resp.json();
            this.cargar();
        },

        async subirFoto(evento) {
            const archivo = evento.target.files?.[0];
            if (!archivo) return;
            // Se limpia el input: sin esto, subir el mismo archivo dos
            // veces seguidas no dispara el change la segunda vez.
            evento.target.value = '';

            const cuerpo = new FormData();
            cuerpo.append('archivo', archivo);

            try {
                const resp = await fetch(
                    `/api/v1/productos/${this.detalle.producto.id}/fotos`,
                    { method: 'POST', credentials: 'same-origin', body: cuerpo }
                );
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo subir la foto');
                }
                window.toast('Foto subida', 'exito');
                await this.refrescarDetalle();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        async marcarPrincipal(foto) {
            try {
                const resp = await fetch(`/api/v1/productos/fotos/${foto.id}/principal`, {
                    method: 'PATCH',
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo marcar como principal');
                await this.refrescarDetalle();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        async borrarFoto(foto) {
            try {
                const resp = await fetch(`/api/v1/productos/fotos/${foto.id}`, {
                    method: 'DELETE',
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo eliminar la foto');
                window.toast('Foto eliminada', 'exito');
                await this.refrescarDetalle();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        /* --- Alta y edición --- */

        abrirAlta() {
            this.form = {
                abierto: true, guardando: false, id: null, sku: '',
                descripcion: '', categoria_id: '', proveedor_id: '', precio_usd: '',
                sku_proveedor: '', descuento_producto: '', peso_gramos: '',
                estacionalidad: 'permanente', stock_infinito: false,
            };
            this.preview = { dolar_proveedor: null, precio_venta: null };
        },

        abrirEdicion(p) {
            this.form = {
                abierto: true, guardando: false, id: p.id, sku: p.sku,
                descripcion: p.descripcion || '',
                categoria_id: p.categoria_id,
                proveedor_id: p.proveedor_id,
                precio_usd: p.precio_usd,
                sku_proveedor: p.sku_proveedor || '',
                descuento_producto: p.descuento_producto,
                peso_gramos: p.peso_gramos || '',
                estacionalidad: p.estacionalidad,
                stock_infinito: p.stock_infinito,
            };
            // En edición ya hay proveedor y precio: se muestra de entrada.
            this.calcularPreview();
        },

        async guardar() {
            this.form.guardando = true;
            try {
                const alta = !this.form.id;
                const cuerpo = {
                    categoria_id: Number(this.form.categoria_id),
                    descripcion: this.form.descripcion || null,
                    precio_usd: this.form.precio_usd,
                    sku_proveedor: this.form.sku_proveedor || null,
                    descuento_producto: this.form.descuento_producto || null,
                    peso_gramos: this.form.peso_gramos || null,
                    estacionalidad: this.form.estacionalidad,
                    stock_infinito: this.form.stock_infinito,
                };
                // El SKU y el precio de venta los genera el backend; el
                // proveedor solo se define en el alta.
                if (alta) cuerpo.proveedor_id = Number(this.form.proveedor_id);

                const resp = await fetch(
                    alta ? '/api/v1/productos' : '/api/v1/productos/' + this.form.id,
                    {
                        method: alta ? 'POST' : 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify(cuerpo),
                    }
                );

                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo guardar el producto');
                }

                const guardado = await resp.json();
                this.form.abierto = false;
                window.toast(
                    alta ? `Producto creado con SKU ${guardado.sku}` : 'Producto actualizado',
                    'exito'
                );
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.form.guardando = false;
            }
        },

        /* --- Alta y baja lógica --- */

        async cambiarEstado(p, activo) {
            try {
                const resp = await fetch(`/api/v1/productos/${p.id}/estado`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ activo }),
                });
                if (!resp.ok) throw new Error('No se pudo cambiar el estado');

                window.toast(activo ? 'Producto activado' : 'Producto desactivado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },
    };
}
