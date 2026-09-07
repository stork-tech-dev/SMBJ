/* ==========================================================================
   Cambios de producto.

   Dos componentes Alpine:
     - listadoCambios()  → historial de cambios (/cambios)
     - nuevoCambio()     → wizard de cambio nuevo (/cambios/nuevo)
   ========================================================================== */

const URL_CAMBIOS    = '/api/v1/cambios';
const URL_VARIANTES  = '/api/v1/productos/variantes';
const URL_MEDIOS_CFG = '/api/v1/configuracion/medios-de-pago';


// ── Listado ─────────────────────────────────────────────────────────────────

function listadoCambios() {
    return {
        cambios: [],
        cargando: false,
        total: 0,
        pagina: 1,
        tamano: 10,

        filtros: { tipo: '', estado: '' },
        detalle: { abierto: false, cambio: null },

        pesos: (v) => window.pesos(v),

        get paginas() { return Math.max(1, Math.ceil(this.total / this.tamano)); },

        fecha(iso) {
            if (!iso) return '—';
            return new Date(iso).toLocaleString('es-AR', {
                day: '2-digit', month: '2-digit', year: 'numeric',
                hour: '2-digit', minute: '2-digit',
            });
        },

        etiquetaTipo(tipo) {
            return {
                comun: 'Común',
                promocion: 'Promoción',
                falla: 'Por falla',
                gift_card_fisica: 'Gift card',
            }[tipo] || tipo;
        },

        etiquetaEstado(estado) {
            return { pendiente: 'Pendiente', confirmado: 'Confirmado', cancelado: 'Cancelado' }[estado] || estado;
        },

        colorEstado(estado) {
            if (estado === 'confirmado') return 'text-success';
            if (estado === 'cancelado')  return 'text-danger';
            return 'text-warning';
        },

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams({ pagina: this.pagina, tamano: this.tamano });
                if (this.filtros.tipo)   params.set('tipo', this.filtros.tipo);
                if (this.filtros.estado) params.set('estado', this.filtros.estado);

                const resp = await fetch(`${URL_CAMBIOS}?${params}`, { credentials: 'same-origin' });
                if (!resp.ok) throw new Error('No se pudo cargar el historial');
                const datos = await resp.json();
                this.cambios = datos.resultados;
                this.total   = datos.total;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        buscar() { this.pagina = 1; this.cargar(); },
        irA(p)   { if (p >= 1 && p <= this.paginas) { this.pagina = p; this.cargar(); } },

        limpiar() { this.filtros = { tipo: '', estado: '' }; this.buscar(); },

        async abrirDetalle(c) {
            this.detalle = { abierto: true, cambio: null };
            try {
                const resp = await fetch(`${URL_CAMBIOS}/${c.id}`, { credentials: 'same-origin' });
                if (!resp.ok) throw new Error('No se pudo cargar el cambio');
                this.detalle.cambio = await resp.json();
            } catch (e) {
                window.toast(e.message, 'error');
                this.detalle.abierto = false;
            }
        },
    };
}


// ── Wizard de nuevo cambio ───────────────────────────────────────────────────

