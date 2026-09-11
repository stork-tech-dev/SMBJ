function consultaStock() {
    return {
        columnas:   [],  // [{id, codigo, nombre}] — CD primero, luego alpha
        filas:      [],  // [{variante_id, codigo_completo, verificador, descripcion, descripcion_sufijo, stocks}]
        categorias: [],
        proveedores: [],
        total:    0,
        pagina:   1,
        tamano:   10,
        cargando: false,

        filtros: {
            busqueda:     '',
            categoria_id: '',
            proveedor_id: '',
        },

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams({ pagina: this.pagina, tamano: this.tamano });
                if (this.filtros.busqueda)     params.set('busqueda', this.filtros.busqueda);
                if (this.filtros.categoria_id) params.set('categoria_id', this.filtros.categoria_id);
                if (this.filtros.proveedor_id) params.set('proveedor_id', this.filtros.proveedor_id);

                const resp = await fetch('/api/v1/stock/consulta?' + params, { credentials: 'same-origin' });
                if (!resp.ok) throw new Error(await resp.text());
                const datos = await resp.json();

                this.columnas = datos.columnas;
                this.filas    = datos.filas;
                this.total    = datos.total;
            } finally {
                this.cargando = false;
            }
        },

        async cargarCatalogos() {
            const [cats, provs] = await Promise.all([
                fetch('/api/v1/categorias?activo=true&pagina=1&tamano=200', { credentials: 'same-origin' }),
                fetch('/api/v1/proveedores?pagina=1&tamano=200', { credentials: 'same-origin' }),
            ]);
            const catsJson  = await cats.json();
            const provsJson = await provs.json();
            this.categorias  = catsJson.resultados  ?? [];
            this.proveedores = provsJson.resultados ?? [];
        },

        // Muestra el camino completo de la categoría en el combo, igual que el
        // listado de stock y productos.
        rutaCategoria(cat) {
            if (!cat) return '';
            const partes = [cat.nombre];
            if (cat.padre)  partes.unshift(cat.padre.nombre);
            return partes.join(' › ');
        },

        limpiar() {
            this.filtros = { busqueda: '', categoria_id: '', proveedor_id: '' };
            this.pagina  = 1;
            this.cargar();
        },
    };
}
