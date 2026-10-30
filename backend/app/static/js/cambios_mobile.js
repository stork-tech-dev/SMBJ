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

// Largo del código de cambio: el mismo que genera el backend
// (`LARGO_CODIGO_CAMBIO` en services/ventas.py). Los emitidos antes de
// acortarlo tienen 8 y siguen valiendo.
const LARGO_CODIGO_CAMBIO = 4;
const LARGO_CODIGO_CAMBIO_VIEJO = 8;
// Pausa de tipeo antes de buscar solo el ticket.
const ESPERA_BUSQUEDA_MS = 500;

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

        // Los tickets que trae el cliente ({codigo, origen, items}): pueden
        // ser varios y lo devuelto de todos suma. `elegidos` son las claves
        // (`claveItem`) de lo que se devuelve, de cualquiera de los tickets.
        tickets: [],
        elegidos: [],
        buscando: false,
        // Con un ticket ya cargado, el campo del código aparece de nuevo
        // solo al tocar "+ Agregar otro ticket".
        agregandoTicket: false,

        pesos: (v) => window.pesos(v),

        async init() {
            try {
                this.autorizadores = await pedir(URL_AUTORIZADORES);
            } catch (_) { /* no bloquea: el selector queda vacío */ }
            if (this.codigoCompleto) this.buscarTicket();
        },

        get puedeContinuar() {
            return this.form.tipo === 'falla' || this.elegidos.length > 0;
        },

        get verCampoCodigo() {
            return this.form.tipo !== 'falla' && (!this.tickets.length || this.agregandoTicket);
        },

        // Lo que suma lo elegido de todos los tickets.
        get totalElegido() {
            return this.tickets.flatMap((t) => t.items)
                .filter((i) => this.elegido(i))
                .reduce((s, i) => s + Number(i.precio), 0);
        },

        claveItem(it) {
            if (it.venta_item_id) return it.venta_item_id;
            return it.retiro_mercaderia_id ? `r${it.retiro_mercaderia_id}` : `v${it.variante_id}`;
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

        quitarTicket(ticket) {
            const claves = ticket.items.map((i) => this.claveItem(i));
            this.elegidos = this.elegidos.filter((c) => !claves.includes(c));
            this.tickets = this.tickets.filter((t) => t !== ticket);
        },

        // Si el código ya tiene el largo de uno completo: 4 caracteres, u 8
        // los de antes de que se acortaran (siguen siendo válidos).
        get codigoCompleto() {
            const largo = this.form.codigo_cambio.trim().length;
            return largo === LARGO_CODIGO_CAMBIO || largo === LARGO_CODIGO_CAMBIO_VIEJO;
        },

        // Completo, busca solo sin tener que tocar la lupa, pero recién
        // cuando se deja de escribir: así uno viejo de 8 no se busca (y
        // falla) a los 4.
        esperaBusqueda: null,

        codigoCambiado() {
            clearTimeout(this.esperaBusqueda);
            if (this.codigoCompleto) {
                this.esperaBusqueda = setTimeout(() => this.buscarTicket(), ESPERA_BUSQUEDA_MS);
            }
        },

        async buscarTicket() {
            clearTimeout(this.esperaBusqueda);
            const codigo = this.form.codigo_cambio.trim().toUpperCase();
            if (!codigo) return;
            if (this.tickets.some((t) => t.codigo === codigo)) {
                window.toast(`El ticket ${codigo} ya está cargado`, 'error');
                return;
            }
            this.buscando = true;
            try {
                const params = new URLSearchParams({ codigo });
                const ticket = await pedir(`${URL_CAMBIOS}/ticket?${params}`);
                const disponibles = ticket.items.filter((i) => i.disponible);
                if (!disponibles.length) {
                    window.toast('Todos los productos de ese ticket ya se devolvieron', 'error');
                    return;
                }
                this.tickets = [...this.tickets, { codigo, ...ticket }];
                // Un solo producto posible (retiro, o ticket de un ítem): ya elegido.
                if (disponibles.length === 1) this.elegidos = [...this.elegidos, this.claveItem(disponibles[0])];
                this.form.codigo_cambio = '';
                this.agregandoTicket = false;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.buscando = false;
            }
        },

        async iniciar() {
            if (this.form.tipo !== 'falla' && !this.tickets.length) {
                window.toast('Ingresá el código de cambio del ticket', 'error');
                return;
            }
            if (this.form.tipo !== 'falla' && !this.elegidos.length) {
                window.toast('Elegí qué productos de los tickets devuelve el cliente', 'error');
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
                        codigos_cambio: this.form.tipo !== 'falla'
                            ? this.tickets.map((t) => t.codigo) : [],
                        autorizador_id: this.form.tipo === 'falla' ? this.form.autorizador_id : null,
                    }),
                });
                if (this.form.tipo === 'falla') {
                    window.location.href = `/cambios/nuevo/devueltos?id=${cambio.id}`;
                    return;
                }

                // Lo elegido de los tickets entra como devuelto y se sigue
                // directo a los ítems nuevos. Si alguno no entra, se va a
                // "Ítems devueltos" (el cambio ya existe) para corregirlo ahí.
                const seleccion = this.tickets.flatMap((t) => t.items).filter((i) => this.elegido(i));
                let fallo = false;
                for (const it of seleccion) {
                    try {
                        await pedir(`${URL_CAMBIOS}/${cambio.id}/items-devueltos`, {
                            method: 'POST',
                            body: JSON.stringify({
                                variante_id: it.variante_id,
                                venta_item_id: it.venta_item_id,
                                retiro_mercaderia_id: it.retiro_mercaderia_id,
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
                // Los medios los da el propio cambio (permiso de Ventas):
                // el catálogo de Configuración no lo ve una vendedora, y
                // el combo quedaba vacío sin avisar.
                const [diferencia, medios] = await Promise.all([
                    pedir(`${URL_CAMBIOS}/${this.cambioId}/diferencia`),
                    pedir(`${URL_CAMBIOS}/${this.cambioId}/medios-de-pago`),
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
