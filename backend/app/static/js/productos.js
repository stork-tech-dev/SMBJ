/* ==========================================================================
   ABM de productos.

   El precio en pesos no se calcula acá: lo manda el backend ya resuelto
   con el dólar del proveedor (está desnormalizado en la tabla). El
   frontend solo le da formato — la API devuelve números crudos
   (Principio 1).

   El filtrado y la paginación también son del backend (Principio 5).
   ========================================================================== */

// El `id` es el que viaja a la API; la etiqueta es la que se lee. No se
// deriva una de la otra: "otoño_invierno" con el guion bajo cambiado por un
// espacio no da "Otoño-Invierno", y capitalizar por CSS tampoco alcanza.
//
// Se llama `id` y no `valor` porque es lo que espera el combobox, que es el
// mismo componente que usan Categoría y Proveedor (acá sin buscador: con
// tres opciones no hay nada que buscar).
const TEMPORADAS = [
    { id: 'atemporal', etiqueta: 'Atemporal' },
    { id: 'otoño_invierno', etiqueta: 'Otoño-Invierno' },
    { id: 'primavera_verano', etiqueta: 'Primavera-Verano' },
];

// A partir de cuántos caracteres el campo Descripción empieza a buscar
// productos parecidos. Es el mismo número que aplica el backend
// (`MINIMO_CARACTERES_SIMILARES` en services/productos.py), que es donde
// vive la regla: acá está solo para no pedirle a la API lo que ya se sabe
// que va a volver vacío. Si cambia allá, cambia acá.
const MINIMO_SIMILARES = 10;

/**
 * Texto comparable: sin mayúsculas, sin tildes y sin espacios de más.
 *
 * Es la misma normalización con la que el backend decide si dos
 * descripciones son la misma (`sin_tildes()` + `lower()` en
 * services/productos.py, y el índice único de la migración 0020),
 * replicada acá SOLO para avisar antes de mandar el alta. Quien decide
 * sigue siendo el backend, que además compara contra el catálogo entero y
 * no contra las pocas sugerencias que se muestran.
 */
