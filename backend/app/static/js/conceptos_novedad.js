/* ==========================================================================
   ABM de conceptos de novedad de caja (sesión 09).

   Un concepto no se borra: se desactiva, porque las novedades registradas
   lo apuntan. El tipo lo define acá la Cuenta Maestra.
   ========================================================================== */

const URL_CONCEPTOS = '/api/v1/configuracion/conceptos-novedad';

function abmConceptosNovedad() {
    return {
        motivos: [],
        cargando: false,
        filtros: { nombre: '', tipo: '', activo: 'true' },
        form: { abierto: false, guardando: false, id: null, nombre: '', tipo: 'salida' },
        confirmacion: { abierta: false, titulo: '', mensaje: '', accion: () => {} },

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams();
                for (const [k, v] of Object.entries(this.filtros)) if (v !== '') params.set(k, v);
                this.motivos = await window.pedir(`${URL_CONCEPTOS}?${params}`);
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        limpiar() {
            this.filtros = { nombre: '', tipo: '', activo: 'true' };
            this.cargar();
        },

        abrirAlta() {
            this.form = { abierto: true, guardando: false, id: null, nombre: '', tipo: 'salida' };
        },

        abrirEdicion(c) {
            this.form = { abierto: true, guardando: false, id: c.id, nombre: c.nombre, tipo: c.tipo };
        },

        async guardar() {
            this.form.guardando = true;
            try {
                const alta = !this.form.id;
                await window.pedir(alta ? URL_CONCEPTOS : `${URL_CONCEPTOS}/${this.form.id}`, {
                    method: alta ? 'POST' : 'PUT',
                    body: JSON.stringify({ nombre: this.form.nombre, tipo: this.form.tipo }),
                });
                this.form.abierto = false;
                window.toast(alta ? 'Concepto creado' : 'Concepto actualizado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.form.guardando = false;
            }
        },

        pedirCambioDeEstado(c, activo) {
            this.confirmacion = {
                abierta: true,
                titulo: activo ? 'Reactivar concepto' : 'Desactivar concepto',
                mensaje: activo
                    ? `¿Reactivar "${c.nombre}"? Vuelve a ofrecerse al cargar una novedad.`
                    : `¿Desactivar "${c.nombre}"? Deja de ofrecerse, pero sigue explicando `
                      + 'las novedades que ya se registraron con él.',
                accion: () => this.cambiarEstado(c, activo),
            };
        },

        async cambiarEstado(c, activo) {
            try {
                await window.pedir(`${URL_CONCEPTOS}/${c.id}/estado`, {
                    method: 'PATCH',
                    body: JSON.stringify({ activo }),
                });
                window.toast(activo ? 'Concepto activado' : 'Concepto desactivado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.confirmacion.abierta = false;
            }
        },
    };
}
