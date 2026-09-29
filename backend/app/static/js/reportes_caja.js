/* ==========================================================================
   Reportes de Caja: un solo componente para los siete reportes.

   Todos filtran por un día (hoy por defecto) y, salvo Señas, por local; la
   respuesta de cada uno trae su propio `opciones_locales`. Lo que cambia
   entre reportes es la tabla, que arma cada plantilla sobre `datos`.
   Sin paginar: lo de un día es poco. Los filtros se resuelven en el backend
   (Principio 5). La pantalla mobile de movimientos de caja reusa este mismo
   componente con otra `base`.
   ========================================================================== */

function reporteCaja(slug, { conLocal = true, base = '/api/v1/reportes/caja/' + slug } = {}) {
    // `base` distinta: el mismo reporte servido por otro endpoint (los
    // movimientos de caja del celular, con permiso de caja y local fijo).

    return {
        datos: null,
        puntosDeVenta: [],
        cargando: false,

        filtros: { fecha: '', punto_de_venta_id: '', estado: '' },

        iniciar() {
            this.filtros.fecha = this.hoy();
            this.cargar();
        },

        hoy() {
            return window.hoyISO();
        },

        parametros() {
            const params = new URLSearchParams();
            if (this.filtros.fecha) params.set('fecha', this.filtros.fecha);
            if (conLocal && this.filtros.punto_de_venta_id) {
                params.set('punto_de_venta_id', this.filtros.punto_de_venta_id);
            }
            if (this.filtros.estado) params.set('estado', this.filtros.estado);
            return params;
        },

        async cargar() {
            this.cargando = true;
            try {
                const resp = await fetch(base + '?' + this.parametros(), { credentials: 'same-origin' });
                if (!resp.ok) throw new Error('No se pudo cargar el reporte');
                this.datos = await resp.json();
                if (this.datos.opciones_locales) this.puntosDeVenta = this.datos.opciones_locales;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        limpiar() {
            this.filtros = { fecha: this.hoy(), punto_de_venta_id: '', estado: '' };
            this.cargar();
        },

        urlExportar() {
            return base + '/exportar?' + this.parametros();
        },

        /* --- Formato (Principio 1: la API manda datos crudos) --- */

        hora(iso) {
            return iso
                ? new Date(iso).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit', hour12: false })
                : '';
        },

        fechaCorta(iso) {
            if (!iso) return '';
            // "2026-09-25" se parte a mano: new Date() lo leería como UTC y en
            // Argentina mostraría el día anterior.
            const [anio, mes, dia] = iso.slice(0, 10).split('-');
            return `${dia}/${mes}/${anio}`;
        },

        rangoTurno(t) {
            const hasta = t.fecha_cierre ? this.hora(t.fecha_cierre) : 'en curso';
            return `${t.punto_de_venta_nombre} · ${this.hora(t.fecha_apertura)} – ${hasta}`;
        },

        esCero(valor) {
            return Number(valor) === 0;
        },

        /** Item de un arqueo para una columna, o null si ese arqueo no la tiene. */
        itemDe(fila, columna) {
            return fila.items.find((i) => i.columna === columna) || null;
        },
    };
}
