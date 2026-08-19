/* ==========================================================================
   Pantalla de stock.

   Cada fila es una VARIANTE EN UNA UBICACIÓN: el mismo código en dos locales
   son dos filas, porque son dos hechos distintos. No hay "stock global".

   La cantidad NUNCA se edita desde acá. Lo único que se toca a mano son los
   mínimos de reposición; para que el número cambie hay que registrar un
   movimiento —un ingreso, una baja, un remito o un ajuste de auditoría—, que
   es lo que deja el rastro de por qué cambió.

   El filtrado y el aislamiento por dispositivo son del backend (Principio 5):
   un vendedor recibe solo las filas de su local sin que esta pantalla haga
   nada especial.
   ========================================================================== */

function abmStock({ puntoFijo = null } = {}) {
    return {
        filas: [],
        total: 0,
        cargando: false,

        // Catálogos de los desplegables.
        puntos: [],
        categorias: [],
        proveedores: [],
        motivos: [],

        // Los tres números del encabezado. Se piden aparte del listado
        // porque son de TODO lo que el usuario puede ver, no de la página
        // que está mirando.
        resumen: { filas: 0, unidades: 0, alertas: 0, valorizado: 0 },

        // La ubicación a la que está limitado este equipo, o null si ve
        // todas. La resuelve el servidor al renderizar la página: pedirla por
        // API obligaría a dibujar la pantalla entera y vaciarla después.
        puntoFijo,

        filtros: {
            busqueda: '', punto_de_venta_id: '', categoria_id: '', proveedor_id: '',
            // String y no booleano para que entre sin cambios en el bucle que
            // arma los query params, igual que en los otros listados.
            solo_bajo_minimo: '',
        },

        ingreso: {
            abierto: false, guardando: false, codigo: '', variante: null,
            punto_de_venta_id: '', cantidad: 1, notas: '',
        },

        minimos: {
            abierto: false, guardando: false, variante_id: null,
            punto_de_venta_id: null, codigo: '', tipo: '',
            stock_minimo_cd: 0, stock_minimo_local: 0,
            /** El que rige en esta ubicación, que es lo que decide la alerta. */
            aplicable() {
                return this.tipo === 'cd' ? this.stock_minimo_cd : this.stock_minimo_local;
            },
        },

        baja: {
            abierto: false, guardando: false, variante_id: null,
            punto_de_venta_id: null, codigo: '', ubicacion: '', disponible: 0,
            cantidad: 1, motivo_baja_id: '', notas: '',
        },

        /* --- Formato: la API manda números, no strings con símbolo --- */

        pesos(valor) {
            if (valor === null || valor === undefined) return '—';
            const n = Number(valor);
            const decimales = Number.isInteger(n) ? 0 : 2;
            return n.toLocaleString('es-AR', {
                style: 'currency', currency: 'ARS',
                minimumFractionDigits: decimales, maximumFractionDigits: decimales,
            });
        },

        /**
         * Camino completo de una categoría, igual que en productos: dos ramas
         * pueden tener hojas con el mismo nombre y el nombre suelto no alcanza
         * para distinguirlas.
         */
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

        /** Las ubicaciones a las que este equipo puede mandar mercadería. */
        puntosDestino() {
            if (!this.puntoFijo) return this.puntos;
            return this.puntos.filter((p) => p.id === this.puntoFijo);
        },

        motivosActivos() {
            return this.motivos.filter((m) => m.activo);
        },

        /* --- Carga --- */

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams();
                for (const [clave, valor] of Object.entries(this.filtros)) {
                    if (valor !== '' && valor !== null) params.set(clave, valor);
                }

                const resp = await fetch('/api/v1/stock?' + params, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo cargar el stock');

                const datos = await resp.json();
                this.filas = datos.resultados;
                this.total = datos.total;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
            this.cargarResumen();
        },

        async cargarResumen() {
            const resp = await fetch('/api/v1/stock/resumen', { credentials: 'same-origin' });
            if (resp.ok) this.resumen = await resp.json();
        },

        async cargarCatalogos() {
            const [puntos, cats, provs, motivos] = await Promise.all([
                fetch('/api/v1/stock/ubicaciones', { credentials: 'same-origin' }),
                fetch('/api/v1/categorias', { credentials: 'same-origin' }),
                fetch('/api/v1/proveedores', { credentials: 'same-origin' }),
                fetch('/api/v1/stock/motivos-baja?activo=true', { credentials: 'same-origin' }),
            ]);
            // Vienen ya acotadas por el dispositivo y solo las activas: para
            // un vendedor la lista trae exactamente su local.
            if (puntos.ok) this.puntos = await puntos.json();
            if (cats.ok) this.categorias = await cats.json();
            if (provs.ok) {
                this.proveedores = (await provs.json()).filter((p) => p.estado === 'activo');
            }
            if (motivos.ok) this.motivos = await motivos.json();
        },

        limpiar() {
            this.filtros = {
                busqueda: '', punto_de_venta_id: '', categoria_id: '', proveedor_id: '',
                solo_bajo_minimo: '',
            };
            this.cargar();
        },

        /* --- Buscar una variante por su código --- */

        /**
         * Resuelve el código tipeado o escaneado a una variante concreta.
         *
         * Usa el mismo buscador del listado de productos, que entiende las
         * tres formas de nombrar un artículo —código de etiqueta con dígito
         * verificador, SKU o descripción—. Solo se toma como identificada si
         * devuelve UNA fila: con varias no hay forma de saber cuál es.
         */
        async buscarVariante(destino) {
            const contexto = this[destino];
            const texto = (contexto.codigo || '').trim();
            contexto.variante = null;
            if (texto.length < 3) return;

            try {
                const params = new URLSearchParams({ busqueda: texto, tamano: 2 });
                const resp = await fetch('/api/v1/productos/variantes?' + params, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) return;

                const datos = await resp.json();
                if (datos.total === 1) contexto.variante = datos.resultados[0];
            } catch {
                // Silencioso: es una ayuda para completar el formulario y no
                // puede trabar la carga.
            }
        },

        /* --- Ingreso de mercadería --- */

        abrirIngreso() {
            this.ingreso = {
                abierto: true, guardando: false, codigo: '', variante: null,
                // Con una sola ubicación posible se elige sola: no hay nada
                // que decidir y obligar a tocarla es fricción sin sentido.
                punto_de_venta_id: this.puntoFijo || '',
                cantidad: 1, notas: '',
            };
        },

        async guardarIngreso() {
            const i = this.ingreso;
            i.guardando = true;
            try {
                const resp = await fetch('/api/v1/stock/ingresos', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        variante_id: i.variante.id,
                        punto_de_venta_id: Number(i.punto_de_venta_id),
                        cantidad: Number(i.cantidad),
                        notas: i.notas || null,
                    }),
                });
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo registrar el ingreso');
                }
                window.toast(`Ingresaron ${i.cantidad} unidades`, 'exito');
                i.abierto = false;
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                i.guardando = false;
            }
        },

        /* --- Mínimos --- */

        abrirMinimos(fila) {
            this.minimos = {
                ...this.minimos,
                abierto: true,
                guardando: false,
                variante_id: fila.variante.id,
                punto_de_venta_id: fila.punto_de_venta.id,
                codigo: fila.variante.codigo_completo + fila.variante.verificador,
                tipo: fila.punto_de_venta.tipo,
                stock_minimo_cd: fila.stock_minimo_cd,
                stock_minimo_local: fila.stock_minimo_local,
            };
        },

        async guardarMinimos() {
            const m = this.minimos;
            m.guardando = true;
            try {
                const resp = await fetch(
                    `/api/v1/stock/minimos/${m.variante_id}/${m.punto_de_venta_id}`,
                    {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify({
                            stock_minimo_cd: Number(m.stock_minimo_cd) || 0,
                            stock_minimo_local: Number(m.stock_minimo_local) || 0,
                        }),
                    }
                );
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudieron guardar los mínimos');
                }
                window.toast('Mínimos actualizados', 'exito');
                m.abierto = false;
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                m.guardando = false;
            }
        },

        /* --- Bajas --- */

        abrirBaja(fila) {
            this.baja = {
                abierto: true, guardando: false,
                variante_id: fila.variante.id,
                punto_de_venta_id: fila.punto_de_venta.id,
                codigo: fila.variante.codigo_completo + fila.variante.verificador,
                ubicacion: fila.punto_de_venta.nombre,
                disponible: fila.cantidad,
                cantidad: 1, motivo_baja_id: '', notas: '',
            };
        },

        async guardarBaja() {
            const b = this.baja;
            b.guardando = true;
            try {
                const resp = await fetch('/api/v1/stock/bajas', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        variante_id: b.variante_id,
                        punto_de_venta_id: b.punto_de_venta_id,
                        cantidad: Number(b.cantidad),
                        motivo_baja_id: Number(b.motivo_baja_id),
                        notas: b.notas || null,
                    }),
                });
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo registrar la baja');
                }
                window.toast(`Se dieron de baja ${b.cantidad} unidades`, 'exito');
                b.abierto = false;
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                b.guardando = false;
            }
        },
    };
}