function textoPlano(valor) {
    return (valor || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .split(/\s+/)
        .filter(Boolean)
        .join(' ');
}

function abmProductos() {
    return {
        TEMPORADAS,

        // Filas del listado. Son VARIANTES, no productos: un producto con
        // tres variantes ocupa tres filas, porque cada una tiene su stock y
        // su etiqueta.
        variantes: [],
        categorias: [],
        proveedores: [],
        total: 0,
        cargando: false,

        // Diálogo de confirmación de las acciones destructivas.
        confirmacion: { abierta: false, titulo: '', mensaje: '', accion: () => {} },

        // Un solo campo de texto que resuelve las tres formas de nombrar un
        // artículo: el código de la etiqueta, el SKU o parte de la
        // descripción. Lo desambigua el backend (ver `listar_variantes`).
        filtros: {
            busqueda: '', categoria_id: '', proveedor_id: '', temporada: '',
            // 'true' = solo activos, que es como arranca la pantalla.
            // Vacío = todos. Es string y no booleano para que entre sin
            // cambios en el bucle que arma los query params.
            activo: 'true',
        },

        // `varianteId` acota el panel al código desde el que se abrió; en
        // null muestra todas las variantes del producto.
        detalle: { abierto: false, producto: null, varianteId: null },

        // Alta de variante. `reemplazaBase` se resuelve al abrir el modal y
        // sirve para avisar ANTES de confirmar que el código de la BASE va a
        // desaparecer: si ya se imprimió esa etiqueta, queda sin respaldo y
        // el sistema no tiene forma de saberlo.
        variante: {
            abierto: false, guardando: false, reemplazaBase: false,
            sufijo: '', descripcion_sufijo: '', sku_proveedor: '',
            ubicacion_deposito: '',
        },

        // Edición de una variante ya creada. El sufijo NO está: entra en el
        // código, que se congela porque la etiqueta ya se imprimió.
        edicionVariante: {
            abierto: false, guardando: false, id: null, codigo: '', proveedorId: null,
            descripcion_sufijo: '', sku_proveedor: '', ubicacion_deposito: '',
            precio_usd: '',
        },

        // Precio en pesos que resultaría del USD tipeado en el modal de
        // variante. Lo calcula el backend, igual que el del producto.
        previewVar: { precio_venta: null },

        // Valores informativos del formulario. null = todavía sin datos
        // suficientes (falta el proveedor o el precio).
        preview: { dolar_proveedor: null, precio_venta: null },

        // Productos ya cargados con descripción parecida a la que se está
        // tipeando, acotados a la categoría y el proveedor elegidos.
        //
        // Sirve para dos cosas: ver que el artículo tal vez ya existe antes
        // de duplicarlo —el backend rechaza el alta si los tres coinciden—
        // y poder adoptar el nombre con el que quedó cargado, para que el
        // catálogo no tenga "Cadena plata 925" y "cadena de plata 925" como
        // si fueran cosas distintas.
        //
        // `resaltado` es el índice de la fila marcada con las flechas; -1
        // es "ninguna", que es como se abre.
        similares: { abierto: false, buscando: false, lista: [], resaltado: -1 },

        // Número de la última búsqueda pedida. Las respuestas pueden llegar
        // desordenadas —una consulta corta tarda menos que la anterior— y
        // sin esto la lista podría quedar mostrando el resultado de un texto
        // que ya no está en el campo.
        similaresToken: 0,

        form: {
            abierto: false, guardando: false, id: null, sku: '',
            descripcion: '', categoria_id: '', proveedor_id: '', precio_usd: '',
            sku_proveedor: '', descuento_producto: '', peso_gramos: '',
            temporada: 'atemporal', stock_infinito: false,
            // La categoría se elige bajando por el árbol: un select por
            // nivel. Acá van los ids elegidos desde la raíz, sin huecos, así
            // que el largo del array ES la cantidad de niveles ya elegidos.
            //
            // `categoria_id` sigue siendo el que viaja a la API: es el
            // último de esta ruta. Puede ser un nodo intermedio mientras la
            // cascada está a medias; lo que exige llegar a la hoja es
            // `categoriaCompleta()`, que gobierna el botón Guardar.
            categoriaRuta: [],
            // Foto elegida en el alta. No se sube acá: el endpoint de fotos
            // cuelga de `/productos/{id}/fotos` y ese id no existe hasta
            // que el producto está creado. Queda esperando en el formulario
            // y se sube apenas hay id. `previo` es el object URL de la
            // miniatura, que hay que revocar para no filtrar memoria.
            foto: { archivo: null, previo: '' },
        },

        /* --- Formato: la API manda números, no strings con símbolo --- */

        /**
         * Importe en pesos, mostrando EXACTAMENTE lo que guarda el backend.
         *
         * Los decimales aparecen solo si existen. La versión anterior usaba
         * `maximumFractionDigits: 0` y aplicaba su propio redondeo
         * half-expand: con el `redondeo` del sistema en 0,50 un precio
         * guardado como 2000,50 se mostraba "$2.001", y uno de 1234,49 se
         * mostraba "$1.234" — menos de lo que se cobra. El redondeo del
         * precio es CEIL y lo hace el backend; la pantalla no puede volver
         * a redondear por su cuenta.
         *
         * Hoy el redondeo configurado es 1000, así que los precios no
         * tienen decimales y el defecto no se veía. Depende de un valor de
         * configuración, no de una garantía.
         */
        pesos(valor) {
            if (valor === null || valor === undefined) return '—';
            const n = Number(valor);
            const decimales = Number.isInteger(n) ? 0 : 2;
            return n.toLocaleString('es-AR', {
                style: 'currency',
                currency: 'ARS',
                minimumFractionDigits: decimales,
                maximumFractionDigits: decimales,
            });
        },

        usd(valor) {
            if (valor === null || valor === undefined) return '—';
            return Number(valor).toLocaleString('es-AR', {
                style: 'currency', currency: 'USD',
            });
        },

        /* --- Categorías --- */

        /**
         * Camino completo de una categoría: "Calzado - Zapatillas - Deportivas".
         *
         * Se arma acá y no en la API porque `categorias` ya está cargado en
         * memoria con el `parent_id` de cada nodo: recorrer hacia arriba no
         * cuesta ninguna consulta, mientras que pedirle la ruta al backend
         * por cada fila del listado sería un N+1. Además el separador es
         * presentación, y la API devuelve datos crudos (Principio 1).
         *
         * Si el catálogo todavía no llegó, devuelve el nombre suelto; al
         * llegar, Alpine vuelve a renderizar con la ruta completa.
         */
        rutaCategoria(categoria) {
            if (!categoria) return '—';

            const ids = this.rutaDeIds(categoria.id);
            if (!ids.length) return categoria.nombre || '—';

            const porId = new Map(this.categorias.map((c) => [c.id, c]));
            return ids.map((id) => porId.get(id).nombre).join(' - ');
        },

        /**
         * Los ids desde la raíz hasta la categoría dada, ella incluida.
         *
         * Es el mismo recorrido hacia arriba que necesitan el camino escrito
         * del listado y la cascada de selects del formulario, escrito una
         * sola vez (Principio 2). Devuelve vacío si la categoría no está en
         * el catálogo cargado.
         */
        rutaDeIds(categoriaId) {
            const porId = new Map(this.categorias.map((c) => [c.id, c]));
            const ids = [];

            let actual = porId.get(Number(categoriaId));
            // El árbol tiene 5 niveles como máximo; el tope corta igual por
            // si un dato quedara inconsistente.
            for (let i = 0; i < 5 && actual; i++) {
                ids.unshift(actual.id);
                actual = actual.parent_id ? porId.get(actual.parent_id) : null;
            }
            return ids;
        },

        /* --- Categoría en cascada: un select por nivel --- */

        /**
         * Las categorías que puede ofrecer el select de ese nivel.
         *
         * El primero muestra las raíces; los demás, solo lo que cuelga de lo
         * elegido en el nivel de arriba. Es lo que hace que no haya que
         * reconocer la rama leyendo el camino completo en cada opción: en
         * cada paso se ve nada más que lo que sigue.
         */
        opcionesCategoria(nivel) {
            if (nivel === 1) return this.categorias.filter((c) => !c.parent_id);

            const padre = this.form.categoriaRuta[nivel - 2];
            if (!padre) return [];
            return this.categorias.filter((c) => c.parent_id === Number(padre));
        },

        /**
         * Si el select de ese nivel se muestra.
         *
         * El primero siempre. Los demás aparecen recién cuando el de arriba
         * tiene valor, y solo si hay algo para elegir: cuando la categoría
         * elegida no tiene hijos, la cascada se termina ahí.
         */
        nivelCategoriaVisible(nivel) {
            if (nivel === 1) return true;
            if (!this.form.categoriaRuta[nivel - 2]) return false;
            return this.opcionesCategoria(nivel).length > 0;
        },

        /** Cuántos selects hay a la vista: es lo que define el ancho del modal. */
        nivelesCategoriaVisibles() {
            let visibles = 0;
            for (let nivel = 1; nivel <= 5; nivel++) {
                if (this.nivelCategoriaVisible(nivel)) visibles++;
            }
            return visibles;
        },

        /**
         * Registra lo elegido en un nivel y descarta lo que colgaba de lo
         * anterior.
         *
         * Cambiar el Tipo invalida el Material que estaba puesto: era hijo de
         * otra rama. Se corta la cola en vez de dejarla, que es lo que haría
         * que el producto terminara guardado en una categoría que ya no se
         * ve en pantalla.
         *
         * Se reemplaza el array entero y no se lo trunca con `length`: el
         * `x-effect` de cada combobox depende de `form.categoriaRuta`, y
         * cambiar la propiedad es lo que hace que los de abajo se vacíen.
         */
        elegirCategoria(nivel) {
            const elegido = this.form.categoriaRuta[nivel - 1];
            this.form.categoriaRuta = this.form.categoriaRuta.slice(0, nivel);
            this.form.categoria_id = elegido || '';
            // La lista de descripciones parecidas está acotada a la
            // categoría: al moverla, queda vieja.
            this.buscarSimilares();
        },

        /**
         * Si la cascada llegó hasta el final.
         *
         * Es la traducción de "todos los selects visibles son obligatorios":
         * si quedara uno a la vista sin elegir, sería porque lo último
         * elegido todavía tiene hijos.
         */
        categoriaCompleta() {
            const ruta = this.form.categoriaRuta;
            if (!ruta.length || !ruta[ruta.length - 1]) return false;
            return this.opcionesCategoria(ruta.length + 1).length === 0;
        },

        /* --- Carga --- */

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams();
                for (const [clave, valor] of Object.entries(this.filtros)) {
                    if (valor !== '' && valor !== null) params.set(clave, valor);
                }

                // Listado a nivel VARIANTE: cada fila es lo que tiene stock y
                // lo que dice una etiqueta. `/productos` sigue existiendo para
                // el detalle y el formulario, que trabajan sobre el producto.
                const resp = await fetch('/api/v1/productos/variantes?' + params, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo cargar el listado');

                const datos = await resp.json();
                this.variantes = datos.resultados;
                this.total = datos.total;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        /** Categorías y proveedores para los selectores de filtro y del form. */
        async cargarCatalogos() {
            const [cats, provs] = await Promise.all([
                fetch('/api/v1/categorias', { credentials: 'same-origin' }),
                fetch('/api/v1/proveedores', { credentials: 'same-origin' }),
            ]);
            if (cats.ok) this.categorias = await cats.json();
            if (provs.ok) {
                // Solo los activos: el backend rechaza cargar un producto
                // de un proveedor dado de baja.
                this.proveedores = (await provs.json()).filter((p) => p.estado === 'activo');
            }

            // La cascada de categorías se arma recorriendo el árbol hacia
            // arriba, así que necesita este catálogo. Si alguien alcanzó a
            // abrir la edición de un producto antes de que llegara, la ruta
            // quedó vacía y no se recompone sola: se rehace acá.
            if (this.form.abierto && this.form.categoria_id
                && !this.form.categoriaRuta.length) {
                this.form.categoriaRuta = this.rutaDeIds(this.form.categoria_id);
            }
        },

        limpiar() {
            // 'Limpiar filtros' vuelve al estado de entrada, que incluye
            // el switch en Sí: limpiar no es 'mostrar todo'.
            this.filtros = {
                busqueda: '', categoria_id: '', proveedor_id: '', temporada: '',
                activo: 'true',
            };
            this.cargar();
        },

        /* --- Detalle --- */

        /**
         * La fila trae un resumen del producto, no el producto entero: le
         * faltan `variantes` y `fotos`, que son lo que muestra el panel. Se
         * pide el detalle completo en vez de engordar cada fila del listado
         * con las variantes hermanas y las fotos de todas.
         *
         * `varianteId` acota el panel a la fila desde la que se abrió: se
         * hizo clic en un código concreto, así que mostrar también sus
         * hermanas obliga a buscar de nuevo cuál era. En null (al agregar
         * una variante) se muestran todas.
         */
        async abrirProducto(productoId, { editar = false, varianteId = null } = {}) {
            try {
                const resp = await fetch('/api/v1/productos/' + productoId, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo abrir el producto');
                const producto = await resp.json();

                if (editar) this.abrirEdicion(producto);
                else this.detalle = { abierto: true, producto, varianteId };
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        /**
         * Variantes que muestra el panel: la elegida, o todas si se entró
         * sin elegir ninguna.
         */
        variantesVisibles() {
            const todas = this.detalle.producto?.variantes || [];
            if (!this.detalle.varianteId) return todas;
            return todas.filter((v) => v.id === this.detalle.varianteId);
        },

        /** Cuántas hermanas quedan fuera de la vista, para poder decirlo. */
        variantesOcultas() {
            const todas = this.detalle.producto?.variantes || [];
            return this.detalle.varianteId ? todas.length - 1 : 0;
        },

        /**
         * Fotos que muestra el panel, con fallback:
         * - Si hay una variante seleccionada y tiene fotos propias → esas.
         * - Si no → las fotos del producto (compartidas).
         */
        fotosVisibles() {
            const p = this.detalle.producto;
            if (!p) return [];
            if (this.detalle.varianteId) {
                const v = (p.variantes || []).find(
                    (v) => v.id === this.detalle.varianteId
                );
                if (v?.fotos?.length) return v.fotos;
            }
            return p.fotos || [];
        },

        /**
         * TRUE si las fotos que se muestran son de una variante (no las
         * compartidas del producto). Sirve para que subirFoto sepa si
         * mandar variante_id o no.
         */
        fotosDeVariante() {
            const p = this.detalle.producto;
            if (!p || !this.detalle.varianteId) return false;
            const v = (p.variantes || []).find(
                (v) => v.id === this.detalle.varianteId
            );
            return !!(v?.fotos?.length);
        },

        /* --- Alta de variante --- */

        abrirVariante() {
            const variantes = this.detalle.producto?.variantes || [];
            this.variante = {
                abierto: true,
                guardando: false,
                // La primera variante real reemplaza a la BASE. Si el
                // producto ya tiene variantes, no hay BASE que perder.
                reemplazaBase: variantes.some((v) => v.es_base),
                sufijo: '',
                descripcion_sufijo: '',
                sku_proveedor: '',
                ubicacion_deposito: '',
            };
        },

        /**
         * Nombre del proveedor elegido. En edición el proveedor no se puede
         * cambiar —no está en `ProductoActualizar` ni en el servicio— así que
         * el formulario lo muestra como dato fijo en vez de como desplegable.
         */
        nombreProveedor() {
            const id = Number(this.form.proveedor_id);
            return this.proveedores.find((p) => p.id === id)?.nombre || '—';
        },

        /** Sufijos ya usados: sirven para avisar antes de que la API rechace. */
        sufijosUsados() {
            return (this.detalle.producto?.variantes || [])
                .filter((v) => !v.es_base)
                .map((v) => v.sufijo);
        },

        /** Cómo va a quedar el código, para verlo antes de confirmar. */
        codigoPrevisto() {
            const sufijo = (this.variante.sufijo || '').toUpperCase();
            if (!sufijo) return '';
            // Se toma el prefijo de una variante existente en vez de armarlo
            // acá: la letra de la empresa la decide el backend y el frontend
            // no tiene por qué conocerla (Principio 1).
            const alguna = (this.detalle.producto?.variantes || [])[0];
            if (!alguna) return '';
            const base = alguna.es_base
                ? alguna.codigo_completo
                : alguna.codigo_completo.slice(0, -1);
            return base + sufijo;
        },

        /* --- Edición de una variante --- */

        abrirEdicionVariante(v) {
            this.edicionVariante = {
                abierto: true,
                guardando: false,
                id: v.id,
                // Solo informativo: el código no se edita.
                codigo: v.codigo_completo + v.verificador,
                proveedorId: this.detalle.producto.proveedor_id,
                descripcion_sufijo: v.descripcion_sufijo || '',
                // Vacío cuando no tiene el suyo: el placeholder dice que en
                // ese caso usa el del producto.
                sku_proveedor: v.sku_proveedor || '',
                ubicacion_deposito: v.ubicacion_deposito || '',
                // Vacío cuando no tiene precio propio: el placeholder dice
                // que en ese caso usa el del producto.
                precio_usd: v.precio_usd ?? '',
            };
            this.previewVariante();
        },

        /** Precio en pesos del USD tipeado, resuelto por el backend. */
        async previewVariante() {
            const usd = Number(this.edicionVariante.precio_usd);
            if (!usd || usd <= 0) {
                this.previewVar = { precio_venta: null };
                return;
            }
            try {
                const params = new URLSearchParams({
                    proveedor_id: this.edicionVariante.proveedorId,
                    precio_usd: this.edicionVariante.precio_usd,
                });
                const resp = await fetch('/api/v1/productos/precio-preview?' + params, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error();
                this.previewVar = await resp.json();
            } catch {
                // Silencioso: es informativo y no puede trabar el formulario.
                this.previewVar = { precio_venta: null };
            }
        },

        async guardarEdicionVariante() {
            const e = this.edicionVariante;
            e.guardando = true;
            try {
                const resp = await fetch('/api/v1/productos/variantes/' + e.id, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        descripcion_sufijo: e.descripcion_sufijo,
                        // null explícito = volver al precio del producto. El
                        // backend distingue esto de "no lo mandes".
                        precio_usd: e.precio_usd === '' ? null : e.precio_usd,
                        // Mismo trato: vaciarlo devuelve la variante al
                        // código de proveedor del producto.
                        sku_proveedor: e.sku_proveedor === '' ? null : e.sku_proveedor,
                        // El backend normaliza; '' sería guardar una ubicación
                        // vacía en vez de ninguna.
                        ubicacion_deposito: e.ubicacion_deposito || null,
                    }),
                });
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo guardar la variante');
                }
                window.toast('Variante actualizada', 'exito');
                e.abierto = false;
                // Se recarga el panel para ver el cambio sin cerrarlo.
                await this.abrirProducto(this.detalle.producto.id,
                                         { varianteId: this.detalle.varianteId });
                this.cargar();
            } catch (err) {
                window.toast(err.message, 'error');
            } finally {
                e.guardando = false;
            }
        },

        async guardarVariante() {
            const sufijo = (this.variante.sufijo || '').trim().toUpperCase();
            if (!sufijo) return;

            this.variante.guardando = true;
            try {
                const resp = await fetch(
                    `/api/v1/productos/${this.detalle.producto.id}/variantes`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify({
                            sufijo,
                            descripcion_sufijo: this.variante.descripcion_sufijo,
                            // Vacío = null = usa el del producto.
                            sku_proveedor: this.variante.sku_proveedor || null,
                            // El backend normaliza el texto; mandar '' sería
                            // guardar una ubicación vacía en vez de ninguna.
                            ubicacion_deposito: this.variante.ubicacion_deposito || null,
                        }),
                    }
                );
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo agregar la variante');
                }
                window.toast('Variante agregada', 'exito');
                // Se cierra SOLO el formulario: la ficha queda abierta con la
                // variante recién creada a la vista y "Agregar variante" a un
                // clic. Un producto que viene en colores o talles necesita
                // varias seguidas, y cerrando todo había que volver a
                // buscarlo en el listado por cada una.
                this.variante.abierto = false;

                // Se relee sin acotar a ninguna variante por dos motivos: la
                // recién creada tiene que verse —el panel filtrado por un
                // código la escondería—, y si era la primera, el backend
                // acaba de eliminar la BASE que el panel venía mostrando, así
                // que filtrar por ese id dejaría la ficha vacía.
                await this.abrirProducto(this.detalle.producto.id, { varianteId: null });
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.variante.guardando = false;
            }
        },

        /* --- Vista previa del precio --- */

        /**
         * Pide al backend el dólar del proveedor y el precio en pesos.
         *
         * No se calcula acá a propósito: el múltiplo de redondeo vive en
         * configuracion_sistema y la fórmula usa CEIL. Replicarla en JS
         * haría que la vista previa dejara de coincidir con lo que se
         * guarda apenas cambie la configuración (Principio 2).
         */
        async calcularPreview() {
            const proveedor = Number(this.form.proveedor_id);
            const usd = Number(this.form.precio_usd);

            if (!proveedor || !usd || usd <= 0) {
                this.preview = { dolar_proveedor: null, precio_venta: null };
                return;
            }

            try {
                const params = new URLSearchParams({
                    proveedor_id: proveedor,
                    precio_usd: this.form.precio_usd,
                });
                const resp = await fetch('/api/v1/productos/precio-preview?' + params, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error();
                this.preview = await resp.json();
            } catch {
                // Silencioso: es informativo y no puede trabar la carga.
                this.preview = { dolar_proveedor: null, precio_venta: null };
            }
        },

        /* --- Fotos --- */

        /**
         * Refresca el producto abierto en el panel.
         *
         * Tras subir o borrar una foto hace falta releer el producto: el
         * objeto del panel es el del listado, y su lista de fotos quedó
         * vieja. Se recarga el listado además, para que la miniatura del
         * producto también se actualice.
         */
        async refrescarDetalle() {
            const resp = await fetch('/api/v1/productos/' + this.detalle.producto.id, {
                credentials: 'same-origin',
            });
            if (resp.ok) this.detalle.producto = await resp.json();
            this.cargar();
        },

        async subirFoto(evento) {
            const archivo = evento.target.files?.[0];
            if (!archivo) return;
            // Se limpia el input: sin esto, subir el mismo archivo dos
            // veces seguidas no dispara el change la segunda vez.
            evento.target.value = '';

            const cuerpo = new FormData();
            cuerpo.append('archivo', archivo);

            // Si se está viendo una variante específica, la foto va a esa
            // variante; si no, al producto (compartida).
            let url = `/api/v1/productos/${this.detalle.producto.id}/fotos`;
            if (this.detalle.varianteId) {
                url += `?variante_id=${this.detalle.varianteId}`;
            }

            try {
                const resp = await fetch(
                    url,
                    { method: 'POST', credentials: 'same-origin', body: cuerpo }
                );
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo subir la foto');
                }
                window.toast('Foto subida', 'exito');
                await this.refrescarDetalle();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        async marcarPrincipal(foto) {
            try {
                const resp = await fetch(`/api/v1/productos/fotos/${foto.id}/principal`, {
                    method: 'PATCH',
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo marcar como principal');
                await this.refrescarDetalle();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        async borrarFoto(foto) {
            try {
                const resp = await fetch(`/api/v1/productos/fotos/${foto.id}`, {
                    method: 'DELETE',
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error('No se pudo eliminar la foto');
                window.toast('Foto eliminada', 'exito');
                await this.refrescarDetalle();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        /* --- Descripciones parecidas --- */

        /**
         * Busca productos ya cargados con descripción parecida a la que se
         * está tipeando, dentro de la categoría y el proveedor elegidos.
         *
         * El umbral de caracteres lo aplica también el backend: acá está
         * para no pedir lo que ya se sabe que vuelve vacío.
         */
        async buscarSimilares() {
            const texto = (this.form.descripcion || '').trim();

            // Solo en el ALTA. En la edición la descripción ya viene puesta:
            // el desplegable se abriría solo al abrir el formulario y encima
            // ofrecería el producto que se está editando.
            if (this.form.id || texto.length < MINIMO_SIMILARES) {
                this.cerrarSimilares();
                return;
            }

            const token = ++this.similaresToken;
            this.similares.buscando = true;
            try {
                const params = new URLSearchParams({ descripcion: texto });
                // Los dos son obligatorios para guardar, pero se puede estar
                // tipeando antes de elegirlos: sin ellos la búsqueda sale
                // sobre todo el catálogo, que ofrece de más pero no de menos.
                if (this.form.categoria_id) {
                    params.set('categoria_id', this.form.categoria_id);
                }
                if (this.form.proveedor_id) {
                    params.set('proveedor_id', this.form.proveedor_id);
                }

                const resp = await fetch('/api/v1/productos/similares?' + params, {
                    credentials: 'same-origin',
                });
                if (!resp.ok) throw new Error();
                const lista = await resp.json();

                // Llegó tarde: ya se pidió otra búsqueda y esta corresponde a
                // un texto que el campo ya no tiene.
                if (token !== this.similaresToken) return;

                this.similares.lista = lista;
                this.similares.abierto = lista.length > 0;
                this.similares.resaltado = -1;
            } catch {
                // Silencioso: es una ayuda para no duplicar, y no puede
                // trabar la carga del producto.
                if (token === this.similaresToken) this.cerrarSimilares();
            } finally {
                if (token === this.similaresToken) this.similares.buscando = false;
            }
        },

        cerrarSimilares() {
            this.similares = { abierto: false, buscando: false, lista: [], resaltado: -1 };
        },

        /** Mueve la fila marcada con las flechas, dando la vuelta en los extremos. */
        moverSimilar(paso) {
            if (!this.similares.abierto || !this.similares.lista.length) return;
            const ultimo = this.similares.lista.length - 1;
            const siguiente = this.similares.resaltado + paso;
            if (siguiente < 0) this.similares.resaltado = ultimo;
            else if (siguiente > ultimo) this.similares.resaltado = 0;
            else this.similares.resaltado = siguiente;
        },

        /**
         * Copia al campo la descripción del producto elegido.
         *
         * Es para completarla, no para dejarla igual: dos productos del
         * mismo proveedor y categoría no pueden llamarse idéntico —lo
         * rechaza el backend—, así que lo que se adopta es la forma de
         * nombrar ("Cadena plata 925" y no "cadena de plata 925") y después
         * se le agrega lo que distingue a este.
         */
        elegirSimilar(p) {
            if (!p) return;
            this.form.descripcion = p.descripcion;
            // Se cierra el desplegable pero la lista NO se descarta: el texto
            // quedó idéntico al de un producto que ya existe, y es la lista lo
            // que hace que `duplicadoExacto()` lo avise en el acto en vez de
            // esperar al error del alta. Al seguir escribiendo se rehace.
            this.similares.abierto = false;
            this.similares.resaltado = -1;
        },

        /**
         * El producto sugerido cuya descripción es EXACTAMENTE la tipeada, o
         * null si no hay ninguno.
         *
         * Con eso el formulario avisa del choque antes de mandar el alta, en
         * vez de que aparezca como error después de apretar Crear.
         *
         * Solo con categoría y proveedor elegidos: la lista se acota con
         * esos dos, y sin ellos un nombre repetido en OTRA categoría no es
         * ningún choque. Es una ayuda, no el control: el que decide es el
         * backend, que compara contra el catálogo entero.
         */
        duplicadoExacto() {
            if (this.form.id || !this.form.categoria_id || !this.form.proveedor_id) {
                return null;
            }
            const texto = textoPlano(this.form.descripcion);
            if (!texto) return null;
            return this.similares.lista.find((p) => textoPlano(p.descripcion) === texto) || null;
        },

        /* --- Alta y edición --- */

        abrirAlta() {
            this.quitarFoto();
            this.cerrarSimilares();
            this.form = {
                abierto: true, guardando: false, id: null, sku: '',
                descripcion: '', categoria_id: '', proveedor_id: '', precio_usd: '',
                sku_proveedor: '', descuento_producto: '', peso_gramos: '',
                temporada: 'atemporal', stock_infinito: false,
                // Sin nada elegido queda a la vista un solo select, el del
                // primer nivel.
                categoriaRuta: [],
                foto: { archivo: null, previo: '' },
            };
            this.preview = { dolar_proveedor: null, precio_venta: null };
        },

        /* --- Foto del alta --- */

        /**
         * Guarda el archivo elegido y arma la miniatura, sin subir nada: no
         * hay a qué producto colgársela todavía.
         *
         * Una sola foto y no las cinco: el alta es el momento de dejar el
         * producto identificable de un vistazo en el listado, y el resto se
         * carga desde la ficha, que ya tiene la grilla con "principal" y
         * "borrar".
         */
        elegirFoto(evento) {
            const archivo = evento.target.files?.[0];
            // Se limpia el input: sin esto, elegir el mismo archivo dos
            // veces seguidas no dispara el change la segunda vez.
            evento.target.value = '';
            if (!archivo) return;

            this.quitarFoto();
            this.form.foto = { archivo, previo: URL.createObjectURL(archivo) };
        },

        quitarFoto() {
            if (this.form.foto?.previo) URL.revokeObjectURL(this.form.foto.previo);
            this.form.foto = { archivo: null, previo: '' };
        },

        /**
         * Sube la foto que esperaba en el formulario, ya con el producto
         * creado.
         *
         * Devuelve si pudo. El error NO se propaga: el producto ya está
         * guardado y hacer fallar todo el alta por la foto haría creer que
         * no se creó nada. Se avisa qué pasó y desde dónde arreglarlo.
         */
        async subirFotoDelAlta(productoId) {
            const archivo = this.form.foto?.archivo;
            if (!archivo) return true;

            const cuerpo = new FormData();
            cuerpo.append('archivo', archivo);

            try {
                const resp = await fetch(`/api/v1/productos/${productoId}/fotos`, {
                    method: 'POST', credentials: 'same-origin', body: cuerpo,
                });
                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo subir la foto');
                }
                return true;
            } catch (e) {
                window.toast(
                    `El producto se creó, pero la foto no se subió: ${e.message}. `
                    + 'Se puede cargar desde la ficha.',
                    'error'
                );
                return false;
            }
        },

        abrirEdicion(p) {
            // El buscador de parecidos es del alta: acá se limpia por si el
            // formulario venía de una y quedó la lista de aquella.
            this.cerrarSimilares();
            this.form = {
                abierto: true, guardando: false, id: p.id, sku: p.sku,
                descripcion: p.descripcion || '',
                categoria_id: p.categoria_id,
                // La cascada se abre con el camino del producto ya puesto,
                // un select por nivel, para poder cambiar desde donde haga
                // falta sin empezar de cero.
                categoriaRuta: this.rutaDeIds(p.categoria_id),
                proveedor_id: p.proveedor_id,
                precio_usd: p.precio_usd,
                sku_proveedor: p.sku_proveedor || '',
                descuento_producto: p.descuento_producto,
                peso_gramos: p.peso_gramos || '',
                temporada: p.temporada,
                stock_infinito: p.stock_infinito,
                foto: { archivo: null, previo: '' },
            };
            // En edición ya hay proveedor y precio: se muestra de entrada.
            this.calcularPreview();
        },

        /**
         * Guarda el producto.
         *
         * `conVariantes` es el segundo botón del alta: deja el producto
         * creado y sigue derecho al alta de su primera variante, en vez de
         * obligar a buscarlo en el listado, abrir la ficha y recién ahí
         * empezar. Es el camino de quien ya sabe que el producto viene en
         * colores o talles.
         */
        async guardar({ conVariantes = false } = {}) {
            this.form.guardando = true;
            try {
                const alta = !this.form.id;
                const cuerpo = {
                    categoria_id: Number(this.form.categoria_id),
                    descripcion: this.form.descripcion || null,
                    precio_usd: this.form.precio_usd,
                    sku_proveedor: this.form.sku_proveedor || null,
                    descuento_producto: this.form.descuento_producto || null,
                    peso_gramos: this.form.peso_gramos || null,
                    temporada: this.form.temporada,
                    stock_infinito: this.form.stock_infinito,
                };
                // El SKU y el precio de venta los genera el backend; el
                // proveedor solo se define en el alta.
                if (alta) cuerpo.proveedor_id = Number(this.form.proveedor_id);

                const resp = await fetch(
                    alta ? '/api/v1/productos' : '/api/v1/productos/' + this.form.id,
                    {
                        method: alta ? 'POST' : 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify(cuerpo),
                    }
                );

                if (!resp.ok) {
                    const error = await resp.json().catch(() => ({}));
                    throw new Error(error.detail || 'No se pudo guardar el producto');
                }

                const guardado = await resp.json();

                // La foto va después del alta y antes de cerrar: si falla,
                // el aviso aparece con el formulario todavía en pantalla.
                const habiaFoto = alta && !!this.form.foto.archivo;
                const fotoOk = alta && await this.subirFotoDelAlta(guardado.id);

                this.quitarFoto();
                this.form.abierto = false;
                window.toast(
                    alta
                        ? `Producto creado con SKU ${guardado.sku}`
                          + (habiaFoto && fotoOk ? ' y su foto' : '')
                        : 'Producto actualizado',
                    'exito'
                );
                this.cargar();

                if (alta && conVariantes) {
                    // El panel primero: `abrirVariante()` necesita saber si
                    // el producto todavía tiene la BASE, para avisar que la
                    // primera variante real la reemplaza.
                    await this.abrirProducto(guardado.id);
                    if (this.detalle.abierto) this.abrirVariante();
                }
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.form.guardando = false;
            }
        },

        /* --- Alta y baja lógica --- */

        /**
         * Pide confirmación antes de cambiar el estado de un producto.
         *
         * La baja se ejecutaba de una: un clic al lado de "Producto" en una
         * tabla donde cada fila es una variante, y el producto entero quedaba
         * desactivado con todas sus variantes. Un error ahí no avisa nada.
         */
        confirmarEstado(producto) {
            const desactivando = producto.activo;
            this.confirmacion = {
                abierta: true,
                titulo: desactivando ? 'Desactivar producto' : 'Activar producto',
                mensaje: desactivando
                    ? `¿Desactivar ${producto.descripcion}? Deja de aparecer para vender, `
                      + 'con todas sus variantes. No se borra: el stock y el historial '
                      + 'se conservan y se puede volver a activar.'
                    : `¿Activar ${producto.descripcion}? Vuelve a estar disponible para vender.`,
                accion: () => this.cambiarEstado(producto, !producto.activo),
            };
        },

        async cambiarEstado(p, activo) {
            this.confirmacion.abierta = false;
            try {
                const resp = await fetch(`/api/v1/productos/${p.id}/estado`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ activo }),
                });
                if (!resp.ok) throw new Error('No se pudo cambiar el estado');

                window.toast(activo ? 'Producto activado' : 'Producto desactivado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },
    };
}
