/* ==========================================================================
   Pantalla de auditoría de inventario.

   Contar y corregir están separados a propósito: quien cuenta registra las
   diferencias y el Dueño decide si se ajusta el stock. Una diferencia puede
   ser un error de conteo, un robo o una venta mal registrada, y las tres se
   arreglan distinto — ajustar automáticamente las taparía por igual.

   Nada de lo que se hace acá mueve stock hasta la aprobación.
   ========================================================================== */

const ESTADOS = [
    { id: 'en_curso', etiqueta: 'En curso' },
    { id: 'pendiente_aprobacion', etiqueta: 'Pendiente de aprobación' },
    { id: 'aprobada', etiqueta: 'Aprobada' },
    { id: 'rechazada', etiqueta: 'Rechazada' },
];

function abmAuditorias({ puntoFijo = null } = {}) {
    return {
        ESTADOS,

        auditorias: [],
        total: 0,
        cargando: false,
        puntos: [],
        categorias: [],
        puntoFijo,

        confirmacion: { abierta: false, titulo: '', mensaje: '', accion: () => {} },

        filtros: { estado: '', punto_de_venta_id: '' },

        inicio: {
            abierto: false, guardando: false,
            punto_de_venta_id: '', filtro_categoria_id: '', notas: '',
        },

        // La pantalla de trabajo: se escanea, se tipea la cantidad y se sigue.
        conteo: {
            abierto: false, guardando: false, auditoria: null,
            codigo: '', variante: null, cantidad: 0,
        },

        detalle: { abierto: false, auditoria: null },

        /* --- Formato --- */

        fecha(iso) {
            if (!iso) return '—';
            return new Date(iso).toLocaleString('es-AR', {
                day: '2-digit', month: '2-digit', year: '2-digit',
                hour: '2-digit', minute: '2-digit',
            });
        },

        etiquetaEstado(estado) {
            return ESTADOS.find((e) => e.id === estado)?.etiqueta || estado || '';
        },

        colorEstado(estado) {
            return {
                en_curso: 'text-primary',
                pendiente_aprobacion: 'text-accent',
                aprobada: 'text-success',
                rechazada: 'text-danger',
            }[estado] || 'text-texto-muted';
        },

        /**
         * Baja la planilla en PDF.
         *
         * Va por el endpoint y no por una ruta de archivo: así respeta el
         * permiso y el aislamiento por dispositivo, igual que el PDF del
         * remito. El documento se arma en el momento, no hay archivo que
         * adivinar.
         */
        descargarPdf(auditoria) {
            window.open(`/api/v1/auditorias-inventario/${auditoria.id}/pdf`, '_blank');
        },

        /** Cuántos códigos no coinciden: es lo único que va a generar ajuste. */
        conDiferencia(auditoria) {
            return (auditoria?.items || []).filter((i) => i.diferencia !== 0).length;
        },

        rutaCategoria(categoria) {
            if (!categoria) return '—';
            const porId = new Map(this.categorias.map((c) => [c.id, c]));
            const tramos = [];
            let actual = porId.get(categoria.id);
            if (!actual) return categoria.nombre || '—';
            for (let i = 0; i < 5 && actual; i++) {
                tramos.unshift(actual.nombre);
                actual = actual.parent_id ? porId.get(actual.parent_id) : null;
            }
            return tramos.join(' - ');
        },

        puntosPosibles() {
            if (!this.puntoFijo) return this.puntos;
            return this.puntos.filter((p) => p.id === this.puntoFijo);
        },

        /* --- Carga --- */

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams();
                for (const [clave, valor] of Object.entries(this.filtros)) {
                    if (valor !== '' && valor !== null) params.set(clave, valor);
                }
                const resp = await fetch('/api/v1/auditorias-inventario?' + params, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudieron cargar las auditorías');

                const datos = await resp.json();
                this.auditorias = datos.resultados;
                this.total = datos.total;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        async cargarCatalogos() {
            const [puntos, cats] = await Promise.all([
                fetch('/api/v1/stock/ubicaciones', { credentials: 'same-origin' }),
                fetch('/api/v1/categorias', { credentials: 'same-origin' }),
            ]);
            if (puntos.ok) this.puntos = await puntos.json();
            if (cats.ok) this.categorias = await cats.json();
        },

        limpiar() {
            this.filtros = { estado: '', punto_de_venta_id: '' };
            this.cargar();
        },

        /* --- Iniciar --- */

        abrirInicio() {
            this.inicio = {
                abierto: true, guardando: false,
                punto_de_venta_id: this.puntoFijo || '',
                filtro_categoria_id: '', notas: '',
            };
        },

        async guardarInicio() {
            const i = this.inicio;
            i.guardando = true;
            try {
                const resp = await fetch('/api/v1/auditorias-inventario', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        punto_de_venta_id: Number(i.punto_de_venta_id),
                        filtro_categoria_id: i.filtro_categoria_id
                            ? Number(i.filtro_categoria_id) : null,
                        notas: i.notas || null,
                    }),
                });
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo iniciar el conteo');
                }
                const auditoria = await resp.json();
                i.abierto = false;
                this.cargar();
                // Se entra derecho a contar: iniciar y quedarse mirando el
                // listado no es lo que alguien quiere hacer a continuación.
                this.conteo = {
                    abierto: true, guardando: false, auditoria,
                    codigo: '', variante: null, cantidad: 0,
                };
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                i.guardando = false;
            }
        },

        /* --- Conteo --- */

        async abrirConteo(auditoriaId) {
            const auditoria = await this.traer(auditoriaId);
            if (!auditoria) return;
            this.conteo = {
                abierto: true, guardando: false, auditoria,
                codigo: '', variante: null, cantidad: 0,
            };
        },

        async traer(auditoriaId) {
            try {
                const resp = await fetch(`/api/v1/auditorias-inventario/${auditoriaId}`, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo abrir la auditoría');
                return await resp.json();
            } catch (e) {
                window.toast(e.message, 'error');
                return null;
            }
        },

        /**
         * Resuelve el código escaneado a una variante concreta.
         *
         * Solo se toma como identificada si el buscador devuelve UNA fila:
         * con varias no hay forma de saber cuál se tiene en la mano.
         */
        async identificar() {
            const texto = (this.conteo.codigo || '').trim();
            this.conteo.variante = null;
            if (texto.length < 3) return;

            const params = new URLSearchParams({ busqueda: texto, tamano: 2 });
            const resp = await fetch('/api/v1/productos/variantes?' + params, {
                credentials: 'same-origin',
            });
            if (!resp.ok) return;

            const datos = await resp.json();
            if (datos.total === 1) {
                this.conteo.variante = datos.resultados[0];
                // Arranca en 1 y no en 0: lo más común es contar al menos una
                // unidad del código que se acaba de escanear.
                this.conteo.cantidad = 1;
            }
        },

        async registrar() {
            const c = this.conteo;
            if (!c.variante) return;

            c.guardando = true;
            try {
                const resp = await fetch(
                    `/api/v1/auditorias-inventario/${c.auditoria.id}/items`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify({
                            items: [{
                                variante_id: c.variante.id,
                                cantidad_contada: Number(c.cantidad) || 0,
                            }],
                        }),
                    }
                );
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo registrar el conteo');
                }
                c.auditoria = await resp.json();
                // Listo para el siguiente código, sin tocar el mouse.
                c.codigo = '';
                c.variante = null;
                c.cantidad = 0;
                document.getElementById('co-codigo')?.focus();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                c.guardando = false;
            }
        },

        confirmarFinalizar() {
            const diferencias = this.conDiferencia(this.conteo.auditoria);
            this.confirmacion = {
                abierta: true,
                titulo: 'Finalizar el conteo',
                mensaje:
                    `Se cierra el conteo con ${diferencias} código(s) con diferencia y `
                    + 'queda esperando la aprobación del Dueño. El stock no cambia todavía, '
                    + 'y después de cerrar no se pueden cargar más códigos.',
                accion: () => this.finalizar(),
            };
        },

        async finalizar() {
            this.confirmacion.abierta = false;
            try {
                const resp = await fetch(
                    `/api/v1/auditorias-inventario/${this.conteo.auditoria.id}/finalizar`,
                    { method: 'PATCH', credentials: 'same-origin' }
                );
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo finalizar');
                }
                window.toast('Conteo finalizado: espera aprobación', 'exito');
                this.conteo.abierto = false;
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        /* --- Detalle y aprobación --- */

        async abrirDetalle(auditoriaId) {
            const auditoria = await this.traer(auditoriaId);
            if (auditoria) this.detalle = { abierto: true, auditoria };
        },

        confirmarAprobacion() {
            const diferencias = this.conDiferencia(this.detalle.auditoria);
            this.confirmacion = {
                abierta: true,
                titulo: 'Aprobar la auditoría',
                mensaje:
                    `Se van a generar ${diferencias} ajuste(s) de stock y las cantidades `
                    + 'quedan iguales a lo contado. Los movimientos quedan registrados y '
                    + 'no se deshacen.',
                accion: () => this.resolver('aprobar'),
            };
        },

        confirmarRechazo() {
            this.confirmacion = {
                abierta: true,
                titulo: 'Rechazar la auditoría',
                mensaje:
                    'El stock queda como está. El conteo no se borra: queda registrado '
                    + 'con sus diferencias para poder revisarlo después.',
                accion: () => this.resolver('rechazar'),
            };
        },

        async resolver(decision) {
            this.confirmacion.abierta = false;
            try {
                const resp = await fetch(
                    `/api/v1/auditorias-inventario/${this.detalle.auditoria.id}/${decision}`,
                    {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        // `rechazar` acepta notas; `aprobar` ignora el cuerpo.
                        body: JSON.stringify({}),
                    }
                );
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || `No se pudo ${decision} la auditoría`);
                }
                window.toast(
                    decision === 'aprobar'
                        ? 'Auditoría aprobada: el stock quedó ajustado'
                        : 'Auditoría rechazada: el stock no cambió',
                    'exito'
                );
                this.detalle.abierto = false;
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },
    };
}
