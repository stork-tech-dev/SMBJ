/* ==========================================================================
   Punto de venta mobile: home, escaneo, carrito, cobro y consulta de stock.

   Los cinco componentes están en un archivo porque son UN flujo y comparten
   la misma base (`ventaBase`): la vendedora entra por el home, escanea,
   revisa el carrito y cobra. Separarlos en cinco archivos duplicaría el
   manejo de errores y la carga de la venta en curso en cada uno.

   Regla de oro de todo el archivo: **acá no se calcula ningún precio**. El
   total, los descuentos, las promociones y los recargos los devuelve el
   backend ya resueltos. Si la pantalla hiciera su propia cuenta y diera
   distinto, la vendedora vería un número y el cliente pagaría otro.

   La única cuenta que sí se hace es el reparto entre dos medios de pago
   —cuánto falta— y se hace para AYUDAR a completar el formulario; el
   backend la vuelve a validar antes de cobrar.
   ========================================================================== */

const API_VENTAS = '/api/v1/ventas';
const API_CLIENTES = '/api/v1/clientes';
const API_STOCK = '/api/v1/stock';

// Cuántos productos distintos se pueden sumar juntos al carrito desde la
// consulta de stock (con un filtro aplicado). Más que eso ya no es "estos
// que encontré", es agregar a ciegas.
const MAX_AGREGAR_JUNTOS = 4;
const API_TURNOS = '/api/v1/turnos';

// Implementación compartida en app.js (Principio 2): la usa también
// cambios_mobile.js. Resuelta en el momento de llamar y no acá arriba:
// este script no lleva `defer` y corre antes que app.js.
const pedir = (url, opciones) => window.pedir(url, opciones);

/* Lo que comparten las pantallas del flujo: la venta en curso y el formato
   de importes. */
