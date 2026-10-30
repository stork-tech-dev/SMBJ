/* ==========================================================================
   Imprimir etiquetas (pantalla `/etiquetas`).

   Portada del prototipo del cliente. La pantalla junta los renglones (de un
   producto, de una compra o escaneados), le pide al servidor que arme todo
   (`POST /api/v1/etiquetas/preparar`: ZPL, avisos y vista previa, repartido
   por rollo) y le pasa cada orden ZPL a Browser Print (`browserprint.js`).

   Nada se da por impreso si Browser Print no lo aceptó.
   ========================================================================== */

const API_ETIQUETAS = '/api/v1/etiquetas';

function etiquetasImprimir(esMaestra) {
    return {
        esMaestra,
        formatos: [],
        disenos: [],
        disenoId: null,
        formatoId: null,         // tipo de etiqueta para TODO (el primero, la múltiple)
        distinto: false,         // tilde "algunos productos llevan otra etiqueta"
        renglones: [],
        _id: 0,
        buscar: '',
        resultados: [],          // variantes que coinciden con lo tipeado
        sinResultados: false,
        verCompra: false,
        numeroCompra: '',
        resultado: null,
        estados: {},             // formato_id → ¿Browser Print ve su impresora?
        bpResponde: null,
        imprimiendo: false,
        mensajes: [],
        verZpl: false,
        abiertoTipo: false,      // bloques 2 y 3: colapsados de entrada
        abiertoImpresora: false,
        _espera: null,
        confirmacion: { abierta: false, titulo: '', mensaje: '', accion: () => {} },

        async iniciar() {
            try {
                [this.formatos, this.disenos] = await Promise.all([
                    window.pedir(API_ETIQUETAS + '/formatos'),
                    window.pedir(API_ETIQUETAS + '/disenos'),
                ]);
            } catch (e) {
                window.toast(e.message, 'error');
                return;
            }
            this.formatoId = this.formatos[0]?.id ?? null;
            this.disenoId = this.disenos[0]?.id ?? null;

            // Se llega desde un producto o desde una compra.
            const q = new URLSearchParams(window.location.search);
            if (q.get('variante_id')) {
                try {
                    await this.cargarOrigen({ variante_id: q.get('variante_id'), copias: q.get('copias') || 1 });
                } catch (e) {
                    window.toast(e.message, 'error');
                }
            }
            if (q.get('compra_id')) await this.cargarCompra(q.get('compra_id'));

            this.$watch('renglones', () => this.preparar());
            this.$watch('disenoId', () => this.preparar());
            this.preparar();
            this.$nextTick(() => this.$refs.buscador.focus());
        },

        cantidad(n, uno, varios) {
            n = n || 0;
            return n + ' ' + (n === 1 ? uno : varios);
        },

        /* 1 = solo código, 2 = código + texto, 3 = solo texto. */
        opcion(r) {
            if (!r.variante_id) return 3;
            return r.conTexto && (r.texto || '').trim() ? 2 : 1;
        },

        nuevoRenglon(p) {
            return {
                id: ++this._id,
                variante_id: p.variante_id,
                codigo: p.codigo,
                producto: p.descripcion,
                variante: p.variante || '',
                copias: p.copias,
                formato_id: this.formatoId,
                conTexto: false,
                texto: '',
                incluir: true,
            };
        },

        /* Suma los renglones; si el producto ya está, le suma las copias. */
        sumar(renglones) {
            for (const p of renglones) {
                const ya = this.renglones.find((r) => r.variante_id === p.variante_id);
                if (ya) ya.copias += p.copias;
                else this.renglones.push(this.nuevoRenglon(p));
            }
        },

        async cargarOrigen(params) {
            const datos = await window.pedir(API_ETIQUETAS + '/origen?' + new URLSearchParams(params));
            this.sumar(datos.renglones);
            return datos.renglones;
        },

        /* Las variantes que coinciden con lo tipeado (código, SKU o descripción), con su foto. */
        async buscarProductos() {
            const texto = this.buscar.trim();
            this.sinResultados = false;
            if (texto.length < 2) {
                this.resultados = [];
                return;
            }
            try {
                const params = new URLSearchParams({ busqueda: texto, tamano: '10' });
                const datos = await window.pedir('/api/v1/productos/variantes?' + params);
                // Si mientras tanto se eligió o se borró, la respuesta ya no corresponde.
                if (this.buscar.trim() !== texto) return;
                this.resultados = datos.resultados;
                this.sinResultados = !this.resultados.length;
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        limpiarBuscador() {
            this.buscar = '';
            this.resultados = [];
            this.sinResultados = false;
            this.$refs.buscador.focus();
        },

        /* Elegida de la lista: se agrega con una copia (o suma una si ya estaba). */
        elegir(v) {
            this.sumar([{
                variante_id: v.id,
                codigo: v.codigo_completo + v.verificador,
                descripcion: v.producto.descripcion,
                variante: v.es_base ? null : (v.descripcion_sufijo || v.sufijo),
                copias: 1,
            }]);
            this.limpiarBuscador();
        },

        /* Enter (lo que manda el lector después del código): si la lista
           tiene una sola opción, esa; si no, el código exacto. */
        async agregar() {
            if (this.resultados.length === 1) {
                this.elegir(this.resultados[0]);
                return;
            }
            const codigo = this.buscar.trim().toUpperCase();
            if (!codigo) return;
            try {
                const [p] = await this.cargarOrigen({ codigo });
                // Mostrar el nombre: quien tipeó ve si es el que buscaba.
                window.toast(p.codigo + ': ' + p.descripcion, 'info', 2500);
                this.limpiarBuscador();
            } catch (e) {
                // Sin código exacto queda lo tipeado y la lista, para elegir de ahí.
                if (!this.resultados.length) window.toast(e.message, 'error');
            }
        },

        async cargarCompra(numero) {
            numero = String(numero || '').trim();
            if (!numero) return;
            try {
                const renglones = await this.cargarOrigen({ compra_id: numero });
                this.verCompra = false;
                this.numeroCompra = '';
                window.toast('Compra ' + numero + ': ' + this.cantidad(renglones.length, 'producto', 'productos')
                             + ' con su cantidad como copias.', 'exito');
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        agregarTexto() {
            this.renglones.push({
                id: ++this._id, variante_id: null, codigo: null, producto: '(solo texto)', variante: '',
                copias: 1, formato_id: this.formatoId, conTexto: true, texto: 'LIQUIDACION 50%', incluir: true,
            });
        },

        /* Cambiar el tipo general: los renglones que lo tenían lo siguen; los cambiados a mano no. */
        cambiarFormato(id) {
            for (const r of this.renglones) if (r.formato_id === this.formatoId) r.formato_id = id;
            this.formatoId = id;
            this.preparar();
        },

        /* Al tildar o destildar, todos arrancan con el tipo general. */
        cambiarDistinto() {
            for (const r of this.renglones) r.formato_id = this.formatoId;
            this.preparar();
        },

        preparar() {
            clearTimeout(this._espera);
            this._espera = setTimeout(async () => {
                if (!this.disenoId) return;
                const etiquetas = this.renglones.filter((r) => r.incluir).map((r) => ({
                    variante_id: r.variante_id,
                    texto: this.opcion(r) === 1 ? null : r.texto,
                    copias: Number(r.copias) || 0,
                    formato_id: this.distinto ? r.formato_id : this.formatoId,
                }));
                try {
                    this.resultado = await window.pedir(API_ETIQUETAS + '/preparar', {
                        method: 'POST',
                        body: JSON.stringify({ diseno_id: this.disenoId, etiquetas }),
                    });
                } catch (e) {
                    window.toast(e.message, 'error');
                    return;
                }
                this.revisarImpresoras();
            }, 250);
        },

        async revisarImpresoras() {
            try {
                const vistas = (await window.BrowserPrint.impresoras()).map((d) => d.name);
                this.bpResponde = true;
                const estados = {};
                for (const g of this.resultado.grupos) {
                    if (g.impresora) estados[g.formato_id] = vistas.includes(g.impresora.browser_print);
                }
                this.estados = estados;
            } catch (e) {
                this.bpResponde = false;
                this.estados = {};
            }
        },

        todasListas() {
            return (this.resultado?.grupos || []).every((g) => this.estados[g.formato_id]);
        },

        avisos() {
            const r = this.resultado;
            if (!r) return [];
            const salida = [...r.avisos];
            for (const g of r.grupos) {
                for (const a of g.avisos) salida.push({ nivel: a.nivel, texto: g.formato_nombre + ': ' + a.texto });
            }
            if (this.bpResponde === false) {
                salida.push({ nivel: 'error', texto: 'Browser Print no responde en esta PC: ¿está instalado y abierto (el iconito de Zebra al lado del reloj)?' });
            } else {
                for (const g of r.grupos) {
                    if (g.impresora && this.estados[g.formato_id] === false) {
                        salida.push({ nivel: 'error', texto: 'Browser Print no ve "' + g.impresora.nombre + '": ¿está prendida esa PC? ¿Está tildado "Driver Search"?' });
                    }
                }
            }
            if (r.grupos.length && !salida.length) {
                salida.push({ nivel: 'bien', texto: 'Todo entra en la etiqueta y las impresoras están listas.' });
            }
            return salida;
        },

        textoZpl() {
            const partes = [];
            for (const g of this.resultado?.grupos || []) {
                partes.push('^FX ===== ' + g.formato_nombre + ' -> ' + (g.impresora?.nombre || 'SIN IMPRESORA')
                            + ' (' + this.cantidad(g.trabajos.length, 'orden', 'órdenes') + ') =====');
                partes.push(...g.trabajos.slice(0, 3));
                if (g.trabajos.length > 3) partes.push('… (' + (g.trabajos.length - 3) + ' órdenes más)');
            }
            return partes.join('\n');
        },

        async imprimirTodo() {
            this.imprimiendo = true;
            this.mensajes = [];
            for (const g of this.resultado.grupos) {
                try {
                    await window.BrowserPrint.imprimir(g.impresora, g.trabajos);
                    this.mensajes.push({ ok: true, texto: '✔ ' + g.formato_nombre + ': se mandaron '
                        + this.cantidad(g.total_etiquetas, 'etiqueta', 'etiquetas') + ' a "' + g.impresora.nombre + '".' });
                } catch (e) {
                    this.mensajes.push({ ok: false, texto: '✖ ' + g.formato_nombre + ': no se pudo mandar ('
                        + e.message + '). No se dieron por impresas: revisá y volvé a mandarlas.' });
                }
            }
            this.imprimiendo = false;
            this.revisarImpresoras();
        },

        async prueba(g) {
            this.mensajes = [];
            try {
                const r = await window.pedir(API_ETIQUETAS + '/impresoras/' + g.impresora.id + '/prueba', { method: 'POST' });
                await window.BrowserPrint.imprimir(g.impresora, [r.zpl]);
                window.toast('Se mandó la etiqueta de prueba a "' + g.impresora.nombre + '".', 'exito');
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        calibrar(g) {
            this.confirmacion = {
                abierta: true,
                titulo: 'Calibrar el rollo',
                mensaje: 'La Zebra "' + g.impresora.nombre + '" va a avanzar algunas etiquetas en blanco para medir el rollo.',
                accion: async () => {
                    this.confirmacion.abierta = false;
                    try {
                        const r = await window.pedir(API_ETIQUETAS + '/impresoras/' + g.impresora.id + '/calibrar', { method: 'POST' });
                        await window.BrowserPrint.imprimir(g.impresora, [r.zpl]);
                        window.toast('Se mandó la orden de calibrar.', 'exito');
                    } catch (e) {
                        window.toast(e.message, 'error');
                    }
                },
            };
        },
    };
}
