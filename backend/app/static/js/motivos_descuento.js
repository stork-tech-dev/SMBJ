/* ==========================================================================
   Catálogo de motivos de descuento.

   La lista de porcentajes NO está escrita acá: se pide a
   /api/v1/ventas/opciones-descuento, que la sirve desde la misma constante
   que valida el backend. Una lista copiada en el JavaScript terminaría
   ofreciendo un valor que la API rechaza, y el error aparecería recién al
   guardar.

   Un motivo no se borra: se desactiva, porque los ítems con descuento lo
   apuntan y borrarlo dejaría descuentos sin explicación.
   ========================================================================== */

const URL_MOTIVOS_DESC = '/api/v1/configuracion/motivos-descuento';
const URL_OPCIONES_DESC = '/api/v1/ventas/opciones-descuento';

function abmMotivosDescuento() {
    return {
        motivos: [],
        porcentajes: [],
        cargando: false,
        filtros: { nombre: '', habilita_cuotas_sin_interes: '', activo: 'true' },

        form: {
            abierto: false, guardando: false, id: null,
            nombre: '', porcentaje_sugerido: '', habilita_cuotas_sin_interes: false,
        },

        porcentaje(valor) {
            if (valor === null || valor === undefined) return '—';
            // El mínimo explícito: sin él, `Intl` aplica su propio
            // redondeo y un 12,5% podría mostrarse como 13%.
            return `${Number(valor).toLocaleString('es-AR', {
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

                // La lista de porcentajes se pide una sola vez: no cambia
                // mientras la pantalla está abierta.
                const pedidos = [fetch(`${URL_MOTIVOS_DESC}?${params}`, { credentials: 'same-origin' })];
                if (!this.porcentajes.length) {
                    pedidos.push(fetch(URL_OPCIONES_DESC, { credentials: 'same-origin' }));
                }

                const [resp, opciones] = await Promise.all(pedidos);
                if (!resp.ok) throw new Error('No se pudo cargar el catálogo');
                this.motivos = await resp.json();

                if (opciones?.ok) {
                    this.porcentajes = (await opciones.json()).porcentajes;
                }
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        /* "Limpiar" vuelve al estado de entrada, no a "mostrar todo". */
        limpiar() {
            this.filtros = { nombre: '', habilita_cuotas_sin_interes: '', activo: 'true' };
            this.cargar();
        },

        abrirAlta() {
            this.form = {
                abierto: true, guardando: false, id: null,
                nombre: '', porcentaje_sugerido: '', habilita_cuotas_sin_interes: false,
            };
        },

        abrirEdicion(m) {
            this.form = {
                abierto: true, guardando: false, id: m.id,
                nombre: m.nombre,
                // A string: el <select> compara por valor de texto, y con un
                // número el sugerido no quedaría preseleccionado al abrir.
                porcentaje_sugerido:
                    m.porcentaje_sugerido === null ? '' : String(Number(m.porcentaje_sugerido)),
                habilita_cuotas_sin_interes: m.habilita_cuotas_sin_interes,
            };
        },

        async guardar() {
            this.form.guardando = true;
            try {
                const alta = !this.form.id;
                // El vacío viaja como null explícito: en la edición eso
                // significa "sacale el sugerido", que es distinto de "no lo
                // mandes", y el backend distingue los dos casos.
                const cuerpo = {
                    nombre: this.form.nombre,
                    porcentaje_sugerido:
                        this.form.porcentaje_sugerido === ''
                            ? null
                            : Number(this.form.porcentaje_sugerido),
                    habilita_cuotas_sin_interes: this.form.habilita_cuotas_sin_interes,
                };

                const resp = await fetch(
                    alta ? URL_MOTIVOS_DESC : `${URL_MOTIVOS_DESC}/${this.form.id}`,
                    {
                        method: alta ? 'POST' : 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify(cuerpo),
                    }
                );
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo guardar');
                }

                this.form.abierto = false;
                window.toast(alta ? 'Motivo creado' : 'Motivo actualizado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.form.guardando = false;
            }
        },

        async cambiarEstado(m, activo) {
            try {
                const resp = await fetch(`${URL_MOTIVOS_DESC}/${m.id}/estado`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ activo }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo cambiar el estado');
                }
                window.toast(activo ? 'Motivo activado' : 'Motivo desactivado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },
    };
}
