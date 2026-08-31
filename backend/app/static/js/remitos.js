/* ==========================================================================
   Pantalla de remitos.

   Un remito es el papel que viaja con la mercadería y, a la vez, el estado de
   una transferencia. El stock sale del origen al ARMAR el envío y entra al
   destino al CONFIRMAR la recepción: en el medio no está en ninguna de las
   dos puntas, que es la verdad de lo que pasa con un camión en la calle.

   El aislamiento por dispositivo lo resuelve el backend: un vendedor ve los
   remitos de su local por las dos puntas —los que le mandaron y los que
   mandó— sin que esta pantalla haga nada especial.
   ========================================================================== */

// El `id` es lo que viaja a la API; la etiqueta es lo que se lee. No se
// deriva una de la otra: "con_diferencia" con el guion bajo cambiado por un
// espacio no da "Con diferencia".
const ESTADOS = [
    { id: 'pendiente', etiqueta: 'Pendiente' },
    { id: 'en_camino', etiqueta: 'En camino' },
    { id: 'confirmado', etiqueta: 'Confirmado' },
    { id: 'con_diferencia', etiqueta: 'Con diferencia' },
];

function abmRemitos({ puntoFijo = null } = {}) {
    return {
        ESTADOS,

        remitos: [],
        total: 0,
        pagina: 1,
        tamano: 10,
        cargando: false,
        puntos: [],
        puntoFijo,

        filtros: {
            estado: '', punto_venta_origen_id: '', punto_venta_destino_id: '',
        },

        alta: {
            abierto: false, guardando: false,
            punto_venta_origen_id: '', punto_venta_destino_id: '',
            codigo: '', items: [], notas: '',
        },

        detalle: { abierto: false, remito: null },

        recepcion: {
            abierto: false, guardando: false, remito: null,
            numero_confirmacion: '', items: [], notas: '',
        },

        /* --- Formato --- */

        fecha(iso) {
            if (!iso) return '—';
            return new Date(iso).toLocaleString('es-AR', {
                day: '2-digit', month: '2-digit', year: '2-digit',
                hour: '2-digit', minute: '2-digit',
            });
        },

        etiquetaEstado(estado) {
            return ESTADOS.find((e) => e.id === estado)?.etiqueta || estado;
        },

        /**
         * El color dice qué hacer, no solo en qué estado está: lo que espera
         * una acción se ve, lo terminado se apaga y lo que tiene diferencia
         * pide que alguien lo mire.
         */
        colorEstado(estado) {
            return {
                pendiente: 'text-accent',
                en_camino: 'text-primary',
                confirmado: 'text-success',
                con_diferencia: 'text-danger',
            }[estado] || 'text-texto-muted';
        },

        /** Los cuatro pasos del flujo, con el que ya pasó marcado. */
        pasos() {
            const r = this.detalle.remito;
            if (!r) return [];
            const recibido = ['confirmado', 'con_diferencia'].includes(r.estado);
            return [
                { clave: 'armado', etiqueta: 'Armado', hecho: true,
                  cuando: this.fecha(r.fecha_envio) },
                { clave: 'despachado', etiqueta: 'Despachado',
                  hecho: r.estado !== 'pendiente', cuando: '' },
                { clave: 'recibido', etiqueta: 'Recibido', hecho: recibido,
                  cuando: r.fecha_recepcion ? this.fecha(r.fecha_recepcion) : '' },
                { clave: 'cierre',
                  etiqueta: r.estado === 'con_diferencia' ? 'Con diferencia' : 'Conforme',
                  hecho: recibido, cuando: '' },
            ];
        },

        /* --- Carga --- */

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams();
                for (const [clave, valor] of Object.entries(this.filtros)) {
                    if (valor !== '' && valor !== null) params.set(clave, valor);
                }
                params.set('pagina', this.pagina);
                params.set('tamano', this.tamano);
                const resp = await fetch('/api/v1/remitos?' + params, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudieron cargar los remitos');

                const datos = await resp.json();
                this.remitos = datos.resultados;
                this.total = datos.total;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        async cargarCatalogos() {
            // Del módulo de stock y no de Configuración: un vendedor no tiene
            // ese permiso, y sin esto no podría armar ni recibir nada. Vienen
            // ya acotadas por el dispositivo.
            const resp = await fetch('/api/v1/stock/ubicaciones', {
                credentials: 'same-origin',
            });
            if (resp.ok) this.puntos = await resp.json();
        },

        limpiar() {
            this.filtros = {
                estado: '', punto_venta_origen_id: '', punto_venta_destino_id: '',
            };
            this.cargar();
        },

        /**
         * De dónde puede salir mercadería: si el equipo está asignado a un
         * local, solo de ese. El backend lo exige igual (403), esto evita
         * ofrecer una opción que va a fallar.
         */
        puntosOrigen() {
            if (!this.puntoFijo) return this.puntos;
            return this.puntos.filter((p) => p.id === this.puntoFijo);
        },

        /** A dónde puede ir: cualquiera menos el origen elegido. */
        puntosDestino() {
            const origen = Number(this.alta.punto_venta_origen_id);
            return this.puntos.filter((p) => p.id !== origen);
        },

        /* --- Armar el envío --- */

        abrirAlta() {
            this.alta = {
                abierto: true, guardando: false,
                punto_venta_origen_id: this.puntoFijo || '',
                punto_venta_destino_id: '',
                codigo: '', items: [], notas: '',
            };
        },

        /**
         * Suma el código tipeado como una línea del remito.
         *
         * Si ya está, suma una unidad más: es lo que pasa cuando se escanean
         * diez pares de la misma zapatilla uno tras otro. Y se corta contra el
         * stock disponible, porque el backend rechaza el envío entero si una
         * línea se pasa —mejor avisar acá que perder lo cargado.
         */
        async agregarItem() {
            const texto = (this.alta.codigo || '').trim();
            if (!texto || !this.alta.punto_venta_origen_id) return;

            const variante = await this.buscarVariante(texto);
            if (!variante) {
                window.toast(`No hay un único artículo con "${texto}"`, 'error');
                return;
            }

            const disponible = await this.stockEnOrigen(variante.id);
            const existente = this.alta.items.find((i) => i.variante_id === variante.id);

            if (existente) {
                if (existente.cantidad >= disponible) {
                    window.toast(`Solo hay ${disponible} en el origen`, 'error');
                } else {
                    existente.cantidad += 1;
                }
            } else if (disponible < 1) {
                window.toast('No hay stock de ese código en el origen', 'error');
            } else {
                this.alta.items.push({
                    variante_id: variante.id,
                    codigo: variante.codigo_completo + variante.verificador,
                    descripcion: variante.producto.descripcion,
                    foto_url: variante.foto_url || null,
                    disponible,
                    cantidad: 1,
                });
            }
            this.alta.codigo = '';
        },

        /**
         * El lector de códigos no manda Enter: escribe el código y se queda
         * ahí. Con el debounce del input, un código completo se agrega solo.
         */
        async agregarSiEsUnico() {
            const texto = (this.alta.codigo || '').trim();
            // Un código de etiqueta entero mide 7 u 8 caracteres; por debajo
            // todavía se está tipeando y buscar sería adivinar.
            if (texto.length < 7) return;
            await this.agregarItem();
        },

        /** La variante que corresponde a un código, o null si es ambiguo. */
        async buscarVariante(texto) {
            const params = new URLSearchParams({ busqueda: texto, tamano: 2 });
            const resp = await fetch('/api/v1/productos/variantes?' + params, {
                credentials: 'same-origin',
            });
            if (!resp.ok) return null;
            const datos = await resp.json();
            return datos.total === 1 ? datos.resultados[0] : null;
        },

        /** Cuánto hay de esa variante en el origen elegido. */
        async stockEnOrigen(varianteId) {
            const params = new URLSearchParams({
                punto_de_venta_id: this.alta.punto_venta_origen_id,
            });
            const resp = await fetch('/api/v1/stock?' + params, {
                credentials: 'same-origin',
            });
            if (!resp.ok) return 0;
            const datos = await resp.json();
            const fila = datos.resultados.find((f) => f.variante.id === varianteId);
            return fila ? fila.cantidad : 0;
        },

        async guardarAlta() {
            const a = this.alta;
            a.guardando = true;
            try {
                const resp = await fetch('/api/v1/remitos', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        punto_venta_origen_id: Number(a.punto_venta_origen_id),
                        punto_venta_destino_id: Number(a.punto_venta_destino_id),
                        items: a.items.map((i) => ({
                            variante_id: i.variante_id,
                            cantidad: Number(i.cantidad),
                        })),
                        notas: a.notas || null,
                    }),
                });
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo crear el remito');
                }
                const creado = await resp.json();
                window.toast(`Remito ${creado.numero} creado`, 'exito');
                a.abierto = false;
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                a.guardando = false;
            }
        },

        /* --- Despacho --- */

        async despachar(remito) {
            try {
                const resp = await fetch(`/api/v1/remitos/${remito.id}/despachar`, {
                    method: 'PATCH', credentials: 'same-origin',
                });
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo despachar');
                }
                window.toast(`${remito.numero} despachado: el PDF está listo`, 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        /**
         * Abre el PDF en otra pestaña.
         *
         * Va por el endpoint y no por la ruta del archivo: así respeta el
         * permiso y el aislamiento por dispositivo. El archivo servido en
         * crudo sería legible por cualquiera que adivine el número.
         */
        verPdf(remito) {
            window.open(`/api/v1/remitos/${remito.id}/pdf`, '_blank');
        },

        /* --- Detalle --- */

        async abrirDetalle(remitoId) {
            try {
                const resp = await fetch(`/api/v1/remitos/${remitoId}`, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo abrir el remito');
                this.detalle = { abierto: true, remito: await resp.json() };
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        /* --- Recepción --- */

        async abrirRecepcion(remitoId) {
            try {
                const resp = await fetch(`/api/v1/remitos/${remitoId}`, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo abrir el remito');
                const remito = await resp.json();

                this.recepcion = {
                    abierto: true, guardando: false, remito,
                    numero_confirmacion: '',
                    // Precargado con lo enviado: lo normal es que llegue todo,
                    // y obligar a tipear cada línea para el caso habitual
                    // invita a equivocarse.
                    items: remito.items.map((i) => ({
                        variante_id: i.variante.id,
                        codigo: i.variante.codigo_completo + i.variante.verificador,
                        descripcion: i.variante.producto.descripcion,
                        foto_url: i.variante.foto_url || null,
                        enviada: i.cantidad_enviada,
                        recibida: i.cantidad_enviada,
                    })),
                    notas: '',
                };
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        hayDiferencia() {
            return this.recepcion.items.some(
                (i) => Number(i.recibida) !== i.enviada
            );
        },

        async guardarRecepcion() {
            const r = this.recepcion;
            r.guardando = true;
            try {
                const resp = await fetch(`/api/v1/remitos/${r.remito.id}/confirmar`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        numero_confirmacion: r.numero_confirmacion.trim(),
                        items: r.items.map((i) => ({
                            variante_id: i.variante_id,
                            cantidad_recibida: Number(i.recibida),
                        })),
                        notas: r.notas || null,
                    }),
                });
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo confirmar la recepción');
                }
                const confirmado = await resp.json();
                window.toast(
                    confirmado.estado === 'con_diferencia'
                        ? 'Recepción confirmada CON DIFERENCIAS'
                        : 'Recepción confirmada',
                    confirmado.estado === 'con_diferencia' ? 'error' : 'exito'
                );
                r.abierto = false;
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                r.guardando = false;
            }
        },
    };
}
