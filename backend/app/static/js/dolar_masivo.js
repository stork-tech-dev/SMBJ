/* ==========================================================================
   Cambio masivo del dólar: modo manual (valor/porcentaje) con preview, e
   importación por Excel. El preview y el resultado los calcula el backend,
   para no repetir el redondeo del lado del cliente (Principio 1).
   ========================================================================== */

function dolarMasivo() {
    return {
        proveedores: [],
        modalidad: 'valor',
        valor: '',
        seleccion: [],
        todos: true,
        preview: [],
        aplicando: false,

        archivo: null,
        errores: [],
        importando: false,

        // Delega en el helper global: estaba copiado acá y en la otra
        // pantalla, y las dos copias tenían que cambiar juntas.
        formatearDolar: window.formatearDolar,

        async cargar() {
            const resp = await fetch('/api/v1/proveedores?estado=activo', { credentials: 'same-origin' });
            if (resp.ok) this.proveedores = await resp.json();
        },

        // ids seleccionados, o null si es "todos".
        _ids() {
            return this.todos ? null : this.seleccion.map(Number);
        },

        async calcularPreview() {
            if (this.valor === '' || (!this.todos && !this.seleccion.length)) {
                this.preview = [];
                return;
            }
            try {
                const resp = await fetch('/api/v1/proveedores/dolar/masivo/preview', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ proveedor_ids: this._ids(), modalidad: this.modalidad, valor: this.valor }),
                });
                this.preview = resp.ok ? await resp.json() : [];
            } catch (e) {
                this.preview = [];
            }
        },

        async aplicar() {
            if (!confirm(`¿Aplicar el cambio a ${this.preview.length} proveedor(es)? Queda auditado.`)) return;
            this.aplicando = true;
            try {
                const resp = await fetch('/api/v1/proveedores/dolar/masivo', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ proveedor_ids: this._ids(), modalidad: this.modalidad, valor: this.valor }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo aplicar el cambio');
                }
                const r = await resp.json();
                window.toast(`Dólar actualizado en ${r.length} proveedor(es)`, 'exito');
                this.valor = '';
                this.preview = [];
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.aplicando = false;
            }
        },

        /* --- Excel --- */

        tomarArchivo(file) {
            this.errores = [];
            this.archivo = file || null;
        },

        async importar() {
            this.importando = true;
            this.errores = [];
            try {
                const fd = new FormData();
                fd.append('archivo', this.archivo);
                const resp = await fetch('/api/v1/proveedores/dolar/importar', {
                    method: 'POST', credentials: 'same-origin', body: fd,
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo procesar el archivo');
                }
                const r = await resp.json();
                if (r.errores.length) {
                    this.errores = r.errores;
                    window.toast(`${r.errores.length} error(es): no se aplicó ningún cambio`, 'error');
                } else {
                    // Las filas cuyo valor ya era el mismo se saltean, y hay
                    // que decirlo: si no, subir 10 filas y leer "2 aplicados"
                    // parece que 8 se perdieron.
                    let mensaje = `Importación aplicada: ${r.aplicados} proveedor(es)`;
                    if (r.sin_cambios) {
                        mensaje += ` · ${r.sin_cambios} sin cambios (mismo valor)`;
                    }
                    window.toast(mensaje, 'exito', 6000);
                    this.archivo = null;
                    this.cargar();
                }
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.importando = false;
            }
        },
    };
}
