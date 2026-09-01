/* ==========================================================================
   Catálogo de medios de pago y sus planes de cuotas.

   Los dos porcentajes se manejan por separado de punta a punta:
   `recargo_cliente` cambia lo que paga el cliente y `costo_medio` no.
   Acá nunca se suman ni se combinan — el único que entra en cualquier
   cuenta de precio es el primero, y esa cuenta la hace el backend.

   Nada se borra: los pagos ya registrados apuntan al medio y al plan.
   ========================================================================== */

const URL_MEDIOS = '/api/v1/configuracion/medios-de-pago';
const URL_PLANES = '/api/v1/configuracion/planes-cuotas';

function abmMediosDePago() {
    return {
        medios: [],
        cargando: false,
        filtros: { nombre: '', soporta_cuotas: '', activo: 'true' },

        medio: {
            abierto: false, guardando: false, id: null,
            nombre: '', soporta_cuotas: false, es_sena: false,
        },
        plan: {
            abierto: false, guardando: false, id: null,
            medio_id: null, medio_nombre: '',
            cuotas: 1, recargo_cliente: 0, costo_medio: 0, monto_minimo: 0,
        },

        pesos: (v) => window.pesos(v),

        /* Porcentaje tal como lo guarda el backend, sin ceros de relleno:
           "15%" y no "15.00%". */
        porcentaje(valor) {
            if (valor === null || valor === undefined) return '—';
            const n = Number(valor);
            // El mínimo explícito: sin él, `Intl` aplica su propio
            // redondeo y un 12,5% podría mostrarse como 13%.
            return `${n.toLocaleString('es-AR', {
                minimumFractionDigits: 0,
                maximumFractionDigits: 2,
            })}%`;
        },

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams();
                for (const [k, v] of Object.entries(this.filtros)) {
                    if (v !== '') params.set(k, v);
                }

                const resp = await fetch(`${URL_MEDIOS}?${params}`, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo cargar el catálogo');
                this.medios = await resp.json();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        /* "Limpiar" vuelve al estado de entrada, no a "mostrar todo": si
           reseteara `activo` a vacío traería los desactivados, que es lo
           contrario de lo que espera quien limpia para volver a empezar. */
        limpiar() {
            this.filtros = { nombre: '', soporta_cuotas: '', activo: 'true' };
            this.cargar();
        },

        /* --- Medios --- */

        abrirAltaMedio() {
            this.medio = {
                abierto: true, guardando: false, id: null,
                nombre: '', soporta_cuotas: false, es_sena: false,
            };
        },

        abrirEdicionMedio(m) {
            this.medio = {
                abierto: true, guardando: false, id: m.id,
                nombre: m.nombre,
                soporta_cuotas: m.soporta_cuotas,
                es_sena: m.es_sena,
            };
        },

        async guardarMedio() {
            this.medio.guardando = true;
            try {
                const alta = !this.medio.id;
                const resp = await fetch(
                    alta ? URL_MEDIOS : `${URL_MEDIOS}/${this.medio.id}`,
                    {
                        method: alta ? 'POST' : 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify({
                            nombre: this.medio.nombre,
                            soporta_cuotas: this.medio.soporta_cuotas,
                            es_sena: this.medio.es_sena,
                        }),
                    }
                );
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo guardar');
                }

                this.medio.abierto = false;
                window.toast(alta ? 'Medio de pago creado' : 'Medio de pago actualizado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.medio.guardando = false;
            }
        },

        async estadoMedio(m, activo) {
            await this._patchEstado(`${URL_MEDIOS}/${m.id}/estado`, activo,
                activo ? 'Medio activado' : 'Medio desactivado');
        },

        /* --- Planes --- */

        abrirAltaPlan(m) {
            this.plan = {
                abierto: true, guardando: false, id: null,
                medio_id: m.id, medio_nombre: m.nombre,
                cuotas: 1, recargo_cliente: 0, costo_medio: 0, monto_minimo: 0,
            };
        },

        abrirEdicionPlan(m, p) {
            this.plan = {
                abierto: true, guardando: false, id: p.id,
                medio_id: m.id, medio_nombre: m.nombre,
                cuotas: p.cuotas,
                recargo_cliente: Number(p.recargo_cliente),
                costo_medio: Number(p.costo_medio),
                monto_minimo: Number(p.monto_minimo),
            };
        },

        async guardarPlan() {
            this.plan.guardando = true;
            try {
                const alta = !this.plan.id;
                const cuerpo = {
                    cuotas: this.plan.cuotas,
                    recargo_cliente: this.plan.recargo_cliente,
                    costo_medio: this.plan.costo_medio,
                    monto_minimo: this.plan.monto_minimo,
                };

                const resp = await fetch(
                    alta
                        ? `${URL_MEDIOS}/${this.plan.medio_id}/planes`
                        : `${URL_PLANES}/${this.plan.id}`,
                    {
                        method: alta ? 'POST' : 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify(cuerpo),
                    }
                );
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo guardar el plan');
                }

                this.plan.abierto = false;
                window.toast(alta ? 'Plan creado' : 'Plan actualizado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.plan.guardando = false;
            }
        },

        async estadoPlan(p, activo) {
            await this._patchEstado(`${URL_PLANES}/${p.id}/estado`, activo,
                activo ? 'Plan activado' : 'Plan desactivado');
        },

        /* Los cuatro cambios de estado son el mismo PATCH con otra URL:
           escribirlos por separado sería copiar el manejo de error cuatro
           veces (Principio 2). */
        async _patchEstado(url, activo, mensaje) {
            try {
                const resp = await fetch(url, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ activo }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo cambiar el estado');
                }
                window.toast(mensaje, 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },
    };
}
