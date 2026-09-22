/* ==========================================================================
   Reporte: Resumen por punto de venta.

   Sin paginar (una fila por local, nunca son muchas) y sin combobox de
   ubicación/categoría/proveedor: acá la ubicación es la dimensión que
   agrupa las filas, no un filtro más.
   ========================================================================== */

function resumenPorPunto() {
    return {
        filas: [],           // [ResumenPuntoVentaFila] — ver backend/app/schemas/ventas.py
        columnasMedios: [],
        cargando: false,

        filtros: {
            fecha_desde: '',
            fecha_hasta: '',
        },

        porcentaje(fila, medio) {
            const valor = fila.porcentajes?.[medio];
            return valor === undefined ? '—' : Number(valor).toFixed(1) + '%';
        },

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams();
                if (this.filtros.fecha_desde) params.set('fecha_desde', this.filtros.fecha_desde);
                if (this.filtros.fecha_hasta) params.set('fecha_hasta', this.filtros.fecha_hasta);

                const resp = await fetch('/api/v1/ventas/resumen-por-punto?' + params, { credentials: 'same-origin' });
                if (!resp.ok) throw new Error(await resp.text());
                const datos = await resp.json();

                this.filas          = datos.filas;
                this.columnasMedios = datos.columnas_medios;
            } finally {
                this.cargando = false;
            }
        },

        limpiar() {
            this.filtros = { fecha_desde: '', fecha_hasta: '' };
            this.cargar();
        },

        urlExportar() {
            const params = new URLSearchParams();
            if (this.filtros.fecha_desde) params.set('fecha_desde', this.filtros.fecha_desde);
            if (this.filtros.fecha_hasta) params.set('fecha_hasta', this.filtros.fecha_hasta);
            return '/api/v1/ventas/resumen-por-punto/exportar?' + params;
        },
    };
}
