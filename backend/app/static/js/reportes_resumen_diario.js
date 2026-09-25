/* ==========================================================================
   Reporte: Resumen diario consolidado (control de cierres de caja).

   Sin paginar: los turnos de un día son pocos. Las opciones de ubicación
   viajan en la propia respuesta de /api/v1/ventas/resumen-diario, mismo
   motivo que en los otros reportes: sin permiso de Reportes no se puede
   pegar directo a /api/v1/puntos-de-venta.
   ========================================================================== */

function resumenDiario() {
    return {
        filas: [],           // [ResumenDiarioFila] — ver backend/app/schemas/ventas.py
        puntosDeVenta: [],
        cargando: false,

        filtros: {
            fecha:             '',
            punto_de_venta_id: '',
        },

        hoy() {
            const d = new Date();
            const mes = String(d.getMonth() + 1).padStart(2, '0');
            const dia = String(d.getDate()).padStart(2, '0');
            return `${d.getFullYear()}-${mes}-${dia}`;
        },

        rangoTurno(fila) {
            const hora = (iso) => new Date(iso).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
            const hasta = fila.fecha_cierre ? hora(fila.fecha_cierre) : 'en curso';
            return hora(fila.fecha_apertura) + ' – ' + hasta;
        },

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams();
                if (this.filtros.fecha)             params.set('fecha', this.filtros.fecha);
                if (this.filtros.punto_de_venta_id) params.set('punto_de_venta_id', this.filtros.punto_de_venta_id);

                const resp = await fetch('/api/v1/ventas/resumen-diario?' + params, { credentials: 'same-origin' });
                if (!resp.ok) throw new Error(await resp.text());
                const datos = await resp.json();

                this.filas          = datos.filas;
                this.puntosDeVenta  = datos.opciones_locales;
            } finally {
                this.cargando = false;
            }
        },

        limpiar() {
            this.filtros = { fecha: this.hoy(), punto_de_venta_id: '' };
            this.cargar();
        },

        urlExportar() {
            const params = new URLSearchParams();
            if (this.filtros.fecha)             params.set('fecha', this.filtros.fecha);
            if (this.filtros.punto_de_venta_id) params.set('punto_de_venta_id', this.filtros.punto_de_venta_id);
            return '/api/v1/ventas/resumen-diario/exportar?' + params;
        },
    };
}
