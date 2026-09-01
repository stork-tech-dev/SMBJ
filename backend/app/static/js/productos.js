/* ==========================================================================
   ABM de productos.

   El precio en pesos no se calcula acá: lo manda el backend ya resuelto
   con el dólar del proveedor (está desnormalizado en la tabla). El
   frontend solo le da formato — la API devuelve números crudos
   (Principio 1).

   El filtrado y la paginación también son del backend (Principio 5).

   El formulario de alta/edición vive en producto_form.js (componente
   Alpine anidado `productoForm()`): se comparte con /compras.
   ========================================================================== */

function abmProductos() {
    return {
        // Filas del listado. Son VARIANTES, no productos: un producto con
        // tres variantes ocupa tres filas, porque cada una tiene su stock y
        // su etiqueta.
        variantes: [],
        categorias: [],
        proveedores: [],
        total: 0,
        cargando: false,

        // Diálogo de confirmación de las acciones destructivas.
        confirmacion: { abierta: false, titulo: '', mensaje: '', accion: () => {} },

        // Un solo campo de texto que resuelve las tres formas de nombrar un
        // artículo: el código de la etiqueta, el SKU o parte de la
        // descripción. Lo desambigua el backend (ver `listar_variantes`).
        filtros: {
            busqueda: '', categoria_id: '', proveedor_id: '', temporada: '',
            // 'true' = activos, 'false' = inactivos. Siempre filtra por
            // un estado; no existe "todos". Es string para que entre sin
            // cambios en el bucle que arma los query params.
            activo: 'true',
        },

        pagina: 1,
        tamano: 10,

        // Filtro "Stock 0": muestra solo variantes con stock = 0 y habilita
        // checkboxes para selección y desactivación masiva.
        stockCero: false,
        seleccion: [],

        // `varianteId` acota el panel al código desde el que se abrió; en
        // null muestra todas las variantes del producto.
        detalle: { abierto: false, producto: null, varianteId: null },

        // Alta de variante. `reemplazaBase` se resuelve al abrir el modal y
        // sirve para avisar ANTES de confirmar que el código de la BASE va a
        // desaparecer: si ya se imprimió esa etiqueta, queda sin respaldo y
        // el sistema no tiene forma de saberlo.
        variante: {
            abierto: false, guardando: false, reemplazaBase: false,
            sufijo: '', descripcion_sufijo: '', sku_proveedor: '',
            ubicacion_deposito: '', stock_inicial: '',
        },

        // Edición de una variante ya creada. El sufijo NO está: entra en el
        // código, que se congela porque la etiqueta ya se imprimió.
        edicionVariante: {
            abierto: false, guardando: false, id: null, codigo: '', proveedorId: null,
            descripcion_sufijo: '', sku_proveedor: '', ubicacion_deposito: '',
            precio_usd: '',
        },

        // Precio en pesos que resultaría del USD tipeado en el modal de
        // variante. Lo calcula el backend, igual que el del producto.
        previewVar: { precio_venta: null },

        // Triggers para el componente hijo `productoForm()`. El padre pone
        // el flag en true (alta) o le pasa el producto (edición); el hijo
        // reacciona con un `x-effect` y lo resetea.
        _abrirFormAlta: false,
        _productoEditar: null,

        /* --- Formato: la API manda números, no strings con símbolo --- */

        // Delega en `window.pesos` (app.js), donde vive el porqué del
        // formato. La misma función la usan el carrito, el cobro y el
        // listado de ventas: dos copias que puedan divergir mostrarían el
        // mismo precio de dos formas distintas (Principio 2).
        pesos: (valor) => window.pesos(valor),

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

            const ids = this.rutaDeIds(categoria.id);
            if (!ids.length) return categoria.nombre || '—';

            const porId = new Map(this.categorias.map((c) => [c.id, c]));
            return ids.map((id) => porId.get(id).nombre).join(' - ');
        },

        /**
         * Los ids desde la raíz hasta la categoría dada, ella incluida.
         *
         * Es el mismo recorrido hacia arriba que necesitan el camino escrito
         * del listado y la cascada de selects del formulario, escrito una
         * sola vez (Principio 2). Devuelve vacío si la categoría no está en
         * el catálogo cargado.
         */
        rutaDeIds(categoriaId) {
            const porId = new Map(this.categorias.map((c) => [c.id, c]));
            const ids = [];

            let actual = porId.get(Number(categoriaId));
            // El árbol tiene 5 niveles como máximo; el tope corta igual por
            // si un dato quedara inconsistente.
            for (let i = 0; i < 5 && actual; i++) {
                ids.unshift(actual.id);
                actual = actual.parent_id ? porId.get(actual.parent_id) : null;
            }
            return ids;
        },

        /* --- Carga --- */

        async cargar() {
            this.cargando = true;
            this.seleccion = [];
            try {
                const params = new URLSearchParams();
                for (const [clave, valor] of Object.entries(this.filtros)) {
                    if (valor !== '' && valor !== null) params.set(clave, valor);
                }
                if (this.stockCero) params.set('stock_cero', 'true');
                params.set('pagina', this.pagina);
                params.set('tamano', this.tamano);

                // Listado a nivel VARIANTE: cada fila es lo que tiene stock y
                // lo que dice una etiqueta. `/productos` sigue existiendo para
                // el detalle y el formulario, que trabajan sobre el producto.
                const resp = await fetch('/api/v1/productos/variantes?' + params, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo cargar el listado');

                const datos = await resp.json();
                this.variantes = datos.resultados;
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
            // 'Limpiar filtros' vuelve al estado de entrada, que incluye
            // el switch en Activo: limpiar no es 'mostrar todo'.
            this.filtros = {
                busqueda: '', categoria_id: '', proveedor_id: '', temporada: '',
                activo: 'true',
            };
            this.stockCero = false;
            this.pagina = 1;
            this.cargar();
        },

        /* --- Detalle --- */

        /**
         * La fila trae un resumen del producto, no el producto entero: le
         * faltan `variantes` y `fotos`, que son lo que muestra el panel. Se
         * pide el detalle completo en vez de engordar cada fila del listado
         * con las variantes hermanas y las fotos de todas.
         *
         * `varianteId` acota el panel a la fila desde la que se abrió: se
         * hizo clic en un código concreto, así que mostrar también sus
         * hermanas obliga a buscar de nuevo cuál era. En null (al agregar
         * una variante) se muestran todas.
         */
        async abrirProducto(productoId, { editar = false, varianteId = null } = {}) {
            try {
                const resp = await fetch('/api/v1/productos/' + productoId, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo abrir el producto');
                const producto = await resp.json();

                if (editar) this._productoEditar = producto;
                else this.detalle = { abierto: true, producto, varianteId };
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        /**
         * Variantes que muestra el panel: la elegida, o todas si se entró
         * sin elegir ninguna.
         */
        variantesVisibles() {
            const todas = this.detalle.producto?.variantes || [];
            if (!this.detalle.varianteId) return todas;
            return todas.filter((v) => v.id === this.detalle.varianteId);
        },

        /** Cuántas hermanas quedan fuera de la vista, para poder decirlo. */
        variantesOcultas() {
            const todas = this.detalle.producto?.variantes || [];
            return this.detalle.varianteId ? todas.length - 1 : 0;
        },

        /**
         * Fotos que muestra el panel, con fallback:
         * - Si hay una variante seleccionada y tiene fotos propias → esas.
         * - Si no → las fotos del producto (compartidas).
         */
        fotosVisibles() {
            const p = this.detalle.producto;
            if (!p) return [];
            if (this.detalle.varianteId) {
                const v = (p.variantes || []).find(
                    (v) => v.id === this.detalle.varianteId
                );
                if (v?.fotos?.length) return v.fotos;
            }
            return p.fotos || [];
        },

        /**
         * TRUE si las fotos que se muestran son de una variante (no las
         * compartidas del producto). Sirve para que subirFoto sepa si
         * mandar variante_id o no.
         */
        fotosDeVariante() {
            const p = this.detalle.producto;
            if (!p || !this.detalle.varianteId) return false;
            const v = (p.variantes || []).find(
                (v) => v.id === this.detalle.varianteId
            );
            return !!(v?.fotos?.length);
        },

        /* --- Alta de variante --- */

        abrirVariante() {
            const variantes = this.detalle.producto?.variantes || [];
            this.variante = {
                abierto: true,
                guardando: false,
                // La primera variante real reemplaza a la BASE. Si el
                // producto ya tiene variantes, no hay BASE que perder.
                reemplazaBase: variantes.some((v) => v.es_base),
                sufijo: '',
                descripcion_sufijo: '',
                sku_proveedor: '',
                ubicacion_deposito: '',
                stock_inicial: '',
            };
        },

        /** Sufijos ya usados: sirven para avisar antes de que la API rechace. */
        sufijosUsados() {
            return (this.detalle.producto?.variantes || [])
                .filter((v) => !v.es_base)
                .map((v) => v.sufijo);
        },

        /** Cómo va a quedar el código, para verlo antes de confirmar. */
        codigoPrevisto() {
            const sufijo = (this.variante.sufijo || '').toUpperCase();
            if (!sufijo) return '';
            // Se toma el prefijo de una variante existente en vez de armarlo
            // acá: la letra de la empresa la decide el backend y el frontend
            // no tiene por qué conocerla (Principio 1).
            const alguna = (this.detalle.producto?.variantes || [])[0];
            if (!alguna) return '';
            const base = alguna.es_base
                ? alguna.codigo_completo
                : alguna.codigo_completo.slice(0, -1);
            return base + sufijo;
        },

        /* --- Edición de una variante --- */

        abrirEdicionVariante(v) {
            this.edicionVariante = {
                abierto: true,
                guardando: false,
                id: v.id,
                // Solo informativo: el código no se edita.
                codigo: v.codigo_completo + v.verificador,
                proveedorId: this.detalle.producto.proveedor_id,
                descripcion_sufijo: v.descripcion_sufijo || '',
                // Vacío cuando no tiene el suyo: el placeholder dice que en
                // ese caso usa el del producto.
                sku_proveedor: v.sku_proveedor || '',
                ubicacion_deposito: v.ubicacion_deposito || '',
                // Vacío cuando no tiene precio propio: el placeholder dice
                // que en ese caso usa el del producto.
                precio_usd: v.precio_usd ?? '',
            };
            this.previewVariante();
        },

        /** Precio en pesos del USD tipeado, resuelto por el backend. */
        async previewVariante() {
            const usd = Number(this.edicionVariante.precio_usd);
            if (!usd || usd <= 0) {
                this.previewVar = { precio_venta: null };
                return;
            }
            try {
                const params = new URLSearchParams({
                    proveedor_id: this.edicionVariante.proveedorId,
                    precio_usd: this.edicionVariante.precio_usd,
                });
                const resp = await fetch('/api/v1/productos/precio-preview?' + params, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error();
                this.previewVar = await resp.json();
            } catch {
                // Silencioso: es informativo y no puede trabar el formulario.
                this.previewVar = { precio_venta: null };
            }
        },

        async guardarEdicionVariante() {
            const e = this.edicionVariante;
            e.guardando = true;
            try {
                const resp = await fetch('/api/v1/productos/variantes/' + e.id, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        descripcion_sufijo: e.descripcion_sufijo,
                        // null explícito = volver al precio del producto. El
                        // backend distingue esto de "no lo mandes".
                        precio_usd: e.precio_usd === '' ? null : e.precio_usd,
                        // Mismo trato: vaciarlo devuelve la variante al
                        // código de proveedor del producto.
                        sku_proveedor: e.sku_proveedor === '' ? null : e.sku_proveedor,
                        // El backend normaliza; '' sería guardar una ubicación
                        // vacía en vez de ninguna.
                        ubicacion_deposito: e.ubicacion_deposito || null,
                    }),
                });
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo guardar la variante');
                }
                window.toast('Variante actualizada', 'exito');
                e.abierto = false;
                // Se recarga el panel para ver el cambio sin cerrarlo.
                await this.abrirProducto(this.detalle.producto.id,
                                         { varianteId: this.detalle.varianteId });
                this.cargar();
            } catch (err) {
                window.toast(err.message, 'error');
            } finally {
                e.guardando = false;
            }
        },

        async guardarVariante() {
            const sufijo = (this.variante.sufijo || '').trim().toUpperCase();
            if (!sufijo) return;

            this.variante.guardando = true;
            try {
                const resp = await fetch(
                    `/api/v1/productos/${this.detalle.producto.id}/variantes`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify({
                            sufijo,
                            descripcion_sufijo: this.variante.descripcion_sufijo,
                            // Vacío = null = usa el del producto.
                            sku_proveedor: this.variante.sku_proveedor || null,
                            // El backend normaliza el texto; mandar '' sería
                            // guardar una ubicación vacía en vez de ninguna.
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
                window.toast('Variante agregada', 'exito');
                // Se cierra SOLO el formulario: la ficha queda abierta con la
                // variante recién creada a la vista y "Agregar variante" a un
                // clic. Un producto que viene en colores o talles necesita
                // varias seguidas, y cerrando todo había que volver a
                // buscarlo en el listado por cada una.
                this.variante.abierto = false;

                // Se relee sin acotar a ninguna variante por dos motivos: la
                // recién creada tiene que verse —el panel filtrado por un
                // código la escondería—, y si era la primera, el backend
                // acaba de eliminar la BASE que el panel venía mostrando, así
                // que filtrar por ese id dejaría la ficha vacía.
                await this.abrirProducto(this.detalle.producto.id, { varianteId: null });
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.variante.guardando = false;
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

        async tomarFotoDetalle() {
            try {
                const blob = await window.webcamCapture();
                if (!blob) return;

                const cuerpo = new FormData();
                cuerpo.append('archivo', new File([blob], 'captura.jpg', { type: 'image/jpeg' }));

                let url = `/api/v1/productos/${this.detalle.producto.id}/fotos`;
                if (this.detalle.varianteId) {
                    url += `?variante_id=${this.detalle.varianteId}`;
                }

                const resp = await fetch(url, {
                    method: 'POST', credentials: 'same-origin', body: cuerpo,
                });
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo subir la foto');
                }
                window.toast('Foto capturada y subida', 'exito');
                await this.refrescarDetalle();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        async imprimirEtiquetas(varianteId, cantidad, tipo) {
            try {
                const resp = await fetch('/api/v1/productos/etiquetas', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        tipo,
                        items: [{ variante_id: varianteId, cantidad: parseInt(cantidad) || 1 }],
                    }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'Error al generar etiquetas');
                }
                const blob = await resp.blob();
                window.open(URL.createObjectURL(blob), '_blank');
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        async subirFoto(evento) {
            const archivo = evento.target.files?.[0];
            if (!archivo) return;
            // Se limpia el input: sin esto, subir el mismo archivo dos
            // veces seguidas no dispara el change la segunda vez.
            evento.target.value = '';

            const cuerpo = new FormData();
            cuerpo.append('archivo', archivo);

            // Si se está viendo una variante específica, la foto va a esa
            // variante; si no, al producto (compartida).
            let url = `/api/v1/productos/${this.detalle.producto.id}/fotos`;
            if (this.detalle.varianteId) {
                url += `?variante_id=${this.detalle.varianteId}`;
            }

            try {
                const resp = await fetch(
                    url,
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

        /* --- Alta y baja lógica --- */

        /**
         * Pide confirmación antes de cambiar el estado de un producto.
         *
         * La baja se ejecutaba de una: un clic al lado de "Producto" en una
         * tabla donde cada fila es una variante, y el producto entero quedaba
         * desactivado con todas sus variantes. Un error ahí no avisa nada.
         */
        confirmarEstado(producto) {
            const desactivando = producto.activo;
            this.confirmacion = {
                abierta: true,
                titulo: desactivando ? 'Desactivar producto' : 'Activar producto',
                mensaje: desactivando
                    ? `¿Desactivar ${producto.descripcion}? Deja de aparecer para vender, `
                      + 'con todas sus variantes. No se borra: el stock y el historial '
                      + 'se conservan y se puede volver a activar.'
                    : `¿Activar ${producto.descripcion}? Vuelve a estar disponible para vender.`,
                accion: () => this.cambiarEstado(producto, !producto.activo),
            };
        },

        async cambiarEstado(p, activo) {
            this.confirmacion.abierta = false;
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

        /* --- Selección y desactivación masiva (modo Stock 0) --- */

        toggleSeleccion(productoId) {
            const idx = this.seleccion.indexOf(productoId);
            if (idx >= 0) {
                this.seleccion.splice(idx, 1);
            } else {
                this.seleccion.push(productoId);
            }
        },

        estaSeleccionado(productoId) {
            return this.seleccion.includes(productoId);
        },

        /** IDs de producto únicos en la tabla visible. */
        _productosVisibles() {
            const ids = new Set();
            for (const v of this.variantes) ids.add(v.producto_id);
            return [...ids];
        },

        toggleTodos() {
            const todos = this._productosVisibles();
            if (this.seleccion.length === todos.length) {
                this.seleccion = [];
            } else {
                this.seleccion = todos;
            }
        },

        todosSeleccionados() {
            const todos = this._productosVisibles();
            return todos.length > 0 && this.seleccion.length === todos.length;
        },

        desactivarMasivo() {
            const n = this.seleccion.length;
            if (!n) return;
            this.confirmacion = {
                abierta: true,
                titulo: 'Desactivar productos',
                mensaje: `¿Desactivar ${n} producto(s)? Dejan de aparecer para vender `
                       + 'con todas sus variantes. No se borran: el stock y el historial '
                       + 'se conservan y se pueden volver a activar.',
                accion: () => this._ejecutarDesactivacionMasiva(),
            };
        },

        async _ejecutarDesactivacionMasiva() {
            this.confirmacion.abierta = false;
            let ok = 0;
            let errores = 0;
            for (const id of this.seleccion) {
                try {
                    const resp = await fetch(`/api/v1/productos/${id}/estado`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify({ activo: false }),
                    });
                    if (resp.ok) ok++; else errores++;
                } catch {
                    errores++;
                }
            }
            if (errores) {
                window.toast(`${ok} desactivado(s), ${errores} con error`, 'error');
            } else {
                window.toast(`${ok} producto(s) desactivado(s)`, 'exito');
            }
            this.cargar();
        },
    };
}
