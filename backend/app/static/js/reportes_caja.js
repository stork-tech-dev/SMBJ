/* ==========================================================================
   Reportes de Caja: un solo componente para los siete reportes.

   Todos filtran por un día (hoy por defecto) y, salvo Señas, por local; la
   respuesta de cada uno trae su propio `opciones_locales`. Los de `rango`
   (Novedades) filtran Desde/Hasta, del inicio del mes a hoy por defecto. Lo que cambia
   entre reportes es la tabla, que arma cada plantilla sobre `datos`.
   Sin paginar: lo de un día es poco. Los filtros se resuelven en el backend
   (Principio 5). La pantalla mobile de movimientos de caja reusa este mismo
   componente con otra `base`.
   ========================================================================== */

function reporteCaja(slug, {
    conLocal = true, rango = false, base = '/api/v1/reportes/caja/' + slug,
} = {}) {
    // `base` distinta: el mismo reporte servido por otro endpoint (los
    // movimientos de caja del celular, con permiso de caja y local fijo).

    return {
        datos: null,
        puntosDeVenta: [],
        cargando: false,

        filtros: { fecha: '', fecha_desde: '', fecha_hasta: '', punto_de_venta_id: '', estado: '' },

        iniciar() {
            this.filtros = this.filtrosIniciales();
            this.cargar();
        },

        // Lo que se ve al entrar y al limpiar: hoy, o del 1° del mes a hoy.
        filtrosIniciales() {
            const hoy = this.hoy();
            return {
                fecha: rango ? '' : hoy,
                fecha_desde: rango ? window.inicioMesISO() : '',
                fecha_hasta: rango ? hoy : '',
                punto_de_venta_id: '',
                estado: '',
            };
        },

        /** Clase de color de un medio de pago (`.serie-n` en custom.css). */
        colorMedio(serie) {
            return serie ? `serie-${serie}` : 'serie-otro';
        },

        /** Ancho del tramo de un medio en la barra: su parte de los ingresos por medio. */
        partePorcentual(fila, filas) {
            const suma = filas.reduce((total, f) => total + Number(f.total), 0);
            return suma ? (Number(fila.total) / suma) * 100 : 0;
        },

        hoy() {
            return window.hoyISO();
        },

        parametros() {
            const params = new URLSearchParams();
            if (this.filtros.fecha) params.set('fecha', this.filtros.fecha);
            if (this.filtros.fecha_desde) params.set('fecha_desde', this.filtros.fecha_desde);
            if (this.filtros.fecha_hasta) params.set('fecha_hasta', this.filtros.fecha_hasta);
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
            this.filtros = this.filtrosIniciales();
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
            // Con rango de fechas hay turnos de varios días: la hora sola no
            // dice de cuál es.
            const dia = rango ? `${this.fechaCorta(t.fecha_apertura)} · ` : '';
            return `${dia}${t.punto_de_venta_nombre} · ${this.hora(t.fecha_apertura)} – ${hasta}`;
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