function nuevoCambio(codigoInicial = '') {
    return {
        pasos: ['Iniciar', 'Ítems devueltos', 'Ítems nuevos', 'Confirmar', 'Listo'],
        paso: 0,
        enviando: false,
        cambioId: null,
        avisos: [],

        form: {
            tipo: 'comun',
            codigo_cambio: codigoInicial || '',
            autorizador_id: null,
            punto_de_venta_id: null,
        },

        scan: { codigo: '', resultados: [], sinResultados: false },

        itemsDevueltos: [],
        itemsNuevos:    [],
        diferencia:     {},
        confirmacion:   { medio_pago_id: null, notas: '' },
        resultado:      {},

        medios: [],

        pesos: (v) => window.pesos(v),

        get totalDevuelto() {
            return this.itemsDevueltos.reduce((s, i) => s + parseFloat(i.precio_reconocido || 0), 0);
        },
        get totalNuevo() {
            return this.itemsNuevos.reduce((s, i) => s + parseFloat(i.precio_actual || 0), 0);
        },

        async init() {
            // Cargar medios de pago para el paso de confirmación
            try {
                const resp = await fetch(URL_MEDIOS_CFG, { credentials: 'same-origin' });
                if (resp.ok) this.medios = await resp.json();
            } catch (_) { /* no bloquea */ }
        },

        // ── Paso 0: iniciar cambio ──────────────────────────────────────────

        async iniciar() {
            if (!this.form.punto_de_venta_id) {
                window.toast('Completá el local donde se hace el cambio', 'error');
                return;
            }
            if (this.form.tipo !== 'falla' && !this.form.codigo_cambio.trim()) {
                window.toast('Ingresá el código de cambio del ticket', 'error');
                return;
            }

            this.enviando = true;
            try {
                const body = {
                    tipo: this.form.tipo,
                    punto_de_venta_id: this.form.punto_de_venta_id,
                    codigo_cambio: this.form.tipo !== 'falla' ? this.form.codigo_cambio.trim().toUpperCase() : null,
                    autorizador_id: this.form.tipo === 'falla' ? this.form.autorizador_id : null,
                };

                const resp = await fetch(URL_CAMBIOS, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify(body),
                });

                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo iniciar el cambio');
                }

                const cambio = await resp.json();
                this.cambioId = cambio.id;

                // Leer avisos del header X-Avisos si los hay
                const hdr = resp.headers.get('X-Avisos');
                if (hdr) {
                    try { this.avisos = JSON.parse(hdr); } catch (_) {}
                }

                this.paso = 1;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.enviando = false;
            }
        },

        // ── Pasos 1 y 2: buscar producto ────────────────────────────────────

        async buscarProducto(destino) {
            const codigo = this.scan.codigo.trim();
            if (!codigo) return;
            this.scan.resultados    = [];
            this.scan.sinResultados = false;

            try {
                const params = new URLSearchParams({ busqueda: codigo, tamano: 10 });
                const resp = await fetch(`${URL_VARIANTES}?${params}`, { credentials: 'same-origin' });
                if (!resp.ok) throw new Error('Error al buscar producto');
                const datos = await resp.json();

                if (!datos.resultados?.length) {
                    this.scan.sinResultados = true;
                } else {
                    // Enriquecer con producto para mostrar descripción
                    this.scan.resultados = datos.resultados.map(r => ({
                        ...r,
                        descripcion: r.producto?.descripcion || r.descripcion || '',
                        descripcion_sufijo: r.descripcion_sufijo || '',
                    }));
                }
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        // ── Paso 1: agregar ítem devuelto ───────────────────────────────────

        async agregarDevuelto(variante) {
            if (!this.cambioId) return;
            this.enviando = true;
            try {
                const body = { variante_id: variante.id, venta_item_id: null };
                const resp = await fetch(`${URL_CAMBIOS}/${this.cambioId}/items-devueltos`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify(body),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo agregar el ítem');
                }
                const item = await resp.json();
                this.itemsDevueltos.push(item);
                this.scan = { codigo: '', resultados: [], sinResultados: false };
                this.$nextTick(() => this.$refs.inputDevuelto?.focus());
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.enviando = false;
            }
        },

        // ── Paso 2: agregar ítem nuevo ──────────────────────────────────────

        async agregarNuevo(variante) {
            if (!this.cambioId) return;
            this.enviando = true;
            try {
                const body = { variante_id: variante.id };
                const resp = await fetch(`${URL_CAMBIOS}/${this.cambioId}/items-nuevos`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify(body),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo agregar el ítem');
                }
                const item = await resp.json();
                this.itemsNuevos.push(item);
                this.scan = { codigo: '', resultados: [], sinResultados: false };
                this.$nextTick(() => this.$refs.inputNuevo?.focus());
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.enviando = false;
            }
        },

        // ── Paso 3: calcular diferencia ─────────────────────────────────────

        async calcularDiferencia() {
            if (!this.cambioId) return;
            this.enviando = true;
            try {
                const resp = await fetch(`${URL_CAMBIOS}/${this.cambioId}/diferencia`, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo calcular la diferencia');
                }
                this.diferencia = await resp.json();
                this.paso = 3;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.enviando = false;
            }
        },

        // ── Confirmar ────────────────────────────────────────────────────────

        async confirmar() {
            if (!this.cambioId) return;

            const difPositiva = parseFloat(this.diferencia.diferencia || 0) > 0;
            if (difPositiva && !this.confirmacion.medio_pago_id) {
                window.toast('Elegí el medio de pago para la diferencia', 'error');
                return;
            }

            this.enviando = true;
            try {
                const body = {
                    medio_pago_diferencia_id: difPositiva ? this.confirmacion.medio_pago_id : null,
                    plan_cuotas_diferencia_id: null,
                    notas: this.confirmacion.notas || null,
                };
                const resp = await fetch(`${URL_CAMBIOS}/${this.cambioId}/confirmar`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify(body),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo confirmar el cambio');
                }
                this.resultado = await resp.json();
                this.paso = 4;
                window.toast('Cambio confirmado correctamente', 'exito');
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.enviando = false;
            }
        },
    };
}
