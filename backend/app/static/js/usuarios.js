/* ==========================================================================
   ABM de usuarios.

   Todo el estado es local; los datos salen siempre de /api/v1/usuarios.
   El filtrado, la paginación y las reglas de negocio están en el backend
   (Principios 1 y 5): acá no se filtra nada sobre datos ya cargados.
   ========================================================================== */

function abmUsuarios() {
    return {
        usuarios: [],
        roles: [],
        rolesAsignables: [],
        total: 0,
        cargando: false,

        // Los tres filtros del diseño de Figma. El backend acepta además
        // username, email y activo: se pueden reactivar sin tocar la API.
        filtros: { nombre: '', rol_id: '' },

        detalle: { abierto: false, usuario: null },

        form: {
            abierto: false,
            guardando: false,
            id: null,
            nombre: '',
            username: '',
            email: '',
            rol_id: '',
            password: '',
            activo: true,
        },

        // Sección "Accesos permitidos": catálogo plano de permisos, con lo
        // heredado del perfil y lo que se agrega a este usuario.
        accesos: [],
        cargandoAccesos: false,

        confirmacion: { abierta: false, titulo: '', mensaje: '', accion: () => {} },

        async cargar() {
            this.cargando = true;
            try {
                // Los filtros vacíos no se mandan: la API los interpreta
                // como "sin filtrar".
                const params = new URLSearchParams();
                for (const [clave, valor] of Object.entries(this.filtros)) {
                    if (valor !== '' && valor !== null) params.set(clave, valor);
                }

                const resp = await fetch('/api/v1/usuarios?' + params, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo cargar el listado');

                const datos = await resp.json();
                this.usuarios = datos.resultados;
                this.total = datos.total;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        async cargarRoles() {
            const resp = await fetch('/api/v1/usuarios/roles-asignables', {
                credentials: 'same-origin',
            });
            if (!resp.ok) return;
            this.rolesAsignables = await resp.json();
            // El filtro por rol muestra los mismos que se pueden asignar.
            this.roles = this.rolesAsignables;
        },

        limpiar() {
            this.filtros = { nombre: '', rol_id: '' };
            this.cargar();
        },

        /* --- Detalle (botón "Ver") --- */

        abrirDetalle(usuario) {
            this.detalle = { abierto: true, usuario };
        },

        // La API devuelve el timestamp crudo: formatearlo es tarea del
        // frontend (Principio 1). Formato del sistema: dd/mm/yy hh:mm.
        formatearFecha(iso) {
            if (!iso) return 'Nunca ingresó';
            return new Date(iso).toLocaleString('es-AR', {
                day: '2-digit', month: '2-digit', year: '2-digit',
                hour: '2-digit', minute: '2-digit', hour12: false,
            });
        },

        /* --- Alta y edición --- */

        abrirAlta() {
            this.form = {
                abierto: true, guardando: false, id: null,
                nombre: '', username: '', email: '',
                rol_id: this.rolesAsignables[0]?.id || '', password: '',
                activo: true,
            };
            this.cargarAccesos();
        },

        abrirEdicion(usuario) {
            this.form = {
                abierto: true, guardando: false,
                id: usuario.id,
                nombre: usuario.nombre,
                username: usuario.username,
                email: usuario.email || '',
                rol_id: usuario.rol_id,
                password: '',
                activo: usuario.activo,
            };
            this.cargarAccesos();
        },

        /* --- Accesos permitidos --- */

        /**
         * Carga el catálogo de accesos.
         *
         * En edición se piden los del usuario (heredados + individuales).
         * En el alta todavía no hay usuario, así que se piden los del
         * perfil elegido: muestran lo que va a heredar. Por eso también se
         * vuelve a llamar al cambiar el selector de perfil.
         */
        async cargarAccesos() {
            const url = this.form.id
                ? `/api/v1/usuarios/${this.form.id}/accesos`
                : `/api/v1/usuarios/accesos?rol_id=${this.form.rol_id}`;

            if (!this.form.id && !this.form.rol_id) {
                this.accesos = [];
                return;
            }

            // Al cambiar de perfil se conservan las marcas individuales que
            // el usuario ya hizo en el formulario, para no perder su trabajo.
            const marcadosAntes = new Set(
                this.accesos.filter((a) => a.override).map((a) => a.clave)
            );

            this.cargandoAccesos = true;
            try {
                const resp = await fetch(url, { credentials: 'same-origin' });
                if (!resp.ok) throw new Error('No se pudieron cargar los accesos');

                const datos = await resp.json();
                this.accesos = datos.map((a) => ({
                    ...a,
                    override: a.override || marcadosAntes.has(a.clave),
                }));
            } catch (e) {
                window.toast(e.message, 'error');
                this.accesos = [];
            } finally {
                this.cargandoAccesos = false;
            }
        },

        /** Guarda los accesos individuales de un usuario ya existente. */
        async guardarAccesos(usuarioId) {
            const marcados = this.accesos
                .filter((a) => a.override && !a.heredado)
                .map((a) => a.clave);

            const resp = await fetch(`/api/v1/usuarios/${usuarioId}/accesos`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ accesos: marcados }),
            });
            if (!resp.ok) {
                const error = await resp.json().catch(() => ({}));
                throw new Error(error.detail || 'El usuario se guardó, pero fallaron los accesos');
            }
        },

        async guardar() {
            this.form.guardando = true;
            try {
                const esAlta = !this.form.id;
                const cuerpo = {
                    nombre: this.form.nombre,
                    email: this.form.email || null,
                    rol_id: Number(this.form.rol_id),
                };
                if (esAlta) cuerpo.username = this.form.username;
                // En edición, contraseña vacía = no cambiarla.
                if (this.form.password) cuerpo.password = this.form.password;

                const resp = await fetch(
                    esAlta ? '/api/v1/usuarios' : '/api/v1/usuarios/' + this.form.id,
                    {
                        method: esAlta ? 'POST' : 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify(cuerpo),
                    }
                );

                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo guardar el usuario');
                }

                // Los accesos se guardan en un segundo paso: en el alta el
                // usuario recién existe (y tiene id) después del POST.
                const guardado = await resp.json();
                await this.guardarAccesos(guardado.id);

                this.form.abierto = false;
                window.toast(esAlta ? 'Usuario creado' : 'Usuario actualizado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.form.guardando = false;
            }
        },

        /* --- Activar / desactivar, siempre con confirmación --- */

        confirmarEstado(usuario) {
            const desactivando = usuario.activo;
            this.confirmacion = {
                abierta: true,
                titulo: desactivando ? 'Desactivar usuario' : 'Activar usuario',
                mensaje: desactivando
                    ? `¿Desactivar a ${usuario.nombre}? Se cerrarán sus sesiones abiertas y no podrá ingresar. La acción queda auditada.`
                    : `¿Activar a ${usuario.nombre}? Podrá volver a ingresar al sistema.`,
                accion: () => this.cambiarEstado(usuario, !usuario.activo),
            };
        },

        async cambiarEstado(usuario, activo) {
            this.confirmacion.abierta = false;
            try {
                const resp = await fetch(`/api/v1/usuarios/${usuario.id}/estado`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ activo }),
                });
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo cambiar el estado');
                }
                window.toast(activo ? 'Usuario activado' : 'Usuario desactivado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },
    };
}
