function consultaStock() {
    return {
        columnas:   [],  // [{id, codigo, nombre, tipo}] — CD primero, luego alpha
        filas:      [],  // [{variante_id, codigo_completo, verificador, descripcion, descripcion_sufijo, stocks}]
        categorias: [],
        proveedores: [],
        puntosDeVenta: [],  // opciones del filtro (sin el CD, que ya se ve siempre)
        total:    0,
        pagina:   1,
        tamano:   10,
        cargando: false,

        filtros: {
            busqueda:         '',
            categoria_id:     '',
            proveedor_id:     '',
            punto_de_venta_id: '',
        },

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams({ pagina: this.pagina, tamano: this.tamano });
                if (this.filtros.busqueda)          params.set('busqueda', this.filtros.busqueda);
                if (this.filtros.categoria_id)      params.set('categoria_id', this.filtros.categoria_id);
                if (this.filtros.proveedor_id)      params.set('proveedor_id', this.filtros.proveedor_id);
                if (this.filtros.punto_de_venta_id) params.set('punto_de_venta_id', this.filtros.punto_de_venta_id);

                const resp = await fetch('/api/v1/stock/consulta?' + params, { credentials: 'same-origin' });
                if (!resp.ok) throw new Error(await resp.text());
                const datos = await resp.json();

                this.columnas = datos.columnas;
                this.filas    = datos.filas;
                this.total    = datos.total;

                // Las opciones del filtro salen de la respuesta SIN filtrar
                // por punto_de_venta_id (Principio 2: no hay un endpoint de
                // puntos de venta accesible con solo permiso de Reportes).
                // Se capturan una sola vez, la primera vez que se ve todo.
                if (!this.filtros.punto_de_venta_id && !this.puntosDeVenta.length) {
                    this.puntosDeVenta = datos.columnas.filter((c) => c.tipo !== 'cd');
                }
            } finally {
                this.cargando = false;
            }
        },

        // /api/v1/categorias y /api/v1/proveedores devuelven un array plano,
        // no paginado (a diferencia de /stock/consulta): sin `.resultados`.
        async cargarCatalogos() {
            const [cats, provs] = await Promise.all([
                fetch('/api/v1/categorias', { credentials: 'same-origin' }),
                fetch('/api/v1/proveedores', { credentials: 'same-origin' }),
            ]);
            if (cats.ok) this.categorias = await cats.json();
            if (provs.ok) {
                // Solo los activos: igual criterio que el filtro de /productos.
                this.proveedores = (await provs.json()).filter((p) => p.estado === 'activo');
            }
        },

        /**
         * Camino completo de una categoría: "Joyas - Anillos - Plata".
         *
         * Se arma acá y no en la API porque `categorias` ya está cargado en
         * memoria con el `parent_id` de cada nodo (igual que en productos.js).
         */
        rutaCategoria(categoria) {
            if (!categoria) return '—';

            const ids = this.rutaDeIds(categoria.id);
            if (!ids.length) return categoria.nombre || '—';

            const porId = new Map(this.categorias.map((c) => [c.id, c]));
            return ids.map((id) => porId.get(id).nombre).join(' - ');
        },

        /** Los ids desde la raíz hasta la categoría dada, ella incluida. */
        rutaDeIds(categoriaId) {
            const porId = new Map(this.categorias.map((c) => [c.id, c]));
            const ids = [];

            let actual = porId.get(Number(categoriaId));
            for (let i = 0; i < 5 && actual; i++) {
                ids.unshift(actual.id);
                actual = actual.parent_id ? porId.get(actual.parent_id) : null;
            }
            return ids;
        },

        limpiar() {
            this.filtros = {
                busqueda: '', categoria_id: '', proveedor_id: '', punto_de_venta_id: '',
            };
            this.pagina  = 1;
            this.cargar();
        },

        // Mismos filtros que `cargar()`, sin paginar: el endpoint de
        // exportación trae todo lo que matchea, no solo la página visible.
        urlExportar() {
            const params = new URLSearchParams();
            if (this.filtros.busqueda)          params.set('busqueda', this.filtros.busqueda);
            if (this.filtros.categoria_id)      params.set('categoria_id', this.filtros.categoria_id);
            if (this.filtros.proveedor_id)      params.set('proveedor_id', this.filtros.proveedor_id);
            if (this.filtros.punto_de_venta_id) params.set('punto_de_venta_id', this.filtros.punto_de_venta_id);
            return '/api/v1/stock/consulta/exportar?' + params;
        },
    };
}
