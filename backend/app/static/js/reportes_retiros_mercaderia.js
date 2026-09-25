/* ==========================================================================
   Reporte: Retiros de mercadería de empleadas (sesión 09).

   Filtros resueltos en el backend (Principio 5). Las opciones de local
   viajan en la misma respuesta del reporte: con solo permiso de Reportes no
   hay acceso a /api/v1/puntos-de-venta.
   ========================================================================== */

const URL_REPORTE_RETIROS = '/api/v1/retiros-mercaderia/reporte';

function reporteRetirosMercaderia() {
    return {
        resultados: [],
        puntosDeVenta: [],
        total: 0,
        pagina: 1,
        tamano: 10,
        cargando: false,
        filtros: { desde: '', hasta: '', punto_de_venta_id: '' },

        pesos: (v) => window.pesos(v),

        fecha(iso) {
            return new Date(iso).toLocaleString('es-AR', {
                day: '2-digit', month: '2-digit', year: 'numeric',
                hour: '2-digit', minute: '2-digit',
            });
        },

        _params() {
            const params = new URLSearchParams();
            for (const [k, v] of Object.entries(this.filtros)) if (v) params.set(k, v);
            return params;
        },

        async cargar() {
            this.cargando = true;
            try {
                const params = this._params();
                params.set('pagina', this.pagina);
                params.set('tamano', this.tamano);
                const datos = await window.pedir(`${URL_REPORTE_RETIROS}?${params}`);
                this.resultados = datos.resultados;
                this.total = datos.total;
                this.puntosDeVenta = datos.opciones_locales;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        limpiar() {
            this.filtros = { desde: '', hasta: '', punto_de_venta_id: '' };
            this.pagina = 1;
            this.cargar();
        },

        urlExportar() {
            return `${URL_REPORTE_RETIROS}/exportar?${this._params()}`;
        },
    };
}
