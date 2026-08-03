/* ==========================================================================
   ABM de roles (Cuenta Maestra).
   ========================================================================== */

function abmRoles() {
    return {
        roles: [],
        cargando: false,
        filtros: { nombre: '', activo: '', es_sistema: '' },

        form: {
            abierto: false, guardando: false,
            id: null, nombre: '', descripcion: '', es_sistema: false,
        },

        confirmacion: {
            abierta: false, titulo: '', mensaje: '', advertencia: '', accion: () => {},
        },

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams();
                for (const [clave, valor] of Object.entries(this.filtros)) {
                    if (valor !== '') params.set(clave, valor);
                }

                const resp = await fetch('/api/v1/roles?' + params, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo cargar el listado de roles');
                this.roles = await resp.json();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        limpiar() {
            this.filtros = { nombre: '', activo: '', es_sistema: '' };
            this.cargar();
        },

        abrirAlta() {
            this.form = {
                abierto: true, guardando: false,
                id: null, nombre: '', descripcion: '', es_sistema: false,
            };
        },

        abrirEdicion(rol) {
            this.form = {
                abierto: true, guardando: false,
                id: rol.id,
                nombre: rol.nombre,
                descripcion: rol.descripcion || '',
                es_sistema: rol.es_sistema,
            };
        },

        async guardar() {
            this.form.guardando = true;
            try {
                const esAlta = !this.form.id;
                const cuerpo = { descripcion: this.form.descripcion || null };
                // En roles del sistema no se manda el nombre: la API lo rechazaría.
                if (esAlta || !this.form.es_sistema) cuerpo.nombre = this.form.nombre;

                const resp = await fetch(
                    esAlta ? '/api/v1/roles' : '/api/v1/roles/' + this.form.id,
                    {
                        method: esAlta ? 'POST' : 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify(cuerpo),
                    }
                );
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo guardar el rol');
                }

                this.form.abierto = false;
                window.toast(esAlta ? 'Rol creado' : 'Rol actualizado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.form.guardando = false;
            }
        },

        confirmarEstado(rol) {
            const desactivando = rol.activo;
            this.confirmacion = {
                abierta: true,
                titulo: desactivando ? 'Desactivar rol' : 'Activar rol',
                mensaje: desactivando
                    ? `¿Desactivar el rol "${rol.nombre}"?`
                    : `¿Activar el rol "${rol.nombre}"?`,
                // Advertencia explícita si tiene usuarios: la API lo rechaza.
                advertencia:
                    desactivando && rol.cantidad_usuarios > 0
                        ? `Tiene ${rol.cantidad_usuarios} usuario(s) asociado(s). ` +
                          'Si alguno está activo, la operación será rechazada.'
                        : '',
                accion: () => this.cambiarEstado(rol, !rol.activo),
            };
        },

        // SIN USO DESDE LA PANTALLA. El botón "Eliminar" se sacó del listado:
        // en un rol nuevo convivía con la papelera de baja y se leían como
        // dos formas de hacer lo mismo. Se conserva —junto con eliminar()—
        // porque el borrado real sigue existiendo en la API y puede volver a
        // exponerse, pero desde el modal de edición, no como otra papelera
        // en la fila.
        confirmarBaja(rol) {
            this.confirmacion = {
                abierta: true,
                titulo: 'Eliminar rol',
                mensaje: `¿Eliminar el rol "${rol.nombre}"? La acción queda auditada.`,
                advertencia:
                    rol.cantidad_usuarios > 0
                        ? `Tiene ${rol.cantidad_usuarios} usuario(s) asociado(s): la operación será rechazada.`
                        : '',
                accion: () => this.eliminar(rol),
            };
        },

        async _accion(url, opciones, mensajeOk) {
            this.confirmacion.abierta = false;
            try {
                const resp = await fetch(url, { credentials: 'same-origin', ...opciones });
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo completar la operación');
                }
                window.toast(mensajeOk, 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        cambiarEstado(rol, activo) {
            return this._accion(
                `/api/v1/roles/${rol.id}/estado`,
                {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ activo }),
                },
                activo ? 'Rol activado' : 'Rol desactivado'
            );
        },

        eliminar(rol) {
            return this._accion(`/api/v1/roles/${rol.id}`, { method: 'DELETE' }, 'Rol eliminado');
        },
    };
}
