/* ==========================================================================
   Caja — Home y gestión de turnos (mobile).
   ========================================================================== */

const URL_TURNOS = '/api/v1/turnos';

function cajaTurno(puntoDeVentaId) {
    return {
        turno: null,          // turno activo o null
        cargando: true,
        overlay: null,        // 'iniciar' | 'sumarse' | null
        efectivoApertura: '',
        enviando: false,

        pesos: (v) => window.pesos(v),

        fecha(iso) {
            if (!iso) return '—';
            return new Date(iso).toLocaleString('es-AR', {
                day: '2-digit', month: '2-digit', year: 'numeric',
                hour: '2-digit', minute: '2-digit',
            });
        },

        async init() {
            await this.cargar();
        },

        async cargar() {
            this.cargando = true;
            try {
                const resp = await fetch(`${URL_TURNOS}/activo`, { credentials: 'same-origin' });
                if (resp.ok) {
                    this.turno = await resp.json();
                } else if (resp.status === 404) {
                    this.turno = null;
                } else {
                    throw new Error('No se pudo cargar el turno');
                }
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        abrirOverlay() {
            this.overlay = this.turno ? 'sumarse' : 'iniciar';
        },

        cerrarOverlay() {
            this.overlay = null;
            this.efectivoApertura = '';
        },

        async confirmarApertura() {
            if (!this.efectivoApertura && this.efectivoApertura !== 0) {
                window.toast('Ingresá el efectivo inicial', 'error');
                return;
            }
            this.enviando = true;
            try {
                const resp = await fetch(`${URL_TURNOS}/abrir`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ efectivo_apertura: parseFloat(this.efectivoApertura) || 0 }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo abrir el turno');
                }
                this.turno = await resp.json();
                this.cerrarOverlay();
                window.toast('Turno iniciado', 'exito');
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.enviando = false;
            }
        },

        async unirse() {
            this.enviando = true;
            try {
                const resp = await fetch(`${URL_TURNOS}/unirse`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: '{}',
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo unir al turno');
                }
                this.turno = await resp.json();
                this.cerrarOverlay();
                window.toast('Te sumaste al turno', 'exito');
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.enviando = false;
            }
        },
    };
}

/* --------------------------------------------------------------------------
   Pantalla de cierre: arqueo dinámico desde el API
   -------------------------------------------------------------------------- */
function cajaArqueo(turnoId) {
    return {
        turnoId,
        items: [],           // ArqueoItemEsperado[] + campo declarado
        totalDeclarado: 0,
        cargando: true,
        enviando: false,
        mostrarConfirmacion: false,
        diferencia: 0,

        pesos: (v) => window.pesos(v),

        async init() {
            await this.cargarEsperado();
        },

        async cargarEsperado() {
            this.cargando = true;
            try {
                const resp = await fetch(`/api/v1/turnos/${this.turnoId}/arqueo/esperado`, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo cargar el arqueo esperado');
                const data = await resp.json();
                // Inicializar items con monto_declarado = 0
                this.items = data.items.map(i => ({
                    ...i,
                    monto_declarado: 0,
                }));
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        get totalCalculado() {
            return this.items
                .filter(i => !i.es_informativo)
                .reduce((s, i) => s + (parseFloat(i.monto_declarado) || 0), 0);
        },

        get diferenciaTotalCalculada() {
            return this.totalCalculado - this.items
                .filter(i => !i.es_informativo)
                .reduce((s, i) => s + (parseFloat(i.monto_esperado) || 0), 0);
        },

        intentarCerrar() {
            this.diferencia = this.diferenciaTotalCalculada;
            if (Math.abs(this.diferencia) > 0.001) {
                this.mostrarConfirmacion = true;
            } else {
                this.cerrar();
            }
        },

        async cerrar() {
            this.mostrarConfirmacion = false;
            this.enviando = true;
            try {
                const body = {
                    items: this.items.map(i => ({
                        medio_de_pago_id: i.medio_de_pago_id ?? null,
                        grupo_terminal: i.grupo_terminal ?? null,
                        monto_declarado: parseFloat(i.monto_declarado) || 0,
                        es_informativo: i.es_informativo,
                    })),
                    total_declarado: this.totalCalculado,
                };
                const resp = await fetch(`/api/v1/turnos/${this.turnoId}/arqueo`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify(body),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo cerrar el turno');
                }
                window.toast('Turno cerrado correctamente', 'exito');
                // Redirigir al home
                window.location.href = '/ventas';
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.enviando = false;
            }
        },
    };
}
