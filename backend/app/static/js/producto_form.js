/**
 * Formulario compartido de alta y edición de producto.
 *
 * Se usa como componente Alpine anidado (`x-data="productoForm({…})"`)
 * tanto en /productos como en /compras. El componente accede a `categorias`
 * y `proveedores` del componente padre a través de la cadena de scope de
 * Alpine (no los define él).
 *
 * Parámetros de configuración:
 *   proveedorFijo  — id numérico si el proveedor no se puede cambiar (compras)
 *   alGuardar      — callback(producto, { alta, conVariantes }) tras guardar
 */

const TEMPORADAS = [
    { id: 'atemporal', etiqueta: 'Atemporal' },
    { id: 'otoño_invierno', etiqueta: 'Otoño-Invierno' },
    { id: 'primavera_verano', etiqueta: 'Primavera-Verano' },
];

// Umbral de caracteres para buscar productos parecidos. El mismo valor lo
// aplica el backend (`MINIMO_CARACTERES_SIMILARES` en services/productos.py).
const MINIMO_SIMILARES = 10;

/**
 * Texto comparable: sin mayúsculas, sin tildes y sin espacios de más.
 * Replica la normalización del backend para avisar antes del alta.
 */
function textoPlano(valor) {
    return (valor || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .split(/\s+/)
        .filter(Boolean)
        .join(' ');
}

function productoForm({ proveedorFijo = null, alGuardar = null } = {}) {
    return {
        TEMPORADAS,
        proveedorFijo,

        /* --- Estado del formulario --- */

        form: {
            abierto: false, guardando: false, id: null, sku: '',
            descripcion: '', categoria_id: '', proveedor_id: '',
            precio_usd: '', sku_proveedor: '', descuento_producto: '',
            peso_gramos: '', temporada: 'atemporal', stock_infinito: false,
            categoriaRuta: [],
            foto: { archivo: null, previo: '' },
            stock_inicial: '',
        },

        // Valores informativos calculados por el backend.
        preview: { dolar_proveedor: null, precio_venta: null },

        // Productos con descripción parecida.
        similares: { abierto: false, buscando: false, lista: [], resaltado: -1 },
        similaresToken: 0,

        /* --- Formato --- */

        pesos(valor) {
            if (valor === null || valor === undefined) return '—';
            const n = Number(valor);
            const decimales = Number.isInteger(n) ? 0 : 2;
            return n.toLocaleString('es-AR', {
                style: 'currency', currency: 'ARS',
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

        /* --- Categoría en cascada --- */

        rutaDeIds(categoriaId) {
            const porId = new Map(this.categorias.map((c) => [c.id, c]));
            const ids = [];
            let actual = porId.get(Number(categoriaId));
            for (let i = 0; i < 5 && actual; i++) {
                ids.unshift(actual.id);
                actual = actual.parent_id ? porId.get(actual.parent_id) : null;
            }
            return ids;
        },

        opcionesCategoria(nivel) {
            if (nivel === 1) return this.categorias.filter((c) => !c.parent_id);
            const padre = this.form.categoriaRuta[nivel - 2];
            if (!padre) return [];
            return this.categorias.filter((c) => c.parent_id === Number(padre));
        },

        nivelCategoriaVisible(nivel) {
            if (nivel === 1) return true;
            if (!this.form.categoriaRuta[nivel - 2]) return false;
            return this.opcionesCategoria(nivel).length > 0;
        },

        nivelesCategoriaVisibles() {
            let visibles = 0;
            for (let nivel = 1; nivel <= 5; nivel++) {
                if (this.nivelCategoriaVisible(nivel)) visibles++;
            }
            return visibles;
        },

        elegirCategoria(nivel) {
            const elegido = this.form.categoriaRuta[nivel - 1];
            this.form.categoriaRuta = this.form.categoriaRuta.slice(0, nivel);
            this.form.categoria_id = elegido || '';
            this.buscarSimilares();
        },

        categoriaCompleta() {
            const ruta = this.form.categoriaRuta;
            if (!ruta.length || !ruta[ruta.length - 1]) return false;
            return this.opcionesCategoria(ruta.length + 1).length === 0;
        },

        /* --- Descripciones parecidas --- */

        async buscarSimilares() {
            const texto = (this.form.descripcion || '').trim();
            if (this.form.id || texto.length < MINIMO_SIMILARES) {
                this.cerrarSimilares();
                return;
            }

            const token = ++this.similaresToken;
            this.similares.buscando = true;
            try {
                const params = new URLSearchParams({ descripcion: texto });
                if (this.form.categoria_id) params.set('categoria_id', this.form.categoria_id);
                if (this.form.proveedor_id) params.set('proveedor_id', this.form.proveedor_id);

                const resp = await fetch('/api/v1/productos/similares?' + params, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error();
                const lista = await resp.json();

                if (token !== this.similaresToken) return;
                this.similares.lista = lista;
                this.similares.abierto = lista.length > 0;
                this.similares.resaltado = -1;
            } catch {
                if (token === this.similaresToken) this.cerrarSimilares();
            } finally {
                if (token === this.similaresToken) this.similares.buscando = false;
            }
        },

        cerrarSimilares() {
            this.similares = { abierto: false, buscando: false, lista: [], resaltado: -1 };
        },

        moverSimilar(paso) {
            if (!this.similares.abierto || !this.similares.lista.length) return;
            const ultimo = this.similares.lista.length - 1;
            const siguiente = this.similares.resaltado + paso;
            if (siguiente < 0) this.similares.resaltado = ultimo;
            else if (siguiente > ultimo) this.similares.resaltado = 0;
            else this.similares.resaltado = siguiente;
        },

        elegirSimilar(p) {
            if (!p) return;
            this.form.descripcion = p.descripcion;
            this.similares.abierto = false;
            this.similares.resaltado = -1;
        },

        duplicadoExacto() {
            if (this.form.id || !this.form.categoria_id || !this.form.proveedor_id) {
                return null;
            }
            const texto = textoPlano(this.form.descripcion);
            if (!texto) return null;
            return this.similares.lista.find((p) => textoPlano(p.descripcion) === texto) || null;
        },

        /* --- Preview de precio --- */

        async calcularPreview() {
            const proveedor = Number(this.form.proveedor_id);
            const usdVal = Number(this.form.precio_usd);

            if (!proveedor || !usdVal || usdVal <= 0) {
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
                this.preview = { dolar_proveedor: null, precio_venta: null };
            }
        },

        /* --- Foto del alta --- */

        elegirFoto(evento) {
            const archivo = evento.target.files?.[0];
            evento.target.value = '';
            if (!archivo) return;

            this.quitarFoto();
            this.form.foto = { archivo, previo: URL.createObjectURL(archivo) };
        },

        async tomarFoto() {
            try {
                const blob = await window.webcamCapture();
                if (!blob) return;
                const archivo = new File([blob], 'captura.jpg', { type: 'image/jpeg' });
                this.quitarFoto();
                this.form.foto = { archivo, previo: URL.createObjectURL(archivo) };
            } catch (e) {
                window.toast('No se pudo acceder a la cámara', 'error');
            }
        },

        quitarFoto() {
            if (this.form.foto?.previo) URL.revokeObjectURL(this.form.foto.previo);
            this.form.foto = { archivo: null, previo: '' };
        },

        async subirFotoDelAlta(productoId) {
            const archivo = this.form.foto?.archivo;
            if (!archivo) return true;

            const cuerpo = new FormData();
            cuerpo.append('archivo', archivo);

            try {
                const resp = await fetch(`/api/v1/productos/${productoId}/fotos`, {
                    method: 'POST', credentials: 'same-origin', body: cuerpo,
                });
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo subir la foto');
                }
                return true;
            } catch (e) {
                window.toast(
                    `El producto se creó, pero la foto no se subió: ${e.message}. `
                    + 'Se puede cargar desde la ficha.',
                    'error'
                );
                return false;
            }
        },

        /* --- Nombre del proveedor para el formulario --- */

        nombreProveedorForm() {
            const id = Number(this.form.proveedor_id);
            return this.proveedores.find((p) => p.id === id)?.nombre || '—';
        },

        /* --- Ciclo de vida --- */

        abrirAlta() {
            this.quitarFoto();
            this.cerrarSimilares();
            this.form = {
                abierto: true, guardando: false, id: null, sku: '',
                descripcion: '', categoria_id: '',
                proveedor_id: this.proveedorFijo ? String(this.proveedorFijo) : '',
                precio_usd: '', sku_proveedor: '', descuento_producto: '',
                peso_gramos: '', temporada: 'atemporal', stock_infinito: false,
                categoriaRuta: [],
                foto: { archivo: null, previo: '' },
                stock_inicial: '',
            };
            this.preview = { dolar_proveedor: null, precio_venta: null };
        },

        abrirEdicion(p) {
            this.cerrarSimilares();
            this.form = {
                abierto: true, guardando: false, id: p.id, sku: p.sku,
                descripcion: p.descripcion || '',
                categoria_id: p.categoria_id,
                categoriaRuta: this.rutaDeIds(p.categoria_id),
                proveedor_id: p.proveedor_id,
                precio_usd: p.precio_usd,
                sku_proveedor: p.sku_proveedor || '',
                descuento_producto: p.descuento_producto,
                peso_gramos: p.peso_gramos || '',
                temporada: p.temporada,
                stock_infinito: p.stock_infinito,
                foto: { archivo: null, previo: '' },
                stock_inicial: '',
            };
            this.calcularPreview();
        },

        /* --- Guardar --- */

        async guardar({ conVariantes = false } = {}) {
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
                    temporada: this.form.temporada,
                    stock_infinito: this.form.stock_infinito,
                };
                if (alta) {
                    cuerpo.proveedor_id = Number(this.form.proveedor_id);
                    if (this.form.stock_inicial)
                        cuerpo.stock_inicial = Number(this.form.stock_inicial);
                }

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

                const habiaFoto = alta && !!this.form.foto.archivo;
                const fotoOk = alta ? await this.subirFotoDelAlta(guardado.id) : true;

                this.quitarFoto();
                this.form.abierto = false;
                window.toast(
                    alta
                        ? `Producto creado con SKU ${guardado.sku}`
                          + (habiaFoto && fotoOk ? ' y su foto' : '')
                        : 'Producto actualizado',
                    'exito'
                );

                if (alGuardar) alGuardar.call(this, guardado, { alta, conVariantes });
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.form.guardando = false;
            }
        },
    };
}
