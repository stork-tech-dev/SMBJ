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

        // Productos del ticket del código ({origen, items}) y los elegidos
        // para devolver (claves de `claveItem`).
        ticket: null,
        elegidos: [],
        buscando: false,

        pesos: (v) => window.pesos(v),

        async init() {
            try {
                this.autorizadores = await pedir(URL_AUTORIZADORES);
            } catch (_) { /* no bloquea: el selector queda vacío */ }
            if (this.form.codigo_cambio.trim().length === 8) this.buscarTicket();
        },

        get puedeContinuar() {
            return this.form.tipo === 'falla' || this.elegidos.length > 0;
        },

        claveItem(it) {
            return it.venta_item_id ?? `v${it.variante_id}`;
        },

        elegido(it) {
            return this.elegidos.includes(this.claveItem(it));
        },

        alternar(it) {
            const clave = this.claveItem(it);
            this.elegidos = this.elegido(it)
                ? this.elegidos.filter((c) => c !== clave)
                : [...this.elegidos, clave];
        },

        // Otro código: lo elegido ya no corresponde. Con los 8 caracteres
        // busca solo, sin tener que tocar la lupa.
        codigoCambiado() {
            this.ticket = null;
            this.elegidos = [];
            if (this.form.codigo_cambio.trim().length === 8) this.buscarTicket();
        },

        async buscarTicket() {
            const codigo = this.form.codigo_cambio.trim().toUpperCase();
            if (!codigo) return;
            this.buscando = true;
            try {
                const params = new URLSearchParams({ codigo });
                this.ticket = await pedir(`${URL_CAMBIOS}/ticket?${params}`);
                // Un solo producto posible (retiro, o ticket de un ítem): ya elegido.
                const disponibles = this.ticket.items.filter((i) => i.disponible);
                this.elegidos = disponibles.length === 1 ? [this.claveItem(disponibles[0])] : [];
                if (!disponibles.length) {
                    window.toast('Todos los productos de ese ticket ya se devolvieron', 'error');
                }
            } catch (e) {
                this.ticket = null;
                window.toast(e.message, 'error');
            } finally {
                this.buscando = false;
            }
        },

        async iniciar() {
            if (this.form.tipo !== 'falla' && !this.form.codigo_cambio.trim()) {
                window.toast('Ingresá el código de cambio del ticket', 'error');
                return;
            }
            if (this.form.tipo !== 'falla' && !this.elegidos.length) {
                window.toast('Elegí qué productos del ticket devuelve el cliente', 'error');
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
                if (this.form.tipo === 'falla') {
                    window.location.href = `/cambios/nuevo/devueltos?id=${cambio.id}`;
                    return;
                }

                // Lo elegido del ticket entra como devuelto y se sigue directo
                // a los ítems nuevos. Si alguno no entra, se va a "Ítems
                // devueltos" (el cambio ya existe) para corregirlo ahí.
                const seleccion = this.ticket.items.filter((i) => this.elegido(i));
                let fallo = false;
                for (const it of seleccion) {
                    try {
                        await pedir(`${URL_CAMBIOS}/${cambio.id}/items-devueltos`, {
                            method: 'POST',
                            body: JSON.stringify({
                                variante_id: it.variante_id,
                                venta_item_id: it.venta_item_id,
                            }),
                        });
                    } catch (e) {
                        fallo = true;
                        window.toast(`${it.codigo}: ${e.message}`, 'error');
                    }
                }
                window.location.href = fallo
                    ? `/cambios/nuevo/devueltos?id=${cambio.id}`
                    : `/cambios/nuevo/nuevos?id=${cambio.id}`;
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
        // Respuesta de GET /cambios/{id}/diferencia, al día con lo agregado.
        diferencia: null,
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
                if (this.items.length) await this.calcularDiferencia();
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
                await this.calcularDiferencia();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.enviando = false;
            }
        },

        /**
         * Misma cuenta que la pantalla de confirmar (promociones, precio
         * reconocido): la hace el backend. Silenciosa si falla: el resumen
         * simplemente no se actualiza.
         */
        async calcularDiferencia() {
            try {
                this.diferencia = await pedir(`${URL_CAMBIOS}/${this.cambioId}/diferencia`);
            } catch (_) { /* se vuelve a pedir en confirmar */ }
        },

        continuar() {
            if (!this.items.length) return;
            window.location.href = `/cambios/nuevo/confirmar?id=${this.cambioId}`;
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
