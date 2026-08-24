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

/* Llamada a la API con el manejo de error del sistema: el `detail` del
   backend es un mensaje pensado para la vendedora, así que se muestra tal
   cual en vez de un "error 409". */
async function pedir(url, opciones = {}) {
    const resp = await fetch(url, {
        credentials: 'same-origin',
        ...opciones,
        headers: opciones.body
            ? { 'Content-Type': 'application/json', ...(opciones.headers || {}) }
            : opciones.headers,
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || 'No se pudo completar la operación');
    }
    return resp.status === 204 ? null : resp.json();
}

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
            this.descuento = {
                abierto: true,
                item_id: item.id,
                descripcion: item.variante?.producto?.descripcion || '',
                motivo_id: item.motivo_descuento_id || '',
                porcentaje: Number(item.descuento_item) || null,
                tenia: Number(item.descuento_item) > 0,
            };
        },

        /* Al elegir el motivo se preselecciona su porcentaje sugerido. Que la
           vendedora pueda cambiarlo no es un agujero: es el caso "hoy hacemos
           30 en vez de 20", y el backend registra que se apartó. */
        alElegirMotivo() {
            const motivo = this.motivos.find((m) => m.id === Number(this.descuento.motivo_id));
            if (motivo && motivo.porcentaje_sugerido !== null) {
                this.descuento.porcentaje = Number(motivo.porcentaje_sugerido);
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

        medios: [],
        senas: [],
        saldoSenas: 0,
        clientes: [],
        clienteBusqueda: '',
        // Una línea por medio de pago. Arranca con una: el caso normal es
        // pagar con uno solo.
        lineas: [{ medio_de_pago_id: null, monto: 0, plan_cuotas_id: null, sena_id: null }],
        confirmando: false,
        confirmada: null,

        async cargar() {
            await this.cargarVenta();
            if (!this.venta) return;

            await this.cargarMedios();
            await this.cargarSenas();

            // La primera línea arranca cubriendo todo: es lo que pasa cuando
            // se paga con un solo medio, que es la mayoría de las ventas.
            this.lineas[0].monto = Number(this.venta.a_cobrar);

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
            } catch (e) {
                this.senas = [];
                this.saldoSenas = 0;
            }
        },

        /* --- Cliente --- */

        async buscarCliente() {
            const texto = this.clienteBusqueda.trim();
            if (texto.length < 2) {
                this.clientes = [];
                return;
            }
            try {
                this.clientes = await pedir(
                    `${API_CLIENTES}/buscar?q=${encodeURIComponent(texto)}`
                );
            } catch (e) {
                this.clientes = [];
            }
        },

        async asociarCliente(clienteId) {
            try {
                this.venta = await pedir(`${API_VENTAS}/${this.venta.id}/cliente`, {
                    method: 'POST',
                    body: JSON.stringify({ cliente_id: clienteId }),
                });
                this.clientes = [];
                this.clienteBusqueda = '';

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

        esSena(linea) {
            return !!this.medioDe(linea)?.es_sena;
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
            const asignado = this.lineas.reduce((t, l) => t + (Number(l.monto) || 0), 0);
            return Math.round((Number(this.venta?.a_cobrar || 0) - asignado) * 100) / 100;
        },

        get puedeConfirmar() {
            if (!this.venta?.items?.length) return false;
            if (this.faltante !== 0) return false;
            return this.lineas.every(
                (l) => l.medio_de_pago_id
                    && Number(l.monto) > 0
                    && (!this.esSena(l) || l.sena_id)
            );
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
                sena_id: null,
            });
        },

        quitarLinea(indice) {
            this.lineas.splice(indice, 1);
            // Lo que quedó suelto vuelve a la primera línea: dejarlo sin
            // asignar obligaría a corregir un monto que la vendedora no tocó.
            this.repartir(0);
        },

        alCambiarMedio(indice) {
            const linea = this.lineas[indice];
            linea.plan_cuotas_id = null;
            linea.sena_id = null;

            // Una seña no puede cubrir más de su saldo: se acota sola y el
            // resto queda para el otro medio.
            if (this.esSena(linea) && this.senas.length === 1) {
                linea.sena_id = this.senas[0].id;
                linea.monto = Math.min(Number(linea.monto), Number(this.senas[0].saldo));
                this.repartir(indice);
            }
        },

        alCambiarMonto(indice) {
            this.repartir(indice);
        },

        /* Ajusta la OTRA línea para que las dos sumen el total. Con una sola
           línea, esa línea cubre todo.

           Es la ayuda de la que habla el flujo: la vendedora carga el
           primero y el sistema calcula el segundo. */
        repartir(indiceFijo) {
            const total = Number(this.venta?.a_cobrar || 0);

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
                // las señas ANTES de tocar el stock. Si algo está mal, la
                // venta sigue abierta y corregible.
                await pedir(`${API_VENTAS}/${this.venta.id}/pagos`, {
                    method: 'POST',
                    body: JSON.stringify({
                        pagos: this.lineas.map((l) => ({
                            medio_de_pago_id: l.medio_de_pago_id,
                            monto: l.monto,
                            plan_cuotas_id: l.plan_cuotas_id || null,
                            sena_id: l.sena_id || null,
                        })),
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

function consultaStockMobile() {
    return {
        filas: [],
        total: 0,
        pagina: 1,
        tamano: 20,
        cargando: false,
        todosLosLocales: false,
        filtros: { busqueda: '' },

        pesos: (v) => window.pesos(v),

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

                // Un vendedor ya viene acotado a su local por el dispositivo:
                // el parámetro solo importa para los roles que ven todo.
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
    };
}
