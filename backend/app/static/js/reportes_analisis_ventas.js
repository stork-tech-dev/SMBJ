/* ==========================================================================
   Reporte: Análisis de ventas por producto.

   Mismo patrón que reportes_stock_bajo_minimo.js: filtros resueltos en el
   backend (Principio 5), las opciones de ubicación viajan en la propia
   respuesta de /api/v1/ventas/analisis-productos (Principio 2: no hay
   endpoint de puntos de venta accesible con solo permiso de Reportes).
   ========================================================================== */

function analisisVentas() {
    return {
        resultados: [],   // [AnalisisProductoFila] — ver backend/app/schemas/ventas.py
        categorias: [],
        proveedores: [],
        puntosDeVenta: [],
        total:    0,
        pagina:   1,
        tamano:   20,
        cargando: false,

        filtros: {
            busqueda:          '',
            categoria_id:      '',
            proveedor_id:      '',
            punto_de_venta_id: '',
        },

        fecha(iso) {
            return new Date(iso).toLocaleDateString('es-AR');
        },

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams({ pagina: this.pagina, tamano: this.tamano });
                if (this.filtros.busqueda)          params.set('busqueda', this.filtros.busqueda);
                if (this.filtros.categoria_id)      params.set('categoria_id', this.filtros.categoria_id);
                if (this.filtros.proveedor_id)      params.set('proveedor_id', this.filtros.proveedor_id);
                if (this.filtros.punto_de_venta_id) params.set('punto_de_venta_id', this.filtros.punto_de_venta_id);

                const resp = await fetch('/api/v1/ventas/analisis-productos?' + params, { credentials: 'same-origin' });
                if (!resp.ok) throw new Error(await resp.text());
                const datos = await resp.json();

                this.resultados    = datos.resultados;
                this.total         = datos.total;
                this.puntosDeVenta = datos.opciones_locales;
            } finally {
                this.cargando = false;
            }
        },

        // /api/v1/categorias y /api/v1/proveedores devuelven un array plano,
        // no paginado: sin `.resultados`.
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

        // Camino completo de una categoría: "Joyas - Anillos - Plata".
        // Implementación compartida en app.js (Principio 2).
        rutaCategoria(categoria) {
            return window.rutaCategoria(this.categorias, categoria);
        },

        limpiar() {
            this.filtros = {
                busqueda: '', categoria_id: '', proveedor_id: '', punto_de_venta_id: '',
            };
            this.pagina = 1;
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
            return '/api/v1/ventas/analisis-productos/exportar?' + params;
        },
    };
}
