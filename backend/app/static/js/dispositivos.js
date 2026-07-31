/* ==========================================================================
   Administración de dispositivos.
   ========================================================================== */

function abmDispositivos() {
    return {
        dispositivos: [],
        locales: [],
        cargando: false,
        filtros: { descripcion: '', punto_de_venta_id: '', activo: '', acceso_desde: '', acceso_hasta: '' },
        form: {
            abierto: false, guardando: false, id: null, uuid: '',
            descripcion: '', punto_de_venta_id: '', observaciones: '', activo: false,
        },

        /**
         * Sistema y navegador en una línea: "Android 13 · Chrome 120".
         *
         * Une los tramos que existen: en un equipo que nunca se conectó, o
         * con un User-Agent que las heurísticas no reconocen, los dos
         * pueden ser null y se muestra un guion.
         */
        equipo(d) {
            const partes = [d.sistema_operativo, d.navegador].filter(Boolean);
            return partes.length ? partes.join(' · ') : '—';
        },

        formatearFecha(iso) {
            if (!iso) return 'Nunca';
            return new Date(iso).toLocaleString('es-AR', {
                day: '2-digit', month: '2-digit', year: '2-digit',
                hour: '2-digit', minute: '2-digit', hour12: false,
            });
        },

        nombreLocal(id) {
            if (!id) return 'Sin asignar';
            const l = this.locales.find((x) => x.id === id);
            return l ? l.nombre : '—';
        },

        /**
         * Estado del dispositivo: activo o inactivo, y nada más.
         *
         * Antes devolvía "Sin asignar" cuando no había local, y esa rama
         * cortaba ANTES de mirar `activo`: dos dispositivos con estado
         * opuesto se veían idénticos, y activar uno sin local parecía no
         * haber tenido efecto. Que no tenga local ya se ve en la columna
         * "Local" y en el borde rojo de la fila; repetirlo acá costaba
         * justamente el dato que esta columna tiene que mostrar.
         */
        etiquetaEstado(d) {
            return d.activo ? 'Activo' : 'Inactivo';
        },
        badgeEstado(d) {
            return d.activo ? 'bg-success/15 text-success' : 'bg-danger/15 text-danger';
        },

        /**
         * Un dispositivo activo pero sin local todavía no puede operar:
         * `get_active_device` exige las dos condiciones. Se avisa al lado
         * del estado para no perder ese matiz al separar las etiquetas.
         */
        faltaLocal(d) {
            return d.activo && !d.punto_de_venta_id;
        },

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams();
                for (const [k, v] of Object.entries(this.filtros)) if (v !== '') params.set(k, v);
                const resp = await fetch('/api/v1/admin/dispositivos?' + params, { credentials: 'same-origin' });
                if (!resp.ok) throw new Error('No se pudo cargar el listado');
                this.dispositivos = await resp.json();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        async cargarLocales() {
            // Solo locales activos: son los asignables a un dispositivo.
            const resp = await fetch('/api/v1/puntos-de-venta?tipo=local&activo=true', { credentials: 'same-origin' });
            if (resp.ok) this.locales = await resp.json();
        },

        limpiar() {
            this.filtros = { descripcion: '', punto_de_venta_id: '', activo: '', acceso_desde: '', acceso_hasta: '' };
            this.cargar();
        },

        abrirEdicion(d) {
            this.form = {
                abierto: true, guardando: false, id: d.id, uuid: d.uuid,
                descripcion: d.descripcion, punto_de_venta_id: d.punto_de_venta_id || '',
                observaciones: d.observaciones || '', activo: d.activo,
            };
        },

        async guardar() {
            this.form.guardando = true;
            try {
                const resp = await fetch(`/api/v1/admin/dispositivos/${this.form.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        descripcion: this.form.descripcion,
                        punto_de_venta_id: this.form.punto_de_venta_id ? Number(this.form.punto_de_venta_id) : null,
                        observaciones: this.form.observaciones || null,
                        activo: this.form.activo,
                    }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo guardar');
                }
                this.form.abierto = false;
                window.toast('Dispositivo actualizado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.form.guardando = false;
            }
        },

        async cambiarEstado(d, activo) {
            const accion = activo ? 'activar' : 'desactivar';
            if (!activo && !confirm(`¿Desactivar el dispositivo "${d.descripcion}"?`)) return;
            try {
                const resp = await fetch(`/api/v1/admin/dispositivos/${d.id}/${accion}`, {
                    method: 'PATCH', credentials: 'same-origin',
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo cambiar el estado');
                }
                window.toast(activo ? 'Dispositivo activado' : 'Dispositivo desactivado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },
    };
}
