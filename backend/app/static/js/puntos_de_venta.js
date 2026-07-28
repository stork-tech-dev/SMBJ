/* ==========================================================================
   ABM de puntos de venta.
   ========================================================================== */

function abmPuntos() {
    return {
        puntos: [],
        cargando: false,
        filtros: { nombre: '', tipo: '', activo: '' },
        form: { abierto: false, guardando: false, id: null, nombre: '', tipo: 'local', codigo_confirmacion: '' },
        baja: { abierta: false, punto: null, advertencia: '' },

        etiquetaTipo(t) {
            return { cd: 'Centro de Distribución', local: 'Local', online: 'Online' }[t] || t;
        },
        badgeTipo(t) {
            return {
                cd: 'bg-primary/15 text-primary',
                local: 'bg-accent text-white',
                online: 'bg-success/15 text-success',
            }[t] || 'bg-surface-alt text-texto-muted';
        },

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams();
                for (const [k, v] of Object.entries(this.filtros)) if (v !== '') params.set(k, v);
                const resp = await fetch('/api/v1/puntos-de-venta?' + params, { credentials: 'same-origin' });
                if (!resp.ok) throw new Error('No se pudo cargar el listado');
                this.puntos = await resp.json();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        limpiar() {
            this.filtros = { nombre: '', tipo: '', activo: '' };
            this.cargar();
        },

        abrirAlta() {
            this.form = { abierto: true, guardando: false, id: null, nombre: '', tipo: 'local', codigo_confirmacion: '' };
        },
        abrirEdicion(p) {
            this.form = {
                abierto: true, guardando: false, id: p.id, nombre: p.nombre,
                tipo: p.tipo, codigo_confirmacion: p.codigo_confirmacion || '',
            };
        },

        async guardar() {
            this.form.guardando = true;
            try {
                const alta = !this.form.id;
                const cuerpo = { nombre: this.form.nombre, tipo: this.form.tipo };
                // El código solo se manda para locales.
                cuerpo.codigo_confirmacion = (this.form.tipo === 'local' && this.form.codigo_confirmacion)
                    ? this.form.codigo_confirmacion : null;

                const resp = await fetch(
                    alta ? '/api/v1/puntos-de-venta' : '/api/v1/puntos-de-venta/' + this.form.id,
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
                window.toast(alta ? 'Punto de venta creado' : 'Punto de venta actualizado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.form.guardando = false;
            }
        },

        pedirBaja(p) {
            this.baja = { abierta: true, punto: p, advertencia: '' };
        },

        async confirmarBaja() {
            const resp = await this.cambiarEstado(this.baja.punto, false, !!this.baja.advertencia);
            if (resp && resp.status === 409) {
                const err = await resp.json();
                this.baja.advertencia = err.detail;
                return;
            }
            this.baja.abierta = false;
        },

        async cambiarEstado(p, activo, confirmar) {
            try {
                const resp = await fetch(`/api/v1/puntos-de-venta/${p.id}/estado`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ activo, confirmar }),
                });
                if (resp.status === 409 && !activo) return resp;  // baja: manejar advertencia arriba
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo cambiar el estado');
                }
                window.toast(activo ? 'Punto de venta activado' : 'Punto de venta desactivado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },
    };
}