function ventaBase() {
    return {
        venta: null,
        cargando: false,

        pesos: (v) => window.pesos(v),

        /* La venta abierta de este equipo, o null. Nunca crea una: abrir una
           venta es un acto de la vendedora, no un efecto de mirar una
           pantalla. */
        async traerEnCurso() {
            const datos = await pedir(`${API_VENTAS}/en-curso`);
            return datos.venta;
        },

        async cargarVenta() {
            this.cargando = true;
            try {
                const resumen = await this.traerEnCurso();
                // El endpoint de venta en curso devuelve el resumen; los
                // ítems y los pagos están en el detalle.
                this.venta = resumen ? await pedir(`${API_VENTAS}/${resumen.id}`) : null;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },
    };
}

/* ==========================================================================
   Pantalla 2 — Home
   ========================================================================== */

function homeVentas() {
    return {
        enCurso: null,
        pesos: (v) => window.pesos(v),

        async cargar() {
            try {
                const datos = await pedir(`${API_VENTAS}/en-curso`);
                this.enCurso = datos.venta;
            } catch (e) {
                // El home tiene que abrirse igual: un fallo del banner no
                // puede dejar a la vendedora sin acceso a los demás botones.
                this.enCurso = null;
            }
        },

        cerrarSesion: () => window.cerrarSesion(),
    };
}

/* ==========================================================================
   Pantalla 3 — Búsqueda de producto
   ========================================================================== */

function nuevaVenta() {
    return {
        ...ventaBase(),

        codigo: '',
        producto: null,
        aviso: null,
        buscando: false,
        agregando: false,

        // Sin stock, no se ofrece agregar: el aviso ya dice que puede ser
        // un error de código, y agregar igual sería vender lo que la
        // pantalla misma está diciendo que no hay en el local.
        get sinStock() {
            return !!this.producto && !this.producto.stock_infinito && this.producto.stock <= 0;
        },

        async iniciar() {
            // Abre la venta al entrar, o recupera la que estaba abierta: el
            // endpoint devuelve la existente en vez de crear una segunda.
            try {
                this.venta = await pedir(API_VENTAS, { method: 'POST', body: '{}' });
            } catch (e) {
                window.toast(e.message, 'error');
            }
            this.enfocar();

            // F2 vuelve el foco al campo: el lector escribe donde esté el
            // cursor, y si el foco se perdió el código se pierde con él.
            window.addEventListener('atajo-buscar', () => this.enfocar());
        },

        /* `$nextTick` y no un focus directo: cuando esto corre después de
           agregar un producto, Alpine todavía está redibujando y el input
           puede no estar en el DOM. */
        enfocar() {
            this.$nextTick(() => this.$refs.codigo?.focus());
        },

        async buscar() {
            const texto = this.codigo.trim();
            if (!texto) return;

            this.buscando = true;
            this.aviso = null;
            try {
                this.producto = await pedir(
                    `${API_VENTAS}/producto?codigo=${encodeURIComponent(texto)}`
                );
                // Se avisa ANTES de agregar, no después: la vendedora tiene
                // que poder mirar la foto y el stock antes de decidir.
                if (!this.producto.stock_infinito && this.producto.stock <= 0) {
                    this.aviso = 'Sin stock de este producto en el local: '
                        + 'controlá bien el código antes de continuar.';
                }
            } catch (e) {
                this.producto = null;
                window.toast(e.message, 'error');
                this.enfocar();
            } finally {
                this.buscando = false;
            }
        },

        async agregar() {
            if (!this.producto || !this.venta) return;

            this.agregando = true;
            try {
                const datos = await pedir(`${API_VENTAS}/${this.venta.id}/items`, {
                    method: 'POST',
                    body: JSON.stringify({ variante_id: this.producto.variante_id }),
                });

                this.venta = datos.venta;
                // El aviso del backend gana sobre el que calculó la pantalla:
                // él sabe cuántas unidades de esta variante ya hay en el
                // carrito, y con 1 en stock el segundo escaneo también avisa.
                if (datos.aviso) window.toast(datos.aviso, 'error');
                else window.toast('Agregado al carrito', 'exito');

                // Se limpia todo para el próximo escaneo: dejar el producto
                // en pantalla invita a tocar "Agregar" dos veces.
                this.producto = null;
                this.aviso = null;
                this.codigo = '';
                this.enfocar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.agregando = false;
            }
        },
    };
}

/* ==========================================================================
   Pantalla 4 — Carrito
   ========================================================================== */

function carritoVenta(puedeDescontar = false) {
    return {
        ...ventaBase(),

        puedeDescontar,
        motivos: [],
        porcentajes: [],
        tope: 50,

        descuento: {
            abierto: false, item_id: null, descripcion: '',
            motivo_id: '', porcentaje: null, tenia: false,
        },

        async cargar() {
            await this.cargarVenta();
            if (this.puedeDescontar) await this.cargarOpciones();
        },

        /* Los motivos y los porcentajes salen del backend, de la misma
           constante que valida. Una lista copiada acá terminaría ofreciendo
           un valor que la API rechaza. */
        async cargarOpciones() {
            try {
                const datos = await pedir(`${API_VENTAS}/opciones-descuento`);
                this.motivos = datos.motivos;
                this.porcentajes = datos.porcentajes;
                this.tope = Number(datos.tope);
            } catch (e) {
                this.motivos = [];
            }
        },

        async quitar(item) {
            try {
                this.venta = await pedir(
                    `${API_VENTAS}/${this.venta.id}/items/${item.id}`,
                    { method: 'DELETE' }
                );
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        async descartar() {
            if (!this.venta) return;
            try {
                await pedir(`${API_VENTAS}/${this.venta.id}`, { method: 'DELETE' });
                window.toast('Venta descartada', 'exito');
                window.location.href = '/ventas';
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        /* --- Descuento --- */

        abrirDescuento(item) {
            // Si el ítem ya tiene motivo, determinar si ese motivo tiene sugerido.
            const motivoActual = item.motivo_descuento_id
                ? this.motivos.find((m) => m.id === item.motivo_descuento_id)
                : null;
            const elige = !motivoActual || motivoActual.porcentaje_sugerido === null;

            this.descuento = {
                abierto: true,
                item_id: item.id,
                descripcion: item.variante?.producto?.descripcion || '',
                motivo_id: item.motivo_descuento_id || '',
                porcentaje: Number(item.descuento_item) || null,
                tenia: Number(item.descuento_item) > 0,
                // TRUE cuando el motivo no tiene sugerido: la vendedora elige de la lista.
                elige_vendedora: elige,
            };
        },

        /* Al elegir el motivo:
           - Si tiene porcentaje sugerido → se aplica directamente, sin lista.
           - Si no tiene sugerido → la vendedora elige de la lista. */
        alElegirMotivo() {
            const motivo = this.motivos.find((m) => m.id === Number(this.descuento.motivo_id));
            if (!motivo) {
                this.descuento.elige_vendedora = true;
                this.descuento.porcentaje = null;
                return;
            }
            if (motivo.porcentaje_sugerido !== null) {
                this.descuento.porcentaje = Number(motivo.porcentaje_sugerido);
                this.descuento.elige_vendedora = false;
            } else {
                this.descuento.porcentaje = null;
                this.descuento.elige_vendedora = true;
            }
        },

        async aplicarDescuento() {
            try {
                this.venta = await pedir(`${API_VENTAS}/${this.venta.id}/descuento`, {
                    method: 'POST',
                    body: JSON.stringify({
                        item_id: this.descuento.item_id,
                        motivo_id: Number(this.descuento.motivo_id),
                        porcentaje: this.descuento.porcentaje,
                    }),
                });
                this.descuento.abierto = false;
                window.toast('Descuento aplicado', 'exito');
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        async quitarDescuento() {
            try {
                this.venta = await pedir(`${API_VENTAS}/${this.venta.id}/descuento`, {
                    method: 'POST',
                    body: JSON.stringify({
                        item_id: this.descuento.item_id,
                        motivo_id: null,
                    }),
                });
                this.descuento.abierto = false;
                window.toast('Descuento quitado', 'exito');
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },
    };
}

/* ==========================================================================
   Pantalla 5 — Finalización de compra
   ========================================================================== */

function finalizarVenta() {
    return {
        ...ventaBase(),
        ...window.buscadorClientes(),

        medios: [],
        senas: [],
        saldoSenas: 0,
        // Si el cliente tiene seña, arranca en Sí: si dejó plata, lo normal
        // es que la use en esta compra.
        usarSena: true,
        // Una línea por medio de pago. Arranca con una: el caso normal es
        // pagar con uno solo.
        lineas: [{ medio_de_pago_id: null, monto: 0, plan_cuotas_id: null }],
        confirmando: false,
        confirmada: null,

        async cargar() {
            await this.cargarVenta();
            if (!this.venta) return;

            await this.cargarMedios();
            await this.cargarSenas();

            // La primera línea arranca cubriendo todo lo que la seña no
            // cubre: es lo que pasa cuando se paga con un solo medio, que es
            // la mayoría de las ventas.
            this.repartir(0);
            this.$watch('usarSena', () => this.repartir(0));

            // F10 confirma, como en el resto del sistema.
            window.addEventListener('atajo-confirmar', () => {
                if (this.puedeConfirmar && !this.confirmando) this.confirmar();
            });
        },

        async cargarMedios() {
            try {
                this.medios = await pedir(`${API_VENTAS}/${this.venta.id}/medios-de-pago`);
            } catch (e) {
                window.toast(e.message, 'error');
                this.medios = [];
            }
        },

        async cargarSenas() {
            if (!this.venta?.cliente) {
                this.senas = [];
                this.saldoSenas = 0;
                return;
            }
            try {
                this.senas = await pedir(`${API_CLIENTES}/${this.venta.cliente.id}/senas`);
                this.saldoSenas = this.senas.reduce((t, s) => t + Number(s.saldo), 0);
                this.usarSena = this.saldoSenas > 0;
            } catch (e) {
                this.senas = [];
                this.saldoSenas = 0;
            }
        },

        /* --- Cliente --- */

        async asociarCliente(clienteId) {
            try {
                this.venta = await pedir(`${API_VENTAS}/${this.venta.id}/cliente`, {
                    method: 'POST',
                    body: JSON.stringify({ cliente_id: clienteId }),
                });
                this.limpiarBusquedaCliente();

                // El cliente puede cambiar el total —trae promociones
                // propias— y con él cambian las señas y los planes que se
                // pueden ofrecer. Se recarga todo en vez de parchear.
                await this.cargarMedios();
                await this.cargarSenas();
                this.repartir(0);
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        /* --- Medios de pago --- */

        medioDe(linea) {
            return this.medios.find((m) => m.id === linea.medio_de_pago_id) || null;
        },

        /* --- Seña ---
           Preview de lo que calcula el backend al registrar los pagos: la
           seña cubre hasta el total y se consume entera. */

        /* El total de productos, tal como lo resolvió el backend. */
        get aCobrar() {
            return this.venta ? Number(this.venta.a_cobrar) : 0;
        },

        get senaAplicada() {
            if (!this.usarSena) return 0;
            return Math.min(this.saldoSenas, this.aCobrar);
        },

        get senaPerdida() {
            return Math.max(Math.round((this.saldoSenas - this.senaAplicada) * 100) / 100, 0);
        },

        get vencimientoSena() {
            return this.senas.length ? this.senas[0].vence_el : null;
        },

        /* Lo que tienen que cubrir los medios de pago: los productos menos
           la seña. Sin recargos: el recargo se suma después. */
        get aCubrir() {
            return Math.round((this.aCobrar - this.senaAplicada) * 100) / 100;
        },

        planesDe(linea) {
            return this.medioDe(linea)?.planes || [];
        },

        etiquetaPlan(plan) {
            const cuotas = plan.cuotas === 1 ? '1 pago' : `${plan.cuotas} cuotas`;
            return plan.sin_interes
                ? `${cuotas} sin interés`
                : `${cuotas} · +${Number(plan.recargo_cliente)}%`;
        },

        /* El recargo se calcula sobre el monto de ESTA línea, no sobre el
           total: si el cliente paga mitad en efectivo, no paga intereses por
           esa mitad. Es un preview — el backend lo vuelve a calcular. */
        recargoDe(linea) {
            const plan = this.planesDe(linea).find((p) => p.id === linea.plan_cuotas_id);
            if (!plan) return 0;
            return (Number(linea.monto) || 0) * Number(plan.recargo_cliente) / 100;
        },

        get recargoTotal() {
            return this.lineas.reduce((t, l) => t + this.recargoDe(l), 0);
        },

        /* Lo que falta asignar entre los medios. Se compara contra el total
           de PRODUCTOS, sin recargos: el recargo se suma después y no es algo
           que la vendedora reparta. */
        get faltante() {
            if (this.aCubrir <= 0) return 0;
            const asignado = this.lineas.reduce((t, l) => t + (Number(l.monto) || 0), 0);
            return Math.round((this.aCubrir - asignado) * 100) / 100;
        },

        get puedeConfirmar() {
            if (!this.venta?.items?.length) return false;
            // La seña cubre todo: no hay medios que elegir.
            if (this.aCubrir <= 0) return true;
            if (this.faltante !== 0) return false;
            return this.lineas.every((l) => l.medio_de_pago_id && Number(l.monto) > 0);
        },

        agregarLinea() {
            if (this.lineas.length >= 2) return;
            // El segundo medio arranca con lo que falta: es exactamente el
            // caso de uso —"$5.000 en efectivo y el resto con tarjeta"— y
            // ahorra la resta que si no hace la vendedora a mano.
            this.lineas.push({
                medio_de_pago_id: null,
                monto: Math.max(this.faltante, 0),
                plan_cuotas_id: null,
            });
        },

        quitarLinea(indice) {
            this.lineas.splice(indice, 1);
            // Lo que quedó suelto vuelve a la primera línea: dejarlo sin
            // asignar obligaría a corregir un monto que la vendedora no tocó.
            this.repartir(0);
        },

        alCambiarMedio(indice) {
            this.lineas[indice].plan_cuotas_id = null;
        },

        alCambiarMonto(indice) {
            this.repartir(indice);
        },

        /* Ajusta la OTRA línea para que las dos sumen el total. Con una sola
           línea, esa línea cubre todo.

           Es la ayuda de la que habla el flujo: la vendedora carga el
           primero y el sistema calcula el segundo. */
        repartir(indiceFijo) {
            const total = Math.max(this.aCubrir, 0);

            if (this.lineas.length === 1) {
                this.lineas[0].monto = total;
                return;
            }

            const fijo = Number(this.lineas[indiceFijo].monto) || 0;
            const otro = indiceFijo === 0 ? 1 : 0;
            this.lineas[otro].monto = Math.max(Math.round((total - fijo) * 100) / 100, 0);
        },

        recalcular() {
            // Cambiar el plan no mueve montos: solo el recargo, que se
            // recalcula solo por ser un getter.
        },

        /* --- Confirmación --- */

        async confirmar() {
            this.confirmando = true;
            try {
                // Dos pasos y no uno: registrar los pagos valida los planes y
                // la seña ANTES de tocar el stock. Si algo está mal, la
                // venta sigue abierta y corregible.
                await pedir(`${API_VENTAS}/${this.venta.id}/pagos`, {
                    method: 'POST',
                    body: JSON.stringify({
                        // Si la seña cubre todo, no va ningún medio.
                        pagos: this.aCubrir <= 0 ? [] : this.lineas.map((l) => ({
                            medio_de_pago_id: l.medio_de_pago_id,
                            monto: l.monto,
                            plan_cuotas_id: l.plan_cuotas_id || null,
                        })),
                        usar_sena: this.usarSena && this.saldoSenas > 0,
                    }),
                });

                this.confirmada = await pedir(`${API_VENTAS}/${this.venta.id}/confirmar`, {
                    method: 'POST',
                    body: '{}',
                });
                window.toast('Venta confirmada', 'exito');
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.confirmando = false;
            }
        },
    };
}

/* ==========================================================================
   Pantalla 7 — Consulta de stock
   ========================================================================== */

function consultaStockMobile(puntoDeVentaId) {
    return {
        // 0 para los roles sin dispositivo de local asignado (ven todo por
        // defecto): ahí no hay "mi sucursal" que separar del resto.
        puntoDeVentaId: Number(puntoDeVentaId) || 0,
        filas: [],
        total: 0,
        pagina: 1,
        tamano: 20,
        cargando: false,
        todosLosLocales: false,
        filtros: { busqueda: '' },

        // Filtro por categoría, elegida nivel por nivel (Categoría →
        // Material → Subcategoría). Filtra por la rama del último nivel
        // elegido; lo resuelve el backend (`categoria_id`).
        filtrosAbiertos: false,
        categorias: [],
        categoriaRuta: [],

        get categoriaId() {
            const elegidos = this.categoriaRuta.filter(Boolean);
            return elegidos.length ? elegidos[elegidos.length - 1] : '';
        },

        get categoriaTexto() {
            return this.categoriaId
                ? window.rutaCategoria(this.categorias, { id: Number(this.categoriaId) })
                : '';
        },

        async abrirFiltros() {
            this.filtrosAbiertos = !this.filtrosAbiertos;
            // Las categorías se piden una sola vez, la primera que se abre.
            if (this.filtrosAbiertos && !this.categorias.length) {
                try {
                    this.categorias = await pedir('/api/v1/categorias');
                } catch (e) {
                    window.toast(e.message, 'error');
                }
            }
        },

        elegirCategoria(nivel) {
            // Cambiar un nivel descarta lo elegido debajo.
            this.categoriaRuta = this.categoriaRuta.slice(0, nivel);
            this.buscar();
        },

        limpiarCategoria() {
            this.categoriaRuta = [];
            this.buscar();
        },

        pesos: (v) => window.pesos(v),

        // La sucursal propia primero; el resto abajo bajo "Otras Sucursales"
        // (ver el template). Es partición para MOSTRAR lo ya traído, no un
        // filtro nuevo: el filtro real es `todos_los_locales` en `cargar()`.
        get misFilas() {
            if (!this.puntoDeVentaId) return this.filas;
            return this.filas.filter((f) => f.punto_de_venta?.id === this.puntoDeVentaId);
        },
        get otrasFilas() {
            if (!this.puntoDeVentaId) return [];
            return this.filas.filter((f) => f.punto_de_venta?.id !== this.puntoDeVentaId);
        },

        // Lo que realmente queda para vender: el stock real menos lo que ya
        // está en MI carrito en curso (`reservado_carrito`, del backend).
        // Nunca negativo — dos vendedoras del mismo equipo no deberían
        // darse, pero si pasara, no hay "menos cero" que mostrar.
        disponible(f) {
            return Math.max(0, f.cantidad - (f.reservado_carrito || 0));
        },

        // Un solo botón, no uno por fila. Se ofrece cuando la búsqueda
        // resolvió a UN producto con stock DISPONIBLE acá, o —si la
        // vendedora ya acotó con un código o con los filtros de categoría—
        // a unos pocos (hasta MAX_AGREGAR_JUNTOS): ahí agrega todos los que
        // tienen disponible, previa confirmación.
        agregando: false,
        confirmacion: { abierta: false, titulo: '', mensaje: '', advertencia: '', accion: () => {} },

        get hayFiltro() {
            return this.filtros.busqueda.trim() !== '' || Boolean(this.categoriaId);
        },

        // Lo que realmente se puede agregar: las filas de este local con
        // disponible. Las que están en cero se muestran pero no se suman.
        get paraAgregar() {
            return this.misFilas.filter((f) => this.disponible(f) > 0);
        },

        get puedeAgregar() {
            const n = this.misFilas.length;
            if (n === 1) return this.paraAgregar.length === 1;
            return this.hayFiltro && n <= MAX_AGREGAR_JUNTOS && this.paraAgregar.length > 0;
        },

        get textoAgregar() {
            const n = this.paraAgregar.length;
            return n > 1 ? `Agregar ${n} productos al carrito` : 'Agregar al carrito de compra';
        },

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams({
                    pagina: this.pagina,
                    tamano: this.tamano,
                    // Sin stock no se puede vender, pero sí se puede querer
                    // saber que el producto existe y está en cero.
                    incluir_sin_stock: 'true',
                });
                if (this.filtros.busqueda) params.set('busqueda', this.filtros.busqueda);
                if (this.categoriaId) params.set('categoria_id', this.categoriaId);

                // Sin esto, un vendedor atado a un local por su dispositivo
                // no puede ver el stock de otro ni del CD: es la única
                // excepción de solo lectura a ese aislamiento.
                params.set('todos_los_locales', this.todosLosLocales ? 'true' : 'false');
                // Para que `disponible()` descuente lo que ya está en mi
                // propio carrito en curso.
                params.set('restar_carrito', 'true');

                const datos = await pedir(`${API_STOCK}?${params}`);

                // Acumula al pasar de página: en el celular es "ver más", no
                // paginación con números.
                this.filas = this.pagina === 1 ? datos.resultados : [...this.filas, ...datos.resultados];
                this.total = datos.total;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        buscar() {
            this.pagina = 1;
            this.cargar();
        },

        verMas() {
            this.pagina += 1;
            this.cargar();
        },

        // Mismo criterio que `nuevaVenta().iniciar()`: abre la venta en
        // curso de este equipo o recupera la que ya había, nunca una
        // segunda. Se queda en esta pantalla después de agregar — la
        // vendedora puede seguir consultando otros productos sin perder
        // la búsqueda.
        /**
         * Un producto: lo agrega directo, como siempre. Varios: primero pide
         * confirmación diciendo cuántos va a sumar, y solo con el "Agregar"
         * del diálogo los agrega.
         */
        agregarAlCarrito() {
            if (!this.puedeAgregar) return;
            const filas = this.paraAgregar;
            if (filas.length === 1) {
                this.agregarFilas(filas);
                return;
            }

            const sinStock = this.misFilas.length - filas.length;
            const nombre = (f) => `${f.variante.codigo_completo}${f.variante.verificador} `
                + `${f.variante.producto?.descripcion || ''}`
                + (f.variante.descripcion_sufijo ? ` — ${f.variante.descripcion_sufijo}` : '');
            this.confirmacion = {
                abierta: true,
                titulo: `Agregar ${filas.length} productos`,
                mensaje: filas.map(nombre).join(' · ')
                    + (sinStock ? ` (${sinStock} sin stock disponible no se agregan)` : ''),
                advertencia: `Vas a sumar ${filas.length} productos al carrito.`,
                accion: () => {
                    this.confirmacion.abierta = false;
                    this.agregarFilas(filas);
                },
            };
        },

        /**
         * Suma una unidad de cada fila a la venta en curso de este equipo
         * (la abre o la recupera, nunca una segunda). En orden, una por vez:
         * si una falla, sigue con las demás y avisa cuáles no entraron.
         */
        async agregarFilas(filas) {
            this.agregando = true;
            try {
                const venta = await pedir(API_VENTAS, { method: 'POST', body: '{}' });
                const avisos = [];
                let agregados = 0;
                for (const f of filas) {
                    try {
                        const datos = await pedir(`${API_VENTAS}/${venta.id}/items`, {
                            method: 'POST',
                            body: JSON.stringify({ variante_id: f.variante.id }),
                        });
                        agregados += 1;
                        if (datos.aviso) avisos.push(datos.aviso);
                    } catch (e) {
                        avisos.push(`${f.variante.codigo_completo}${f.variante.verificador}: ${e.message}`);
                    }
                }

                if (avisos.length) window.toast(avisos.join(' · '), 'error');
                if (agregados) {
                    window.toast(
                        agregados === 1 ? 'Agregado al carrito' : `${agregados} productos agregados al carrito`,
                        'exito',
                    );
                }

                // Refresca `reservado_carrito`: sin esto, el botón seguiría
                // ofreciendo agregar de más allá de lo que real queda
                // disponible en el local. `buscar()` no se puede esperar
                // (no devuelve su promesa), así que se repite acá.
                this.pagina = 1;
                await this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.agregando = false;
            }
        },
    };
}

/* ==========================================================================
   Pantalla 8 — Anular venta
   ========================================================================== */

function anularVenta(puntoDeVentaId) {
    return {
        puntoDeVentaId: Number(puntoDeVentaId) || 0,
        turno: null,
        ventas: [],
        cargando: false,

        pesos: (v) => window.pesos(v),

        anulacion: { abierta: false, enviando: false, venta: null, motivo: '', entendido: false },

        async cargar() {
            this.cargando = true;
            try {
                // Sin turno abierto no hay nada para anular: el backend lo
                // rechazaría igual, pero mejor no ofrecer una lista vacía de
                // ventas que después van a rebotar todas.
                this.turno = await pedir(`${API_TURNOS}/activo`);
                if (!this.turno) {
                    this.ventas = [];
                    return;
                }

                const params = new URLSearchParams({
                    punto_de_venta_id: this.puntoDeVentaId,
                    estado: 'confirmada',
                    fecha_desde: this.turno.fecha_apertura.slice(0, 10),
                    tamano: 50,
                });
                const datos = await pedir(`${API_VENTAS}?${params}`);
                this.ventas = datos.resultados;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        pedirAnulacion(v) {
            this.anulacion = { abierta: true, enviando: false, venta: v, motivo: '', entendido: false };
        },

        async anular() {
            this.anulacion.enviando = true;
            try {
                await pedir(`${API_VENTAS}/${this.anulacion.venta.id}/anular`, {
                    method: 'PATCH',
                    body: JSON.stringify({ motivo: this.anulacion.motivo || null }),
                });
                this.anulacion.abierta = false;
                window.toast('Venta anulada: stock y puntos revertidos', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.anulacion.enviando = false;
            }
        },
    };
}
