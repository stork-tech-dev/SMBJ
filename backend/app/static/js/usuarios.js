/* ==========================================================================
   ABM de usuarios.

   Todo el estado es local; los datos salen siempre de /api/v1/usuarios.
   El filtrado, la paginación y las reglas de negocio están en el backend
   (Principios 1 y 5): acá no se filtra nada sobre datos ya cargados.
   ========================================================================== */

/* Abreviaturas de mes fijas y no `toLocaleDateString('es-AR', {month:'short'})`:
   ese resultado depende del locale del navegador (un Chrome en inglés daría
   "Oct", y algunas implementaciones agregan punto: "oct."). Con la constante
   la columna se ve igual en cualquier navegador. */
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
               'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

function abmUsuarios() {
    return {
        usuarios: [],
        roles: [],
        rolesAsignables: [],
        // Puntos de venta activos, de cualquier tipo, para el selector.
        puntosDeVentaAsignables: [],
        total: 0,
        pagina: 1,
        tamano: 10,
        cargando: false,

        // Los tres filtros del diseño de Figma. El backend acepta además
        // username, email y activo: se pueden reactivar sin tocar la API.
        // `activo: 'true'` = solo activos por defecto (ver components/switch_activos).
        filtros: { nombre: '', rol_id: '', local_asignado_id: '', activo: 'true' },

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
            fecha_nacimiento: '',
            celular: '',
            local_asignado_id: '',
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

                params.set('pagina', this.pagina);
                params.set('tamano', this.tamano);

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

        /**
         * Opciones del selector "Punto de Venta": todos los activos, de
         * cualquier tipo (local, centro de distribución u online).
         *
         * Usa el endpoint del propio módulo y no /puntos-de-venta, que
         * exige permiso de configuración: quien gestiona usuarios no
         * tiene por qué tenerlo.
         */
        async cargarPuntosDeVenta() {
            const resp = await fetch('/api/v1/usuarios/puntos-de-venta-asignables', {
                credentials: 'same-origin',
            });
            if (!resp.ok) return;
            this.puntosDeVentaAsignables = await resp.json();
        },

        limpiar() {
            this.filtros = { nombre: '', rol_id: '', local_asignado_id: '', activo: 'true' };
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

        /**
         * Fecha sin hora en dd/mm/yyyy, como en el diseño ("06/10/1995").
         *
         * La API manda "1995-10-06" (Principio 1: datos crudos). Se parte
         * el string en lugar de usar new Date(): esa fecha se interpreta
         * como UTC y en Argentina (UTC-3) mostraría el día anterior.
         */
        formatearFechaCorta(iso) {
            if (!iso) return '—';
            const [anio, mes, dia] = iso.split('-');
            return `${dia}/${mes}/${anio}`;
        },

        /**
         * Cumpleaños en dd-mmm ("06-oct"), para la columna del listado.
         *
         * Sin el año a propósito: en la tabla el dato sirve como
         * recordatorio de cumpleaños, no como fecha de nacimiento. El
         * año completo se ve en el panel "Ver".
         *
         * Parte el string por el mismo motivo que formatearFechaCorta:
         * new Date("1995-10-06") se interpreta como UTC y en Argentina
         * mostraría el día anterior.
         */
        formatearCumple(iso) {
            if (!iso) return '—';
            const [, mes, dia] = iso.split('-');
            return `${dia}-${MESES[Number(mes) - 1]}`;
        },

        /* --- Alta y edición --- */

        abrirAlta() {
            this.form = {
                abierto: true, guardando: false, id: null,
                nombre: '', username: '', email: '',
                rol_id: this.rolesAsignables[0]?.id || '', password: '',
                activo: true,
                fecha_nacimiento: '', celular: '', local_asignado_id: '',
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
                // input type="date" espera ISO (yyyy-mm-dd), que es
                // justo lo que devuelve la API.
                fecha_nacimiento: usuario.fecha_nacimiento || '',
                celular: usuario.celular || '',
                local_asignado_id: usuario.local_asignado_id || '',
            };
            this.asegurarPuntoDeVentaActual(usuario);
            this.cargarAccesos();
        },

        /**
         * Mete en el desplegable el punto de venta que el usuario ya tiene,
         * si no está en la lista.
         *
         * Pasa cuando se lo desactivó después de asignárselo: el endpoint
         * solo devuelve los activos, así que sin esto el campo se vería
         * vacío y parecería que el usuario no tiene ninguno. El backend deja
         * conservarlo —lo que prohíbe es asignar uno inactivo—, y el dato ya
         * viene en la respuesta del usuario.
         */
        asegurarPuntoDeVentaActual(usuario) {
            const actual = usuario.local_asignado;
            if (!actual) return;
            if (this.puntosDeVentaAsignables.some((p) => p.id === actual.id)) return;
            this.puntosDeVentaAsignables = [
                ...this.puntosDeVentaAsignables,
                { id: actual.id, nombre: `${actual.nombre} (inactivo)` },
            ];
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
                    // Los tres campos personales viajan siempre, también
                    // en null: así el backend distingue "vaciar el campo"
                    // de "no lo mandaron" y se pueden borrar desde el form.
                    fecha_nacimiento: this.form.fecha_nacimiento || null,
                    celular: this.form.celular || null,
                    local_asignado_id: this.form.local_asignado_id
                        ? Number(this.form.local_asignado_id)
                        : null,
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
