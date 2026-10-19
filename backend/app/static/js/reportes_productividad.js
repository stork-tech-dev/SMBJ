/* ==========================================================================
   Reportes de Productividad: un componente para los dos (Centro de
   Distribución y Vendedores).

   Filtran por Desde/Hasta (del inicio del mes a hoy por defecto) y
   Vendedores también por local; la respuesta trae `filas` (una por usuario)
   y `totales`. Tabla chica (una fila por usuario): recarga en cada cambio,
   sin botón "Buscar". Los filtros los resuelve el backend (Principio 5).
   ========================================================================== */

function reporteProductividad(slug, { conLocal = false } = {}) {
    const base = '/api/v1/reportes/productividad/' + slug;

    return {
        datos: null,
        puntosDeVenta: [],
        cargando: false,
        filtros: {},

        iniciar() {
            this.filtros = this.filtrosIniciales();
            this.cargar();
        },

        // Lo que se ve al entrar y al limpiar: del 1° del mes a hoy.
        filtrosIniciales() {
            return {
                fecha_desde: window.inicioMesISO(),
                fecha_hasta: window.hoyISO(),
                punto_de_venta_id: '',
            };
        },

        parametros() {
            const params = new URLSearchParams();
            if (this.filtros.fecha_desde) params.set('fecha_desde', this.filtros.fecha_desde);
            if (this.filtros.fecha_hasta) params.set('fecha_hasta', this.filtros.fecha_hasta);
            if (conLocal && this.filtros.punto_de_venta_id) {
                params.set('punto_de_venta_id', this.filtros.punto_de_venta_id);
            }
            return params;
        },

        async cargar() {
            this.cargando = true;
            try {
                this.datos = await window.pedir(base + '?' + this.parametros());
                if (this.datos.opciones_locales) this.puntosDeVenta = this.datos.opciones_locales;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        limpiar() {
            this.filtros = this.filtrosIniciales();
            this.cargar();
        },

        urlExportar() {
            return base + '/exportar?' + this.parametros();
        },

        pesos: (v) => window.pesos(v),

        // Un cero se atenúa: lo que hizo cada uno resalta solo.
        claseNumero(valor) {
            return Number(valor) === 0 ? 'text-texto-disabled' : 'text-texto';
        },
    };
}
