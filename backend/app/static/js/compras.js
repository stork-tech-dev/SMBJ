/**
 * Listado de compras cerradas + banner de borrador activo.
 */
function abmCompras() {
    return {
        filas: [],
        total: 0,
        pagina: 1,
        tamano: 10,
        cargando: false,
        borrador: null,
        proveedores: [],

        filtros: {
            proveedor_id: '',
        },

        async cargar() {
            this.cargando = true;
            try {
                // Borrador del usuario actual.
                const rb = await fetch('/api/v1/compras/borrador', { credentials: 'same-origin' });
                if (rb.ok) {
                    this.borrador = await rb.json();
                } else {
                    this.borrador = null;
                }

                // Listado de cerradas.
                const params = new URLSearchParams();
                if (this.filtros.proveedor_id) params.set('proveedor_id', this.filtros.proveedor_id);
                params.set('pagina', this.pagina);
                params.set('tamano', this.tamano);
                const rl = await fetch(`/api/v1/compras?${params}`, { credentials: 'same-origin' });
                if (rl.ok) {
                    const data = await rl.json();
                    this.filas = data.resultados;
                    this.total = data.total;
                }

                // Proveedores para el filtro.
                if (!this.proveedores.length) {
                    const rp = await fetch('/api/v1/proveedores?tamano=200', { credentials: 'same-origin' });
                    if (rp.ok) {
                        const dp = await rp.json();
                        this.proveedores = dp.resultados || dp;
                    }
                }
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        limpiarFiltros() {
            this.filtros.proveedor_id = '';
            this.cargar();
        },

        /* --- Modal confirmación genérica --- */
        confirmacion: {
            abierta: false, titulo: '', mensaje: '',
            _cb: null,
            accion() { if (this._cb) this._cb(); this.abierta = false; },
        },

        eliminarBorrador() {
            if (!this.borrador) return;
            this.confirmacion.titulo = 'Eliminar borrador';
            this.confirmacion.mensaje = '¿Eliminar el borrador? Esta acción no se puede deshacer.';
            this.confirmacion._cb = async () => {
                try {
                    const resp = await fetch(`/api/v1/compras/${this.borrador.id}`, {
                        method: 'DELETE',
                        credentials: 'same-origin',
                    });
                    if (!resp.ok) {
                        const err = await resp.json().catch(() => ({}));
                        throw new Error(err.detail || 'No se pudo eliminar');
                    }
                    window.toast('Borrador eliminado', 'exito');
                    this.borrador = null;
                } catch (e) {
                    window.toast(e.message, 'error');
                }
            };
            this.confirmacion.abierta = true;
        },
    };
}
