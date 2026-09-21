/* ==========================================================================
   Cambios de producto — mobile: tipo, ítems devueltos, ítems nuevos,
   confirmar y listo.

   A diferencia del wizard de escritorio (una sola página con `x-show` por
   paso), acá cada paso es una pantalla propia — mismo patrón que
   ventas_mobile.js — porque no hay wizard de una sola página que entre
   cómodo en 390px. El `id` del cambio viaja como query param entre
   pantallas: no existe un "cambio en curso" del que tirar como sí existe
   para ventas, así que cada pantalla lo lee de la URL y, si necesita los
   ítems ya cargados, los vuelve a pedir con `GET /cambios/{id}` — el estado
   vive en el servidor, no en el cliente.
   ========================================================================== */

const URL_CAMBIOS = '/api/v1/cambios';
const URL_VARIANTES = '/api/v1/productos/variantes';
const URL_AUTORIZADORES = '/api/v1/usuarios/autorizadores';
const URL_MEDIOS_CFG = '/api/v1/configuracion/medios-de-pago';

// Resuelto en el momento de llamar: este script no lleva `defer` y corre
// antes que app.js (mismo motivo que en ventas_mobile.js).
const pedir = (url, opciones) => window.pedir(url, opciones);

/** El `id` del cambio en curso, o null si se entró sin uno. */
function idDeUrl() {
    const id = new URLSearchParams(window.location.search).get('id');
    return id ? Number(id) : null;
}

/* ==========================================================================
   Paso 0 — Tipo de cambio
   ========================================================================== */

function cambioTipo(puntoDeVentaId, codigoInicial = '') {
    return {
        puntoDeVentaId: Number(puntoDeVentaId) || 0,
        enviando: false,
        autorizadores: [],

        form: {
            tipo: 'comun',
            codigo_cambio: codigoInicial || '',
            autorizador_id: null,
        },

        async init() {
            try {
                this.autorizadores = await pedir(URL_AUTORIZADORES);
            } catch (_) { /* no bloquea: el selector queda vacío */ }
        },

        async iniciar() {
            if (this.form.tipo !== 'falla' && !this.form.codigo_cambio.trim()) {
                window.toast('Ingresá el código de cambio del ticket', 'error');
                return;
            }
            if (this.form.tipo === 'falla' && !this.form.autorizador_id) {
                window.toast('Elegí quién autoriza el cambio', 'error');
                return;
            }

            this.enviando = true;
            try {
                const cambio = await pedir(URL_CAMBIOS, {
                    method: 'POST',
                    body: JSON.stringify({
                        tipo: this.form.tipo,
                        punto_de_venta_id: this.puntoDeVentaId,
                        codigo_cambio: this.form.tipo !== 'falla'
                            ? this.form.codigo_cambio.trim().toUpperCase() : null,
                        autorizador_id: this.form.tipo === 'falla' ? this.form.autorizador_id : null,
                    }),
                });
                window.location.href = `/cambios/nuevo/devueltos?id=${cambio.id}`;
            } catch (e) {
                window.toast(e.message, 'error');
                this.enviando = false;
            }
        },
    };
}

/* ==========================================================================
   Paso 1 — Ítems devueltos
   ========================================================================== */

