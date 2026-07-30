/* ==========================================================================
   Árbol de categorías.

   El backend devuelve el árbol anidado; acá se lo aplana a una lista de
   nodos visibles según qué ramas estén abiertas. Aplanar en el cliente
   evita anidar 5 <template> en el HTML, que es la única forma de hacer
   recursión en Alpine y queda ilegible.

   El filtrado sigue siendo del backend (Principio 5): `cargar()` siempre
   vuelve a pedir, nunca filtra sobre lo que ya tiene en memoria.
   ========================================================================== */

function arbolCategorias() {
    return {
        arbol: [],
        total: 0,
        cargando: false,
        // Ids de las ramas expandidas.
        abiertos: [],

        filtros: { nombre: '', nivel: '' },

        form: {
            abierto: false, guardando: false, id: null,
            nombre: '', orden: 0, parent_id: null, ubicacion: '',
        },

        confirmacion: { abierta: false, id: null, nombre: '' },

        /**
         * Nodos que se dibujan: cada raíz y, de forma recursiva, los hijos
         * de las ramas abiertas.
         */
        get visibles() {
            const salida = [];
            const recorrer = (nodos) => {
                for (const n of nodos) {
                    salida.push(n);
                    if (this.abiertos.includes(n.id)) recorrer(n.hijos);
                }
            };
            recorrer(this.arbol);
            return salida;
        },

        async cargar() {
            this.cargando = true;
            try {
                // Con filtros activos el resultado es plano: filtrar un
                // árbol dejaría nodos huérfanos (un hijo que coincide y un
                // padre que no). Se muestran los coincidentes sin jerarquía.
                const params = new URLSearchParams();
                for (const [clave, valor] of Object.entries(this.filtros)) {
                    if (valor !== '' && valor !== null) params.set(clave, valor);
                }
                const hayFiltros = [...params.keys()].length > 0;

                const url = hayFiltros
                    ? '/api/v1/categorias?' + params
                    : '/api/v1/categorias/arbol';

                const resp = await fetch(url, { credentials: 'same-origin' });
                if (!resp.ok) throw new Error('No se pudo cargar el árbol');

                const datos = await resp.json();
                // El listado plano no trae `hijos`: se completa para que
                // la vista no tenga que preguntar de dónde vino el dato.
                this.arbol = hayFiltros
                    ? datos.map((c) => ({ ...c, hijos: [] }))
                    : datos;
                this.total = this.contar(this.arbol);
            } catch (e) {
                window.toast(e.message, 'error');
                this.arbol = [];
                this.total = 0;
            } finally {
                this.cargando = false;
            }
        },

        contar(nodos) {
            return nodos.reduce((n, c) => n + 1 + this.contar(c.hijos || []), 0);
        },

        alternar(id) {
            const i = this.abiertos.indexOf(id);
            if (i === -1) this.abiertos.push(id);
            else this.abiertos.splice(i, 1);
        },

        limpiar() {
            this.filtros = { nombre: '', nivel: '' };
            this.cargar();
        },

        /* --- Alta y edición --- */

        /** `padre` null crea una raíz; si viene, crea un hijo. */
        abrirAlta(padre) {
            this.form = {
                abierto: true, guardando: false, id: null,
                nombre: '', orden: 0,
                parent_id: padre ? padre.id : null,
                ubicacion: padre
                    ? `Dentro de "${padre.nombre}" — será nivel ${padre.nivel + 1}`
                    : 'En el primer nivel',
            };
        },

        abrirEdicion(nodo) {
            this.form = {
                abierto: true, guardando: false, id: nodo.id,
                nombre: nodo.nombre, orden: nodo.orden,
                parent_id: nodo.parent_id,
                ubicacion: `Nivel ${nodo.nivel}`,
            };
        },

        async guardar() {
            this.form.guardando = true;
            try {
                const alta = !this.form.id;
                const cuerpo = { nombre: this.form.nombre, orden: Number(this.form.orden) || 0 };
                // El nivel no viaja: lo deriva el backend del padre.
                if (alta) cuerpo.parent_id = this.form.parent_id;

                const resp = await fetch(
                    alta ? '/api/v1/categorias' : '/api/v1/categorias/' + this.form.id,
                    {
                        method: alta ? 'POST' : 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify(cuerpo),
                    }
                );

                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo guardar la categoría');
                }

                // Al crear un hijo se abre la rama del padre, para que el
                // nodo nuevo quede a la vista y no parezca que no pasó nada.
                if (alta && this.form.parent_id && !this.abiertos.includes(this.form.parent_id)) {
                    this.abiertos.push(this.form.parent_id);
                }

                this.form.abierto = false;
                window.toast(alta ? 'Categoría creada' : 'Categoría actualizada', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.form.guardando = false;
            }
        },

        /* --- Baja --- */

        confirmarBaja(nodo) {
            this.confirmacion = { abierta: true, id: nodo.id, nombre: nodo.nombre };
        },

        async eliminar() {
            try {
                const resp = await fetch('/api/v1/categorias/' + this.confirmacion.id, {
                    method: 'DELETE',
                    credentials: 'same-origin',
                });
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo eliminar');
                }
                window.toast('Categoría eliminada', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.confirmacion.abierta = false;
            }
        },
    };
}
