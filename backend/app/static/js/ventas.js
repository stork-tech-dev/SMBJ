/* ==========================================================================
   Listado de ventas para escritorio.

   Tabla de alto volumen: los filtros se aplican con el botón "Buscar" y no
   al tipear (Principio 5). Todos se resuelven en el backend — nunca se
   filtra en el navegador sobre datos ya traídos, porque solo se tiene la
   página actual y el resultado sería una mentira parcial.
   ========================================================================== */

const URL_VENTAS = '/api/v1/ventas';
const URL_MEDIOS_CONFIG = '/api/v1/configuracion/medios-de-pago';

function listadoVentas(puedeAnular = false) {
    return {
        ventas: [],
        cargando: false,
        total: 0,
        pagina: 1,
        tamano: 50,
        puedeAnular,

        // Catálogos cargados una sola vez al abrir la pantalla.
        puntos: [],
        medios: {},

        filtros: {
            numero: '', estado: '',
            fecha_desde: '', fecha_hasta: '',
            punto_de_venta_id: '',
        },

        detalle: { abierto: false, venta: null },
        anulacion: { abierta: false, enviando: false, venta: null, motivo: '' },

        pesos: (v) => window.pesos(v),

        get paginas() {
            return Math.max(1, Math.ceil(this.total / this.tamano));
        },

        fecha(iso) {
            if (!iso) return '—';
            return new Date(iso).toLocaleString('es-AR', {
                day: '2-digit', month: '2-digit', year: 'numeric',
                hour: '2-digit', minute: '2-digit',
            });
        },

        etiquetaEstado(estado) {
            return { en_curso: 'En curso', confirmada: 'Confirmada', anulada: 'Anulada' }[estado]
                || estado;
        },

        colorEstado(estado) {
            if (estado === 'confirmada') return 'text-success';
            if (estado === 'anulada') return 'text-danger';
            return 'text-texto-muted';
        },

        nombreMedio(id) {
            return this.medios[id] || `Medio #${id}`;
        },

        async cargarCatalogos() {
            const resp = await fetch('/api/v1/stock/ubicaciones', { credentials: 'same-origin' });
            if (resp.ok) this.puntos = await resp.json();
        },

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams({
                    pagina: this.pagina,
                    tamano: this.tamano,
                });
                for (const [k, v] of Object.entries(this.filtros)) {
                    if (v !== '') params.set(k, v);
                }

                const pedidos = [fetch(`${URL_VENTAS}?${params}`, { credentials: 'same-origin' })];
                if (!Object.keys(this.medios).length) {
                    pedidos.push(fetch(URL_MEDIOS_CONFIG, { credentials: 'same-origin' }));
                }

                const [resp, medios] = await Promise.all(pedidos);
                if (!resp.ok) throw new Error('No se pudo cargar el listado');

                const datos = await resp.json();
                this.ventas = datos.resultados;
                this.total = datos.total;

                // Si el usuario no tiene permiso de configuración, el
                // catálogo vuelve 403 y el detalle muestra "Medio #3": es
                // peor que nada, pero mucho mejor que romper el listado
                // entero por un nombre.
                if (medios?.ok) {
                    for (const m of await medios.json()) this.medios[m.id] = m.nombre;
                }
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        /* Cambiar un filtro vuelve a la página 1: quedarse en la 3 de un
           resultado que ahora tiene una sola página muestra una tabla vacía
           sin decir por qué. */
        buscar() {
            this.pagina = 1;
            this.cargar();
        },

        irA(pagina) {
            if (pagina < 1 || pagina > this.paginas) return;
            this.pagina = pagina;
            this.cargar();
        },

        limpiar() {
            this.filtros = {
                numero: '', estado: '',
                fecha_desde: '', fecha_hasta: '',
                punto_de_venta_id: '',
            };
            this.buscar();
        },

        /* --- Detalle --- */

        async abrirDetalle(v) {
            this.detalle = { abierto: true, venta: null };
            try {
                // El listado trae el resumen; los ítems y los pagos hay que
                // pedirlos. Traerlos en el listado serían cincuenta ventas
                // con todos sus renglones para mostrar una.
                const resp = await fetch(`${URL_VENTAS}/${v.id}`, { credentials: 'same-origin' });
                if (!resp.ok) throw new Error('No se pudo cargar la venta');
                this.detalle.venta = await resp.json();
            } catch (e) {
                window.toast(e.message, 'error');
                this.detalle.abierto = false;
            }
        },

        /* --- Anulación --- */

        pedirAnulacion(v) {
            this.anulacion = { abierta: true, enviando: false, venta: v, motivo: '' };
        },

        async anular() {
            this.anulacion.enviando = true;
            try {
                const resp = await fetch(`${URL_VENTAS}/${this.anulacion.venta.id}/anular`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ motivo: this.anulacion.motivo || null }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo anular la venta');
                }

                this.anulacion.abierta = false;
                window.toast('Venta anulada: stock y puntos revertidos', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.anulacion.enviando = false;
            }
        },
    };
}