function cambioDevueltos() {
    return {
        cambioId: idDeUrl(),
        cargando: true,
        enviando: false,
        items: [],
        scan: { codigo: '', resultados: [], sinResultados: false },

        pesos: (v) => window.pesos(v),

        get total() {
            return this.items.reduce((s, i) => s + parseFloat(i.precio_reconocido || 0), 0);
        },

        async init() {
            if (!this.cambioId) {
                window.location.href = '/cambios/nuevo';
                return;
            }
            try {
                const cambio = await pedir(`${URL_CAMBIOS}/${this.cambioId}`);
                this.items = cambio.items_devueltos;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        async buscar() {
            const codigo = this.scan.codigo.trim();
            if (!codigo) return;
            this.scan.resultados = [];
            this.scan.sinResultados = false;

            try {
                const params = new URLSearchParams({ busqueda: codigo, tamano: 10 });
                const datos = await pedir(`${URL_VARIANTES}?${params}`);
                if (!datos.resultados?.length) {
                    this.scan.sinResultados = true;
                } else {
                    this.scan.resultados = datos.resultados.map((r) => ({
                        ...r,
                        descripcion: r.producto?.descripcion || r.descripcion || '',
                    }));
                }
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        async agregar(variante) {
            this.enviando = true;
            try {
                const item = await pedir(`${URL_CAMBIOS}/${this.cambioId}/items-devueltos`, {
                    method: 'POST',
                    body: JSON.stringify({ variante_id: variante.id, venta_item_id: null }),
                });
                this.items.push(item);
                this.scan = { codigo: '', resultados: [], sinResultados: false };
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.enviando = false;
            }
        },

        continuar() {
            if (!this.items.length) return;
            window.location.href = `/cambios/nuevo/nuevos?id=${this.cambioId}`;
        },
    };
}

/* ==========================================================================
   Paso 2 — Ítems nuevos
   ========================================================================== */

function cambioNuevos() {
    return {
        cambioId: idDeUrl(),
        cargando: true,
        enviando: false,
        items: [],
        scan: { codigo: '', resultados: [], sinResultados: false },

        pesos: (v) => window.pesos(v),

        get total() {
            return this.items.reduce((s, i) => s + parseFloat(i.precio_actual || 0), 0);
        },

        async init() {
            if (!this.cambioId) {
                window.location.href = '/cambios/nuevo';
                return;
            }
            try {
                const cambio = await pedir(`${URL_CAMBIOS}/${this.cambioId}`);
                this.items = cambio.items_nuevos;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        async buscar() {
            const codigo = this.scan.codigo.trim();
            if (!codigo) return;
            this.scan.resultados = [];
            this.scan.sinResultados = false;

            try {
                const params = new URLSearchParams({ busqueda: codigo, tamano: 10 });
                const datos = await pedir(`${URL_VARIANTES}?${params}`);
                if (!datos.resultados?.length) {
                    this.scan.sinResultados = true;
                } else {
                    this.scan.resultados = datos.resultados.map((r) => ({
                        ...r,
                        descripcion: r.producto?.descripcion || r.descripcion || '',
                    }));
                }
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        async agregar(variante) {
            this.enviando = true;
            try {
                const item = await pedir(`${URL_CAMBIOS}/${this.cambioId}/items-nuevos`, {
                    method: 'POST',
                    body: JSON.stringify({ variante_id: variante.id }),
                });
                this.items.push(item);
                this.scan = { codigo: '', resultados: [], sinResultados: false };
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.enviando = false;
            }
        },

        async continuar() {
            if (!this.items.length) return;
            this.enviando = true;
            try {
                // Solo dispara el cálculo del lado del backend antes de
                // navegar: la pantalla de confirmar lo vuelve a pedir sola.
                await pedir(`${URL_CAMBIOS}/${this.cambioId}/diferencia`);
                window.location.href = `/cambios/nuevo/confirmar?id=${this.cambioId}`;
            } catch (e) {
                window.toast(e.message, 'error');
                this.enviando = false;
            }
        },
    };
}

/* ==========================================================================
   Paso 3 — Confirmar
   ========================================================================== */

function cambioConfirmar() {
    return {
        cambioId: idDeUrl(),
        cargando: true,
        enviando: false,
        diferencia: {},
        medios: [],
        confirmacion: { medio_pago_id: null, notas: '' },

        pesos: (v) => window.pesos(v),

        async init() {
            if (!this.cambioId) {
                window.location.href = '/cambios/nuevo';
                return;
            }
            try {
                const [diferencia, medios] = await Promise.all([
                    pedir(`${URL_CAMBIOS}/${this.cambioId}/diferencia`),
                    pedir(URL_MEDIOS_CFG).catch(() => []),
                ]);
                this.diferencia = diferencia;
                this.medios = medios;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        async confirmar() {
            this.enviando = true;
            try {
                await pedir(`${URL_CAMBIOS}/${this.cambioId}/confirmar`, {
                    method: 'POST',
                    body: JSON.stringify({
                        medio_pago_diferencia_id: this.confirmacion.medio_pago_id || null,
                        plan_cuotas_diferencia_id: null,
                        notas: this.confirmacion.notas || null,
                    }),
                });
                window.location.href = `/cambios/nuevo/listo?id=${this.cambioId}`;
            } catch (e) {
                window.toast(e.message, 'error');
                this.enviando = false;
            }
        },
    };
}

/* ==========================================================================
   Paso 4 — Listo
   ========================================================================== */

function cambioListo() {
    return {
        cambioId: idDeUrl(),
        cargando: true,
        cambio: null,

        async init() {
            if (!this.cambioId) {
                window.location.href = '/cambios/nuevo';
                return;
            }
            try {
                this.cambio = await pedir(`${URL_CAMBIOS}/${this.cambioId}`);
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },
    };
}
