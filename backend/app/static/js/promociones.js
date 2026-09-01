/* ==========================================================================
   Catálogo de promociones 2x1 y 3x2.

   "Activa" y "vigente" son dos preguntas distintas y la pantalla las muestra
   por separado: una promo prendida con fecha de fin pasada NO rige hoy. Las
   dos las resuelve el backend — `vigente` viene calculado en la respuesta,
   porque comparar fechas en el navegador usaría el reloj del celular y no el
   del servidor.

   Una promoción no se borra: se desactiva, porque las ventas confirmadas la
   apuntan y borrarla dejaría ítems en $0 sin decir por qué.
   ========================================================================== */

const URL_PROMOS = '/api/v1/configuracion/promociones';
const URL_CATEGORIAS = '/api/v1/categorias';
const URL_PRODUCTOS = '/api/v1/productos';

function abmPromociones() {
    return {
        promociones: [],
        cargando: false,
        filtros: { nombre: '', tipo: '', vigente: '', activo: 'true' },

        form: {
            abierto: false, guardando: false, id: null,
            nombre: '', tipo: 'dos_x_uno',
            fecha_inicio: '', fecha_fin: '',
            alcances: [],
        },

        busqueda: { tipo: 'categoria', texto: '', opciones: [] },

        etiquetaTipo(tipo) {
            return tipo === 'dos_x_uno' ? '2x1' : '3x2';
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

        /* "Limpiar" vuelve al estado de entrada, no a "mostrar todo". */
        limpiar() {
            this.filtros = { nombre: '', tipo: '', vigente: '', activo: 'true' };
            this.cargar();
        },

        /* --- Alta y edición --- */

        abrirAlta() {
            this.form = {
                abierto: true, guardando: false, id: null,
                nombre: '', tipo: 'dos_x_uno',
                fecha_inicio: '', fecha_fin: '',
                alcances: [],
            };
            this.busqueda = { tipo: 'categoria', texto: '', opciones: [] };
        },

        abrirEdicion(p) {
            this.form = {
                abierto: true, guardando: false, id: p.id,
                nombre: p.nombre, tipo: p.tipo,
                fecha_inicio: p.fecha_inicio || '',
                fecha_fin: p.fecha_fin || '',
                // Copia, no referencia: editar y cancelar no puede dejar la
                // fila del listado con los alcances a medio cambiar.
                alcances: (p.alcances || []).map((a) => ({
                    tipo_alcance: a.tipo_alcance,
                    referencia_id: a.referencia_id,
                    nombre: a.nombre || `#${a.referencia_id}`,
                })),
            };
            this.busqueda = { tipo: 'categoria', texto: '', opciones: [] };
        },

        /* --- Alcance --- */

        async buscarAlcance() {
            const texto = this.busqueda.texto.trim();
            if (texto.length < 2) {
                this.busqueda.opciones = [];
                return;
            }

            try {
                // Dos endpoints distintos, una sola forma de resultado:
                // {id, nombre}. Así el resto de la pantalla no tiene que
                // saber de cuál de los dos vino.
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

            // Repetir el mismo alcance no hace que la promo aplique dos
            // veces: solo duplicaría el chip. El UNIQUE de la base lo
            // rechazaría igual, pero con un error ilegible.
            const yaEsta = this.form.alcances.some(
                (a) => a.tipo_alcance === alcance.tipo_alcance
                    && a.referencia_id === alcance.referencia_id
            );
            if (!yaEsta) this.form.alcances.push(alcance);

            this.busqueda.texto = '';
            this.busqueda.opciones = [];
        },

        async guardar() {
            this.form.guardando = true;
            try {
                const alta = !this.form.id;
                const cuerpo = {
                    nombre: this.form.nombre,
                    tipo: this.form.tipo,
                    alcances: this.form.alcances.map((a) => ({
                        tipo_alcance: a.tipo_alcance,
                        referencia_id: a.referencia_id,
                    })),
                    // Las fechas viajan siempre las dos, incluso vacías: el
                    // backend las trata como un rango, y mandar una sola
                    // dejaría una vigencia a medias.
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
