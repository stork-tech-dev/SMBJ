/* ==========================================================================
   Reporte "Historial del Producto".

   Un buscador (SKU, descripción o código de etiqueta) contra el endpoint
   propio del reporte y, al elegir un producto, el informe en cinco partes
   que arma el backend (Principio 1: acá solo se formatea). El producto
   elegido queda en la URL (`?producto_id=`) para volver o compartir el link.

   `nombres` son los mismos textos que usa el PDF (tipos de movimiento,
   campos de precio, orígenes del dólar): la ruta los pasa desde Python.
   ========================================================================== */

const API_HISTORIAL = '/api/v1/reportes/historial-producto';

function historialProducto(productoInicial, nombres) {
    return {
        busqueda: '',
        resultados: [],
        sinResultados: false,
        productoId: productoInicial || null,
        datos: null,
        cargando: false,

        iniciar() {
            if (this.productoId) this.cargar();
        },

        async buscar() {
            const texto = this.busqueda.trim();
            this.sinResultados = false;
            if (texto.length < 2) {
                this.resultados = [];
                return;
            }
            try {
                const params = new URLSearchParams({ busqueda: texto });
                this.resultados = await window.pedir(`${API_HISTORIAL}/buscar?${params}`);
                this.sinResultados = !this.resultados.length;
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        elegir(producto) {
            this.productoId = producto.id;
            this.resultados = [];
            this.busqueda = '';
            const url = new URL(window.location);
            url.searchParams.set('producto_id', producto.id);
            window.history.replaceState(null, '', url);
            this.cargar();
        },

        async cargar() {
            this.cargando = true;
            try {
                this.datos = await window.pedir(`${API_HISTORIAL}/${this.productoId}`);
            } catch (e) {
                this.datos = null;
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        get urlPdf() {
            return this.productoId ? `${API_HISTORIAL}/${this.productoId}/pdf` : '#';
        },

        /* --- Formato (Principio 1: la API manda datos crudos) --- */

        pesos: (v) => window.pesos(v),

        fechaHora(iso) {
            if (!iso) return '';
            return new Date(iso).toLocaleString('es-AR', {
                day: '2-digit', month: '2-digit', year: 'numeric',
                hour: '2-digit', minute: '2-digit', hour12: false,
            });
        },

        tipoMovimiento(tipo) {
            return nombres.tipos_movimiento[tipo] || tipo;
        },

        campoPrecio(fila) {
            const campo = nombres.campos_precio[fila.campo] || fila.campo;
            const origen = fila.origen ? nombres.origenes_dolar[fila.origen] : '';
            return origen ? `${campo} (${origen})` : campo;
        },

        // Los importes en pesos; el precio en dólares, el descuento (%) y la
        // cotización del dólar, como número.
        valorPrecio(fila, valor) {
            if (valor === null || valor === undefined) return '—';
            return fila.campo === 'precio_venta' ? this.pesos(valor) : String(Number(valor));
        },
    };
}
