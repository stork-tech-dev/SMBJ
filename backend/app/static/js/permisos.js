/* ==========================================================================
   Componente Alpine del árbol de permisos.

   Lo usan por igual la pantalla de permisos de un rol y la de overrides de
   un usuario. La única diferencia es `modo`:

     'rol'     → todos los checkboxes editables
     'usuario' → lo heredado del rol queda bloqueado y en gris; el usuario
                 solo puede AGREGAR overrides, nunca quitar permisos
   ========================================================================== */

function arbolPermisos(urlDatos, urlGuardar, modo) {
    return {
        modo,
        arbol: [],
        expandidos: {},
        cargando: false,
        guardando: false,
        sucio: false,

        // Diálogo de confirmación (components/modal_confirmacion).
        confirmacion: { abierta: false, titulo: '', mensaje: '', accion: () => {} },

        acciones: ['ver', 'crear', 'editar', 'eliminar'],
        etiquetas: {
            ver: 'Ver',
            crear: 'Crear',
            editar: 'Editar',
            eliminar: 'Eliminar',
        },

        /**
         * Aplana el árbol en filas para renderizar con un solo x-for:
         * cada módulo, seguido de sus recursos si está expandido.
         */
        get filas() {
            const filas = [];
            for (const nodo of this.arbol) {
                filas.push({ clave: nodo.modulo, tipo: 'modulo', nodo, padre: null });
                if (this.expandidos[nodo.modulo]) {
                    for (const recurso of nodo.recursos) {
                        filas.push({
                            clave: nodo.modulo + '/' + recurso.recurso,
                            tipo: 'recurso',
                            nodo: recurso,
                            padre: nodo,
                        });
                    }
                }
            }
            return filas;
        },

        async cargar() {
            this.cargando = true;
            try {
                const resp = await fetch(urlDatos, { credentials: 'same-origin' });
                if (!resp.ok) throw new Error('No se pudo cargar el árbol de permisos');
                this.arbol = await resp.json();
                this.sucio = false;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        abierto(nodo) {
            return !!this.expandidos[nodo.modulo];
        },

        alternar(nodo) {
            if (!nodo.recursos.length) return;
            this.expandidos[nodo.modulo] = !this.expandidos[nodo.modulo];
        },

        expandirTodo(valor) {
            for (const nodo of this.arbol) {
                if (nodo.recursos.length) this.expandidos[nodo.modulo] = valor;
            }
        },

        /* --- Estado de cada checkbox --- */

        // En modo usuario el checkbox refleja el permiso efectivo, que ya
        // incluye lo heredado; en modo rol, el permiso del rol.
        marcado(nodo, accion) {
            return nodo['puede_' + accion] === true;
        },

        // Lo que viene del rol no se edita desde la pantalla de overrides:
        // los overrides solo agregan.
        bloqueado(nodo, accion) {
            if (this.modo !== 'usuario') return false;
            return nodo['heredado_' + accion] === true;
        },

        cambiar(nodo, accion, valor, padre) {
            nodo['puede_' + accion] = valor;
            if (this.modo === 'usuario') {
                nodo['override_' + accion] = valor;
            }

            // Marcar el permiso general del módulo sugiere marcar sus
            // recursos, pero cada uno sigue siendo editable por separado.
            if (!padre && nodo.recursos && valor) {
                for (const recurso of nodo.recursos) {
                    if (recurso['puede_' + accion] === null) continue;
                    if (this.bloqueado(recurso, accion)) continue;
                    recurso['puede_' + accion] = true;
                    if (this.modo === 'usuario') recurso['override_' + accion] = true;
                }
            }

            this.sucio = true;
        },

        /* --- Guardado explícito, con confirmación --- */

        /**
         * Pide confirmación antes de guardar el árbol de permisos.
         *
         * Antes usaba el `confirm()` del navegador. El diálogo del sistema
         * además deja decir de quién son los permisos que se están tocando:
         * esta pantalla sirve tanto para un rol como para un usuario, y con
         * el cartel de Chrome no había forma de aclararlo.
         */
        confirmarGuardado() {
            this.confirmacion = {
                abierta: true,
                titulo: 'Guardar permisos',
                mensaje: this.modo === 'usuario'
                    ? '¿Guardar los permisos de este usuario? Cambian lo que puede hacer '
                      + 'apenas se aplique. Queda auditado.'
                    : '¿Guardar los permisos de este rol? Cambian para TODOS los usuarios '
                      + 'que lo tengan asignado. Queda auditado.',
                accion: () => this.guardar(),
            };
        },

        // Arma el payload que espera la API: una fila por módulo y una por
        // recurso. En modo usuario se mandan solo los overrides, porque lo
        // heredado del rol no se persiste como override.
        _payload() {
            const campo = this.modo === 'usuario' ? 'override_' : 'puede_';
            const permisos = [];

            const fila = (modulo, recurso, nodo) => ({
                modulo,
                recurso,
                puede_ver: nodo[campo + 'ver'] === true,
                puede_crear: nodo[campo + 'crear'] === true,
                puede_editar: nodo[campo + 'editar'] === true,
                puede_eliminar: nodo[campo + 'eliminar'] === true,
            });

            for (const nodo of this.arbol) {
                permisos.push(fila(nodo.modulo, null, nodo));
                for (const recurso of nodo.recursos) {
                    permisos.push(fila(nodo.modulo, recurso.recurso, recurso));
                }
            }
            return { permisos };
        },

        async guardar() {
            this.confirmacion.abierta = false;
            this.guardando = true;
            try {
                const resp = await fetch(urlGuardar, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify(this._payload()),
                });
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudieron guardar los permisos');
                }
                this.arbol = await resp.json();
                this.sucio = false;
                window.toast('Permisos guardados', 'exito');
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.guardando = false;
            }
        },
    };
}
