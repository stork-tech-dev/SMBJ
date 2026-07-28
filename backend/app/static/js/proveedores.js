/* ==========================================================================
   ABM de proveedores.

   Estado local; datos siempre desde /api/v1/proveedores. Filtrado,
   validaciones y reglas de negocio en el backend (Principios 1 y 5).
   ========================================================================== */

function abmProveedores() {
    return {
        proveedores: [],
        cargando: false,
        filtros: { razon_social: '', estado: '', dolar_desde: '', dolar_hasta: '' },

        form: {
            abierto: false, guardando: false, id: null,
            razon_social: '', telefono: '', email: '', direccion: '', notas: '',
            dolar_actual: '',
        },

        ficha: { abierta: false, proveedor: null, historial: [], nuevoDolar: '', guardandoDolar: false },

        baja: { abierta: false, proveedor: null, estado: 'desactivado', advertencia: '', procesando: false },

        /* --- Presentación --- */

        formatearDolar(v) {
            if (v === null || v === undefined || v === '') return '—';
            return Number(v).toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        },

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
            this.filtros = { razon_social: '', estado: '', dolar_desde: '', dolar_hasta: '' };
            this.cargar();
        },

        /* --- Alta / edición --- */

        abrirAlta() {
            this.form = {
                abierto: true, guardando: false, id: null,
                razon_social: '', telefono: '', email: '', direccion: '', notas: '',
                dolar_actual: '',
            };
        },

        abrirEdicion(p) {
            this.form = {
                abierto: true, guardando: false, id: p.id,
                razon_social: p.razon_social, telefono: p.telefono || '',
                email: p.email || '', direccion: p.direccion || '', notas: p.notas || '',
                dolar_actual: p.dolar_actual,
            };
        },

        async guardar() {
            this.form.guardando = true;
            try {
                const alta = !this.form.id;
                const cuerpo = {
                    razon_social: this.form.razon_social,
                    telefono: this.form.telefono || null,
                    email: this.form.email || null,
                    direccion: this.form.direccion || null,
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

        /* --- Ficha, dólar e historial --- */

        async abrirFicha(p) {
            this.ficha = { abierta: true, proveedor: p, historial: [], nuevoDolar: '', guardandoDolar: false };
            await this.cargarHistorial(p.id);
        },

        async cargarHistorial(id) {
            const resp = await fetch(`/api/v1/proveedores/${id}/dolar/historial`, { credentials: 'same-origin' });
            if (resp.ok) this.ficha.historial = await resp.json();
        },

        async cambiarDolar() {
            this.ficha.guardandoDolar = true;
            try {
                const resp = await fetch(`/api/v1/proveedores/${this.ficha.proveedor.id}/dolar`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ valor_nuevo: this.ficha.nuevoDolar }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo actualizar el dólar');
                }
                this.ficha.proveedor = await resp.json();
                this.ficha.nuevoDolar = '';
                await this.cargarHistorial(this.ficha.proveedor.id);
                window.toast('Dólar actualizado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.ficha.guardandoDolar = false;
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
