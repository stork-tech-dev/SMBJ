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
        // Lo contado en efectivo al cerrar el turno anterior del local
        // ({efectivo, fecha_cierre}), o null. Precarga el efectivo inicial.
        cierreAnterior: null,
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
            if (this.overlay === 'iniciar') this.precargarEfectivo();
        },

        /**
         * Completa "Efectivo inicial en caja" con lo que se contó al cerrar el
         * turno anterior. Queda editable: si la vendedora cuenta otra cosa,
         * lo corrige. Si falla o no hubo cierre, el campo queda vacío como
         * siempre.
         */
        async precargarEfectivo() {
            this.cierreAnterior = null;
            try {
                const resp = await fetch(`${URL_TURNOS}/efectivo-cierre-anterior`, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) return;
                const datos = await resp.json();
                if (datos.efectivo === null || this.overlay !== 'iniciar') return;
                this.cierreAnterior = datos;
                if (this.efectivoApertura === '') this.efectivoApertura = Number(datos.efectivo);
            } catch {
                // Silencioso: es una ayuda, no puede trabar la apertura.
            }
        },

        get distintoDelCierre() {
            return this.cierreAnterior !== null && this.efectivoApertura !== ''
                && Number(this.efectivoApertura) !== Number(this.cierreAnterior.efectivo);
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
                // Los que se cuentan arrancan en 0; los informativos (Seña)
                // no se cuentan: su "declarado" es el total que se muestra.
                this.items = data.items.map(i => ({
                    ...i,
                    monto_declarado: i.es_informativo ? i.monto_esperado : 0,
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


/* ==========================================================================
   Operaciones de caja (sesión 09) — celular del local.

   Las cuatro pantallas registran sobre el turno abierto del local del
   dispositivo; el local lo decide el backend, no se manda desde acá.
   Los errores del backend se muestran tal cual (`window.pedir`).
   ========================================================================== */

const API_OPERACIONES = '/api/v1';

/** Comportamiento común: envío con toast de error y estado de "hecho". */
function _operacionBase() {
    return {
        cargando: false,
        enviando: false,
        hecho: null,
        pesos: (v) => window.pesos(v),

        async _enviar(url, cuerpo) {
            this.enviando = true;
            try {
                this.hecho = await window.pedir(url, {
                    method: 'POST',
                    body: JSON.stringify(cuerpo),
                });
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.enviando = false;
            }
        },
    };
}

function retiroEfectivo() {
    return {
        ..._operacionBase(),
        cargando: true,
        error: null,
        disponible: 0,
        monto: '',
        codigo: '',

        get superaDisponible() {
            return this.monto !== '' && Number(this.monto) > Number(this.disponible);
        },

        async cargar() {
            try {
                const datos = await window.pedir(`${API_OPERACIONES}/retiros-efectivo/disponible`);
                this.disponible = datos.disponible;
            } catch (e) {
                this.error = e.message;
            } finally {
                this.cargando = false;
            }
        },

        async confirmar() {
            if (this.superaDisponible) return;
            await this._enviar(`${API_OPERACIONES}/retiros-efectivo`, {
                monto: this.monto,
                codigo: this.codigo,
            });
            // Código incorrecto o error: se limpia el código para reintentar.
            if (!this.hecho) this.codigo = '';
        },
    };
}

function novedadCaja() {
    return {
        ..._operacionBase(),
        cargando: true,
        conceptos: [],
        autorizadores: [],
        conceptoId: '',
        autorizadorId: '',
        monto: '',
        notas: '',

        get concepto() {
            return this.conceptos.find((c) => String(c.id) === String(this.conceptoId)) || null;
        },

        async cargar() {
            try {
                [this.conceptos, this.autorizadores] = await Promise.all([
                    window.pedir(`${API_OPERACIONES}/novedades-caja/conceptos`),
                    window.pedir(`${API_OPERACIONES}/usuarios/autorizadores`),
                ]);
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        confirmar() {
            return this._enviar(`${API_OPERACIONES}/novedades-caja`, {
                concepto_id: Number(this.conceptoId),
                monto: this.monto,
                autorizador_id: Number(this.autorizadorId),
                notas: this.notas || null,
            });
        },
    };
}

function retiroMercaderia() {
    return {
        ..._operacionBase(),
        busqueda: '',
        resultados: [],
        empleada: null,
        otraEmpresa: false,
        nombreManual: '',
        dniManual: '',
        codigo: '',
        producto: null,

        get nombreEmpleada() {
            if (this.empleada) return this.empleada.nombre + ' (esta empresa)';
            return this.nombreManual.trim() + ' (otra empresa)';
        },

        get sinStock() {
            return !!this.producto && !this.producto.stock_infinito && this.producto.stock <= 0;
        },

        async buscarEmpleada() {
            const q = this.busqueda.trim();
            if (q.length < 2) { this.resultados = []; return; }
            try {
                this.resultados = await window.pedir(
                    `${API_OPERACIONES}/retiros-mercaderia/buscar-empleada?q=${encodeURIComponent(q)}`
                );
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        elegirEmpleada(usuario) {
            this.empleada = usuario;
            this.resultados = [];
            this.busqueda = '';
        },

        async buscarProducto() {
            const codigo = this.codigo.trim();
            if (!codigo) return;
            try {
                this.producto = await window.pedir(
                    `${API_OPERACIONES}/retiros-mercaderia/cotizar?codigo=${encodeURIComponent(codigo)}`
                );
            } catch (e) {
                this.producto = null;
                window.toast(e.message, 'error');
            }
        },

        confirmar() {
            return this._enviar(`${API_OPERACIONES}/retiros-mercaderia`, {
                variante_id: this.producto.variante_id,
                empleada_usuario_id: this.empleada ? this.empleada.id : null,
                empleada_nombre: this.empleada ? null : this.nombreManual.trim(),
                empleada_dni: this.empleada ? null : (this.dniManual.trim() || null),
            });
        },
    };
}

function cobroJoyero() {
    return {
        ..._operacionBase(),
        cargando: true,
        medios: [],
        montoEfectivo: '',
        montoOtros: '',
        reclamo: '',
        notas: '',
        forma: 'efectivo',
        medioId: '',

        get medioEfectivo() {
            return this.medios.find((m) => m.es_efectivo) || null;
        },

        get otrosMedios() {
            return this.medios.filter((m) => !m.es_efectivo);
        },

        get total() {
            const valor = this.forma === 'efectivo' ? this.montoEfectivo : this.montoOtros;
            return Number(valor || 0);
        },

        get puedeConfirmar() {
            if (this.total <= 0) return false;
            return this.forma === 'efectivo' ? !!this.medioEfectivo : !!this.medioId;
        },

        async cargar() {
            try {
                this.medios = await window.pedir(`${API_OPERACIONES}/cobros-joyero/medios-de-pago`);
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        confirmar() {
            const medio = this.forma === 'efectivo' ? this.medioEfectivo.id : Number(this.medioId);
            return this._enviar(`${API_OPERACIONES}/cobros-joyero`, {
                medio_de_pago_id: medio,
                monto_efectivo: this.montoEfectivo || 0,
                monto_otros: this.montoOtros || 0,
                numero_reclamo: this.reclamo || null,
                notas: this.notas || null,
            });
        },
    };
}
