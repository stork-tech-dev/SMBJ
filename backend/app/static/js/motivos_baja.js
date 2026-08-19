/* ==========================================================================
   ABM de motivos de baja de stock.

   El catálogo que llena el combo del modal de baja en /stock. Un motivo no
   se borra nunca: se desactiva, porque las bajas ya registradas lo apuntan y
   borrarlo dejaría sin explicación mercadería que ya se descontó.
   ========================================================================== */

const URL_MOTIVOS = '/api/v1/stock/motivos-baja';

function abmMotivosBaja() {
    return {
        motivos: [],
        cargando: false,
        filtros: { nombre: '', activo: 'true' },
        form: { abierto: false, guardando: false, id: null, nombre: '' },
        // Mismo diálogo que el resto del sistema (components/modal_confirmacion).
        confirmacion: { abierta: false, titulo: '', mensaje: '', accion: () => {} },

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams();
                for (const [k, v] of Object.entries(this.filtros)) if (v !== '') params.set(k, v);

                const resp = await fetch(`${URL_MOTIVOS}?${params}`, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo cargar el listado');
                this.motivos = await resp.json();
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
            this.filtros = { nombre: '', activo: 'true' };
            this.cargar();
        },

        abrirAlta() {
            this.form = { abierto: true, guardando: false, id: null, nombre: '' };
        },

        abrirEdicion(m) {
            this.form = { abierto: true, guardando: false, id: m.id, nombre: m.nombre };
        },

        async guardar() {
            this.form.guardando = true;
            try {
                const alta = !this.form.id;
                const resp = await fetch(
                    alta ? URL_MOTIVOS : `${URL_MOTIVOS}/${this.form.id}`,
                    {
                        method: alta ? 'POST' : 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify({ nombre: this.form.nombre }),
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

        /* Desactivar y reactivar pasan por el mismo PUT que renombra: el
           backend no tiene endpoint de borrado, y no lo tiene a propósito. */
        pedirCambioDeEstado(m, activo) {
            this.confirmacion = {
                abierta: true,
                titulo: activo ? 'Reactivar motivo' : 'Desactivar motivo',
                mensaje: activo
                    ? `¿Reactivar "${m.nombre}"? Vuelve a ofrecerse al registrar una baja.`
                    : `¿Desactivar "${m.nombre}"? Deja de ofrecerse al registrar una baja, `
                      + 'pero sigue explicando las bajas que ya se hicieron con él.',
                accion: () => this.cambiarEstado(m, activo),
            };
        },

        async cambiarEstado(m, activo) {
            try {
                const resp = await fetch(`${URL_MOTIVOS}/${m.id}`, {
                    method: 'PUT',
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
            } finally {
                this.confirmacion.abierta = false;
            }
        },
    };
}
