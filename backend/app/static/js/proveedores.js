/* ==========================================================================
   ABM de proveedores.

   Estado local; datos siempre desde /api/v1/proveedores. Filtrado,
   validaciones y reglas de negocio en el backend (Principios 1 y 5).
   ========================================================================== */

function abmProveedores() {
    return {
        proveedores: [],
        cargando: false,
        // El estado arranca en 'activo': la pantalla del día a día muestra solo
        // los proveedores operativos. Acá el filtro es un select y no el switch
        // "Solo activos" de los otros listados, porque hay TRES estados
        // (activo, desactivado, inhabilitado) y un sí/no no los distingue.
        filtros: { nombre: '', estado: 'activo', dolar_desde: '', dolar_hasta: '' },

        // El cambio de dólar y su historial viven en el FORMULARIO, no en la
        // ficha: la ficha es de consulta y muestra el valor actual sin más.
        form: {
            abierto: false, guardando: false, id: null,
            nombre: '', pais: '', telefono: '', email: '', provincia: '', notas: '',
            dolar_actual: '',
            historial: [], nuevoDolar: '', guardandoDolar: false,
        },

        ficha: { abierta: false, proveedor: null },

        baja: { abierta: false, proveedor: null, estado: 'desactivado', advertencia: '', procesando: false },

        /* --- Presentación --- */

        // Delega en el helper global: estaba copiado acá y en la otra
        // pantalla, y las dos copias tenían que cambiar juntas.
        formatearDolar: window.formatearDolar,

        formatearFecha(iso) {
            if (!iso) return '—';
            return new Date(iso).toLocaleString('es-AR', {
                day: '2-digit', month: '2-digit', year: '2-digit',
                hour: '2-digit', minute: '2-digit', hour12: false,
            });
        },

        etiquetaEstado(e) {
            return { activo: 'Activo', desactivado: 'Desactivado', inhabilitado: 'Inhabilitado' }[e] || e;
        },

        colorEstado(e) {
            return e === 'activo' ? 'text-success' : (e === 'inhabilitado' ? 'text-danger' : 'text-texto-muted');
        },

        etiquetaOrigen(o) {
            return {
                manual: 'Manual', masivo_valor: 'Masivo (valor)',
                masivo_porcentaje: 'Masivo (%)', importacion_excel: 'Excel',
            }[o] || o;
        },

        /* --- Listado --- */

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams();
                for (const [k, v] of Object.entries(this.filtros)) {
                    if (v !== '' && v !== null) params.set(k, v);
                }
                const resp = await fetch('/api/v1/proveedores?' + params, { credentials: 'same-origin' });
                if (!resp.ok) throw new Error('No se pudo cargar el listado');
                this.proveedores = await resp.json();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        limpiar() {
            this.filtros = { nombre: '', estado: 'activo', dolar_desde: '', dolar_hasta: '' };
            this.cargar();
        },

        /* --- Alta / edición --- */

        abrirAlta() {
            this.form = {
                abierto: true, guardando: false, id: null,
                nombre: '', pais: '', telefono: '', email: '', provincia: '', notas: '',
                dolar_actual: '',
                historial: [], nuevoDolar: '', guardandoDolar: false,
            };
        },

        async abrirEdicion(p) {
            this.form = {
                abierto: true, guardando: false, id: p.id,
                nombre: p.nombre, pais: p.pais || '', telefono: p.telefono || '',
                email: p.email || '', provincia: p.provincia || '', notas: p.notas || '',
                dolar_actual: p.dolar_actual,
                historial: [], nuevoDolar: '', guardandoDolar: false,
            };
            await this.cargarHistorial(p.id);
        },

        async guardar() {
            this.form.guardando = true;
            try {
                const alta = !this.form.id;
                const cuerpo = {
                    nombre: this.form.nombre,
                    pais: this.form.pais || null,
                    telefono: this.form.telefono || null,
                    email: this.form.email || null,
                    provincia: this.form.provincia || null,
                    notas: this.form.notas || null,
                };
                if (alta) cuerpo.dolar_actual = this.form.dolar_actual;

                const resp = await fetch(
                    alta ? '/api/v1/proveedores' : '/api/v1/proveedores/' + this.form.id,
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
                window.toast(alta ? 'Proveedor creado' : 'Proveedor actualizado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.form.guardando = false;
            }
        },

        /* --- Ficha: solo consulta --- */

        abrirFicha(p) {
            this.ficha = { abierta: true, proveedor: p };
        },

        /* --- Dólar e historial: dentro de la edición --- */

        async cargarHistorial(id) {
            const resp = await fetch(`/api/v1/proveedores/${id}/dolar/historial`, { credentials: 'same-origin' });
            if (resp.ok) this.form.historial = await resp.json();
        },

        async cambiarDolar() {
            this.form.guardandoDolar = true;
            try {
                const resp = await fetch(`/api/v1/proveedores/${this.form.id}/dolar`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ valor_nuevo: this.form.nuevoDolar }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo actualizar el dólar');
                }
                const actualizado = await resp.json();
                this.form.dolar_actual = actualizado.dolar_actual;
                this.form.nuevoDolar = '';
                await this.cargarHistorial(this.form.id);
                window.toast('Dólar actualizado', 'exito');
                // Recarga la tabla: el cambio de dólar recalcula los precios
                // de todos los productos del proveedor.
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.form.guardandoDolar = false;
            }
        },

        /* --- Baja / reactivación --- */

        abrirBaja(p) {
            this.baja = { abierta: true, proveedor: p, estado: 'desactivado', advertencia: '', procesando: false };
        },

        async confirmarBaja() {
            this.baja.procesando = true;
            try {
                // Si ya hubo advertencia de productos activos, se confirma la baja igual.
                const resp = await this._patchEstado(
                    this.baja.proveedor.id, this.baja.estado, !!this.baja.advertencia
                );
                if (resp.status === 409) {
                    // Productos activos: mostrar la advertencia y esperar 2da confirmación.
                    const err = await resp.json();
                    this.baja.advertencia = err.detail;
                    return;
                }
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo dar de baja');
                }
                this.baja.abierta = false;
                window.toast('Proveedor dado de baja', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.baja.procesando = false;
            }
        },

        async reactivar(p) {
            const resp = await this._patchEstado(p.id, 'activo', false);
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                window.toast(err.detail || 'No se pudo reactivar', 'error');
                return;
            }
            window.toast('Proveedor reactivado', 'exito');
            this.cargar();
        },

        _patchEstado(id, estado, confirmar) {
            return fetch(`/api/v1/proveedores/${id}/estado`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ estado, confirmar_con_productos: confirmar }),
            });
        },
    };
}
