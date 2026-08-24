/* ==========================================================================
   ABM de clientes.

   Los puntos NO se calculan acá: vienen resueltos por el backend, que los
   suma de `puntos_cliente`. Repetir esa suma en JavaScript sería tener dos
   versiones de la misma regla, y la del navegador terminaría desactualizada.

   La corrección de un saldo mal cargado se hace con un movimiento nuevo de
   tipo ajuste, nunca editando los anteriores: la tabla es de solo inserción
   y la base lo hace cumplir con un trigger.
   ========================================================================== */

const URL_CLIENTES = '/api/v1/clientes';

function abmClientes() {
    return {
        clientes: [],
        cargando: false,
        total: 0,
        pagina: 1,
        tamano: 50,

        filtros: { busqueda: '', localidad: '', activo: 'true' },

        form: {
            abierto: false, guardando: false, id: null,
            nombre: '', dni: '', domicilio: '', codigo_postal: '',
            localidad: '', telefono: '', email: '',
        },

        ficha: { abierta: false, datos: null, puntos: [] },
        ajuste: { cantidad: null, descripcion: '' },

        pesos: (v) => window.pesos(v),

        get paginas() {
            return Math.max(1, Math.ceil(this.total / this.tamano));
        },

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams({
                    pagina: this.pagina,
                    tamano: this.tamano,
                });
                for (const [k, v] of Object.entries(this.filtros)) {
                    if (v !== '') params.set(k, v);
                }

                const resp = await fetch(`${URL_CLIENTES}?${params}`, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo cargar el listado');

                const datos = await resp.json();
                this.clientes = datos.resultados;
                this.total = datos.total;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        /* Cambiar un filtro vuelve a la página 1: quedarse en la 3 de un
           resultado que ahora tiene una sola página muestra una tabla vacía
           sin decir por qué. */
        buscar() {
            this.pagina = 1;
            this.cargar();
        },

        irA(pagina) {
            if (pagina < 1 || pagina > this.paginas) return;
            this.pagina = pagina;
            this.cargar();
        },

        /* "Limpiar" vuelve al estado de entrada, no a "mostrar todo": si
           reseteara `activo` a vacío traería los desactivados, que es lo
           contrario de lo que espera quien limpia para volver a empezar. */
        limpiar() {
            this.filtros = { busqueda: '', localidad: '', activo: 'true' };
            this.buscar();
        },

        /* --- Alta y edición --- */

        abrirAlta() {
            this.form = {
                abierto: true, guardando: false, id: null,
                nombre: '', dni: '', domicilio: '', codigo_postal: '',
                localidad: '', telefono: '', email: '',
            };
        },

        abrirEdicion(c) {
            this.form = {
                abierto: true, guardando: false, id: c.id,
                nombre: c.nombre || '', dni: c.dni || '',
                domicilio: c.domicilio || '', codigo_postal: c.codigo_postal || '',
                localidad: c.localidad || '', telefono: c.telefono || '',
                email: c.email || '',
            };
        },

        async guardar() {
            this.form.guardando = true;
            try {
                const alta = !this.form.id;
                const { abierto, guardando, id, ...campos } = this.form;

                const resp = await fetch(
                    alta ? URL_CLIENTES : `${URL_CLIENTES}/${id}`,
                    {
                        method: alta ? 'POST' : 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        // Los vacíos viajan como null y no como '': en la
                        // edición, un string vacío se guardaría tal cual y
                        // la ficha mostraría un campo "cargado" sin nada.
                        body: JSON.stringify(
                            Object.fromEntries(
                                Object.entries(campos).map(([k, v]) => [k, v || null])
                            )
                        ),
                    }
                );
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo guardar');
                }

                this.form.abierto = false;
                window.toast(alta ? 'Cliente creado' : 'Cliente actualizado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.form.guardando = false;
            }
        },

        /* Baja lógica: no hay borrado. Las ventas, las señas y los puntos
           apuntan al cliente. */
        async cambiarEstado(c, activo) {
            try {
                const resp = await fetch(`${URL_CLIENTES}/${c.id}/estado`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ activo }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo cambiar el estado');
                }
                window.toast(activo ? 'Cliente activado' : 'Cliente desactivado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        /* --- Ficha --- */

        async abrirFicha(c) {
            this.ficha = { abierta: true, datos: null, puntos: [] };
            this.ajuste = { cantidad: null, descripcion: '' };
            await this.recargarFicha(c.id);
        },

        async recargarFicha(clienteId) {
            try {
                // Las dos en paralelo: la ficha no puede dibujarse hasta
                // tener las dos, y encadenarlas duplicaría la espera.
                const [ficha, puntos] = await Promise.all([
                    fetch(`${URL_CLIENTES}/${clienteId}`, { credentials: 'same-origin' }),
                    fetch(`${URL_CLIENTES}/${clienteId}/puntos`, { credentials: 'same-origin' }),
                ]);
                if (!ficha.ok) throw new Error('No se pudo cargar la ficha');

                this.ficha.datos = await ficha.json();
                this.ficha.puntos = puntos.ok ? await puntos.json() : [];
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        async ajustarPuntos() {
            const clienteId = this.ficha.datos?.id;
            if (!clienteId) return;

            try {
                const resp = await fetch(`${URL_CLIENTES}/${clienteId}/puntos/ajuste`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        cantidad: Number(this.ajuste.cantidad),
                        descripcion: this.ajuste.descripcion,
                    }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo ajustar');
                }

                window.toast('Puntos ajustados', 'exito');
                this.ajuste = { cantidad: null, descripcion: '' };
                await this.recargarFicha(clienteId);
                // El listado muestra el saldo en su columna: sin esto, la
                // fila de atrás quedaría con el número viejo.
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },
    };
}
