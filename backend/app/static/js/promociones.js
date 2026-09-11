/* ==========================================================================
   Catálogo de promociones: 2x1, 3x2 y % Porcentaje.

   "Activa" y "vigente" son dos preguntas distintas y la pantalla las muestra
   por separado: una promo prendida con fecha de fin pasada NO rige hoy. Las
   dos las resuelve el backend — `vigente` viene calculado en la respuesta,
   porque comparar fechas en el navegador usaría el reloj del celular y no el
   del servidor.

   Una promoción no se borra: se desactiva, porque las ventas confirmadas la
   apuntan y borrarla dejaría ítems con precio distinto sin decir por qué.

   Los alcances son concurrentes: una promo restringida a "Sucursal X" y
   "Efectivo" solo aplica si el punto de venta ES X y el medio de pago ES
   efectivo. Un set vacío de cada alcance significa "todos".
   ========================================================================== */

const URL_PROMOS = '/api/v1/configuracion/promociones';
const URL_CATEGORIAS = '/api/v1/categorias';
const URL_PRODUCTOS = '/api/v1/productos';
const URL_CATALOGOS = '/api/v1/configuracion/promociones/catalogos';

function abmPromociones() {
    return {
        promociones: [],
        cargando: false,
        filtros: { nombre: '', tipo: '', vigente: '', activo: 'true' },

        form: {
            abierto: false, guardando: false, id: null,
            nombre: '', nota: '', tipo: 'dos_x_uno',
            porcentaje_descuento: '',
            fecha_inicio: '', fecha_fin: '',
            // Alcances de producto/categoría individuales
            alcances: [],
            // Atajos para "todos" — excluyentes entre sí y con alcances individuales
            todos_productos: false,
            todos_categorias: false,
            // Sucursales y medios de pago: vacío = todos
            sucursales: [],
            medios_pago: [],
        },

        busqueda: { tipo: 'categoria', texto: '', opciones: [] },

        // Catálogos para los selectores de sucursal y medio de pago
        catalogos: { puntos_de_venta: [], medios_de_pago: [] },

        etiquetaTipo(tipo) {
            if (tipo === 'dos_x_uno') return '2x1';
            if (tipo === 'tres_x_dos') return '3x2';
            if (tipo === 'porcentaje') return '% Porcentaje';
            return tipo;
        },

        resumenAlcance(p) {
            if (!p.alcances?.length) return '—';
            // Los dos primeros y un contador: la columna tiene que entrar en
            // la fila, y la lista completa está en el modal de edición.
            const nombres = p.alcances.map((a) => a.nombre || `#${a.referencia_id}`);
            const visibles = nombres.slice(0, 2).join(', ');
            return nombres.length > 2
                ? `${visibles} +${nombres.length - 2}`
                : visibles;
        },

        resumenVigencia(p) {
            const fecha = (iso) =>
                iso ? new Date(`${iso}T00:00:00`).toLocaleDateString('es-AR') : null;
            const desde = fecha(p.fecha_inicio);
            const hasta = fecha(p.fecha_fin);

            if (!desde && !hasta) return 'Sin límite';
            if (desde && hasta) return `${desde} – ${hasta}`;
            return desde ? `Desde ${desde}` : `Hasta ${hasta}`;
        },

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams();
                for (const [k, v] of Object.entries(this.filtros)) {
                    if (v !== '') params.set(k, v);
                }

                const resp = await fetch(`${URL_PROMOS}?${params}`, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo cargar el catálogo');
                this.promociones = await resp.json();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        async cargarCatalogos() {
            try {
                const resp = await fetch(URL_CATALOGOS, { credentials: 'same-origin' });
                if (!resp.ok) return;
                this.catalogos = await resp.json();
            } catch {
                // No bloquear el modal si los catálogos fallan: el usuario
                // puede seguir cargando sin restricciones de sucursal/medio.
            }
        },

        /* "Limpiar" vuelve al estado de entrada, no a "mostrar todo". */
        limpiar() {
            this.filtros = { nombre: '', tipo: '', vigente: '', activo: 'true' };
            this.cargar();
        },

        /* --- Alta y edición --- */

        _formVacio() {
            return {
                abierto: true, guardando: false, id: null,
                nombre: '', nota: '', tipo: 'dos_x_uno',
                porcentaje_descuento: '',
                fecha_inicio: '', fecha_fin: '',
                alcances: [],
                todos_productos: false,
                todos_categorias: false,
                sucursales: [],
                medios_pago: [],
            };
        },

        abrirAlta() {
            this.form = this._formVacio();
            this.busqueda = { tipo: 'categoria', texto: '', opciones: [] };
            if (!this.catalogos.puntos_de_venta.length) this.cargarCatalogos();
        },

        abrirEdicion(p) {
            const alcancesProductoCategoria = [];
            let todosProductos = false;
            let todosCategorias = false;
            const sucursales = [];
            const mediosPago = [];

            for (const a of (p.alcances || [])) {
                if (a.tipo_alcance === 'todos_productos') {
                    todosProductos = true;
                } else if (a.tipo_alcance === 'todos_categorias') {
                    todosCategorias = true;
                } else if (a.tipo_alcance === 'punto_de_venta') {
                    sucursales.push({ id: a.referencia_id, nombre: a.nombre || `#${a.referencia_id}` });
                } else if (a.tipo_alcance === 'medio_de_pago') {
                    mediosPago.push({ id: a.referencia_id, nombre: a.nombre || `#${a.referencia_id}` });
                } else {
                    alcancesProductoCategoria.push({
                        tipo_alcance: a.tipo_alcance,
                        referencia_id: a.referencia_id,
                        nombre: a.nombre || `#${a.referencia_id}`,
                    });
                }
            }

            this.form = {
                abierto: true, guardando: false, id: p.id,
                nombre: p.nombre,
                nota: p.nota || '',
                tipo: p.tipo,
                porcentaje_descuento: p.porcentaje_descuento ?? '',
                fecha_inicio: p.fecha_inicio || '',
                fecha_fin: p.fecha_fin || '',
                alcances: alcancesProductoCategoria,
                todos_productos: todosProductos,
                todos_categorias: todosCategorias,
                sucursales,
                medios_pago: mediosPago,
            };
            this.busqueda = { tipo: 'categoria', texto: '', opciones: [] };
            if (!this.catalogos.puntos_de_venta.length) this.cargarCatalogos();
        },

        /* --- Alcance de producto/categoría --- */

        async buscarAlcance() {
            const texto = this.busqueda.texto.trim();
            if (texto.length < 2) {
                this.busqueda.opciones = [];
                return;
            }

            try {
                if (this.busqueda.tipo === 'categoria') {
                    const resp = await fetch(
                        `${URL_CATEGORIAS}?nombre=${encodeURIComponent(texto)}`,
                        { credentials: 'same-origin' }
                    );
                    if (!resp.ok) throw new Error('No se pudieron buscar categorías');
                    const datos = await resp.json();
                    this.busqueda.opciones = datos.map((c) => ({ id: c.id, nombre: c.nombre }));
                } else {
                    const resp = await fetch(
                        `${URL_PRODUCTOS}?descripcion=${encodeURIComponent(texto)}&tamano=20`,
                        { credentials: 'same-origin' }
                    );
                    if (!resp.ok) throw new Error('No se pudieron buscar productos');
                    const datos = await resp.json();
                    this.busqueda.opciones = datos.resultados.map((p) => ({
                        id: p.id,
                        nombre: `${p.sku} · ${p.descripcion}`,
                    }));
                }
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        agregarAlcance(opcion) {
            const alcance = {
                tipo_alcance: this.busqueda.tipo,
                referencia_id: opcion.id,
                nombre: opcion.nombre,
            };

            const yaEsta = this.form.alcances.some(
                (a) => a.tipo_alcance === alcance.tipo_alcance
                    && a.referencia_id === alcance.referencia_id
            );
            if (!yaEsta) this.form.alcances.push(alcance);

            this.busqueda.texto = '';
            this.busqueda.opciones = [];
        },

        /* --- Sucursales (toggle de chips) --- */

        toggleSucursal(pdv) {
            const idx = this.form.sucursales.findIndex((s) => s.id === pdv.id);
            if (idx >= 0) {
                this.form.sucursales.splice(idx, 1);
            } else {
                this.form.sucursales.push({ id: pdv.id, nombre: pdv.nombre });
            }
        },

        sucursalSeleccionada(pdv) {
            return this.form.sucursales.some((s) => s.id === pdv.id);
        },

        /* --- Medios de pago (toggle de chips) --- */

        toggleMedio(medio) {
            const idx = this.form.medios_pago.findIndex((m) => m.id === medio.id);
            if (idx >= 0) {
                this.form.medios_pago.splice(idx, 1);
            } else {
                this.form.medios_pago.push({ id: medio.id, nombre: medio.nombre });
            }
        },

        medioSeleccionado(medio) {
            return this.form.medios_pago.some((m) => m.id === medio.id);
        },

        /* --- Guardar --- */

        async guardar() {
            this.form.guardando = true;
            try {
                // Construir el array de alcances desde todos los campos del form.
                const alcances = [];

                if (this.form.todos_productos) {
                    alcances.push({ tipo_alcance: 'todos_productos', referencia_id: 0 });
                } else if (this.form.todos_categorias) {
                    alcances.push({ tipo_alcance: 'todos_categorias', referencia_id: 0 });
                } else {
                    alcances.push(
                        ...this.form.alcances.map((a) => ({
                            tipo_alcance: a.tipo_alcance,
                            referencia_id: a.referencia_id,
                        }))
                    );
                }

                for (const s of this.form.sucursales) {
                    alcances.push({ tipo_alcance: 'punto_de_venta', referencia_id: s.id });
                }
                for (const m of this.form.medios_pago) {
                    alcances.push({ tipo_alcance: 'medio_de_pago', referencia_id: m.id });
                }

                const alta = !this.form.id;
                const cuerpo = {
                    nombre: this.form.nombre,
                    nota: this.form.nota || null,
                    tipo: this.form.tipo,
                    porcentaje_descuento: this.form.tipo === 'porcentaje'
                        ? Number(this.form.porcentaje_descuento) || null
                        : null,
                    alcances,
                    fecha_inicio: this.form.fecha_inicio || null,
                    fecha_fin: this.form.fecha_fin || null,
                };

                const resp = await fetch(
                    alta ? URL_PROMOS : `${URL_PROMOS}/${this.form.id}`,
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
                window.toast(alta ? 'Promoción creada' : 'Promoción actualizada', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.form.guardando = false;
            }
        },

        async cambiarEstado(p, activo) {
            try {
                const resp = await fetch(`${URL_PROMOS}/${p.id}/estado`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ activo }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo cambiar el estado');
                }
                window.toast(activo ? 'Promoción activada' : 'Promoción desactivada', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },
    };
}
