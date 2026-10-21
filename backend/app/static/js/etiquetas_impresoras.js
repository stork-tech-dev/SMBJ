/* ==========================================================================
   Ajustes → Impresoras: fichas de las Zebra y qué rollo imprime cada una.

   Basada en la pantalla del prototipo del cliente. Las fichas y la
   asignación viven en el backend (/api/v1/etiquetas); Browser Print se
   consulta solo para mostrar qué impresoras ve ESTA PC y para mandar la
   etiqueta de prueba y la calibración (`browserprint.js`).
   ========================================================================== */

const API_ETIQUETAS = '/api/v1/etiquetas';

function impresorasEtiquetas() {
    return {
        impresoras: [],
        formatos: [],
        asignacion: {},          // formato_id → impresora_id (0 = ninguna)
        asignacionGuardada: {},
        visibles: [],            // nombres que ve Browser Print en esta PC
        bpOk: false,
        bpTexto: 'Buscando Browser Print…',
        aMano: { ver: false, nombre: '', bp: '' },
        confirmacion: { abierta: false, titulo: '', mensaje: '', accion: () => {} },

        async iniciar() {
            try {
                const [impresoras, formatos] = await Promise.all([
                    window.pedir(API_ETIQUETAS + '/impresoras'),
                    window.pedir(API_ETIQUETAS + '/formatos'),
                ]);
                this.impresoras = impresoras.map((i) => this.ficha(i));
                this.formatos = formatos;
                this.asignacion = Object.fromEntries(formatos.map((f) => [f.id, f.impresora_id || 0]));
                this.asignacionGuardada = { ...this.asignacion };
            } catch (e) {
                window.toast(e.message, 'error');
            }
            this.buscarBrowserPrint();
        },

        /* La API manda los decimales como texto: se pasan a número para los inputs. */
        ficha(i) {
            return {
                ...i,
                corrimiento_x_mm: Number(i.corrimiento_x_mm),
                corrimiento_y_mm: Number(i.corrimiento_y_mm),
                _previa: '',
                _ocupada: false,
            };
        },

        async buscarBrowserPrint() {
            try {
                this.visibles = (await window.BrowserPrint.impresoras()).map((d) => d.name);
                this.bpOk = true;
                this.bpTexto = 'Browser Print responde en esta PC y ve '
                    + this.visibles.length + (this.visibles.length === 1 ? ' impresora.' : ' impresoras.');
            } catch (e) {
                this.visibles = [];
                this.bpOk = false;
                this.bpTexto = e.message;
            }
        },

        /** Impresoras que ve Browser Print y no están en ninguna ficha. */
        sinFicha() {
            return this.visibles.filter((n) => !this.impresoras.some((f) => f.browser_print === n));
        },

        /** "\\PCDEPOSITO\ZDesigner ZD421" → "Zebra de PCDEPOSITO". */
        nombreSugerido(n) {
            const pc = (n.match(/^\\\\([^\\]+)\\/) || [])[1];
            return pc ? 'Zebra de ' + pc : n.slice(0, 60);
        },

        opcionesBrowserPrint(f) {
            return [...new Set([f.browser_print, ...this.visibles])];
        },

        imprime(id) {
            return this.formatos.filter((f) => this.asignacionGuardada[f.id] === id).map((f) => f.nombre).join(' y ');
        },

        asignacionCambio() {
            return this.formatos.some((f) => this.asignacion[f.id] !== this.asignacionGuardada[f.id]);
        },

        /** Una impresora tiene un solo rollo a la vez: asignarle dos obliga a cambiar el rollo. */
        repetidas() {
            const usos = {};
            for (const f of this.formatos) {
                const id = this.asignacion[f.id];
                if (id) (usos[id] = usos[id] || []).push(f.nombre);
            }
            const dobles = Object.values(usos).find((l) => l.length > 1);
            return dobles
                ? 'Una misma impresora tiene asignados ' + dobles.join(' y ')
                  + ': tiene un solo rollo a la vez, así que al cambiar de tipo hay que cambiar el rollo.'
                : '';
        },

        async agregar(browserPrint, nombre) {
            browserPrint = (browserPrint || '').trim();
            nombre = (nombre || '').trim() || this.nombreSugerido(browserPrint);
            if (!browserPrint) {
                window.toast('Falta el nombre en Browser Print.', 'error');
                return;
            }
            try {
                const nueva = await window.pedir(API_ETIQUETAS + '/impresoras', {
                    method: 'POST',
                    body: JSON.stringify({ nombre, browser_print: browserPrint }),
                });
                this.impresoras.push(this.ficha(nueva));
                this.aMano = { ver: false, nombre: '', bp: '' };
                window.toast('Se agregó "' + nombre + '". Asignale qué tipo de etiqueta imprime.', 'exito');
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        async guardarAsignacion() {
            try {
                for (const f of this.formatos) {
                    if (this.asignacion[f.id] === this.asignacionGuardada[f.id]) continue;
                    await window.pedir(API_ETIQUETAS + '/formatos/' + f.id + '/impresora', {
                        method: 'PUT',
                        body: JSON.stringify({ impresora_id: this.asignacion[f.id] || null }),
                    });
                    this.asignacionGuardada[f.id] = this.asignacion[f.id];
                }
                window.toast('Asignación guardada.', 'exito');
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        async guardarFicha(f) {
            try {
                const guardada = await window.pedir(API_ETIQUETAS + '/impresoras/' + f.id, {
                    method: 'PUT',
                    body: JSON.stringify({
                        nombre: f.nombre,
                        browser_print: f.browser_print,
                        corrimiento_x_mm: f.corrimiento_x_mm,
                        corrimiento_y_mm: f.corrimiento_y_mm,
                        oscuridad: f.oscuridad,
                        velocidad: f.velocidad,
                    }),
                });
                Object.assign(f, this.ficha(guardada), { _previa: f._previa });
                window.toast('Ficha guardada.', 'exito');
                return true;
            } catch (e) {
                window.toast(e.message, 'error');
                return false;
            }
        },

        /** Guarda la ficha (la prueba sale con estos ajustes) y manda una fila de prueba. */
        async prueba(f) {
            if (!(await this.guardarFicha(f))) return;
            f._ocupada = true;
            try {
                const r = await window.pedir(API_ETIQUETAS + '/impresoras/' + f.id + '/prueba', { method: 'POST' });
                f._previa = r.vista_previa;
                await window.BrowserPrint.imprimir(f, [r.zpl]);
                window.toast('Se mandó la etiqueta de prueba a "' + f.nombre + '".', 'exito');
            } catch (e) {
                window.toast('No se pudo mandar: ' + e.message, 'error');
            } finally {
                f._ocupada = false;
            }
        },

        calibrar(f) {
            this.confirmar(
                'Calibrar el rollo',
                'La Zebra "' + f.nombre + '" va a avanzar algunas etiquetas en blanco para medir el rollo.',
                async () => {
                    f._ocupada = true;
                    try {
                        const r = await window.pedir(API_ETIQUETAS + '/impresoras/' + f.id + '/calibrar', { method: 'POST' });
                        await window.BrowserPrint.imprimir(f, [r.zpl]);
                        window.toast('Se mandó la orden de calibrar.', 'exito');
                    } catch (e) {
                        window.toast('No se pudo mandar: ' + e.message, 'error');
                    } finally {
                        f._ocupada = false;
                    }
                },
            );
        },

        pedirQuitar(f) {
            this.confirmar('Quitar impresora', '¿Quitar "' + f.nombre + '"? Se borra su ficha.', async () => {
                try {
                    await window.pedir(API_ETIQUETAS + '/impresoras/' + f.id, { method: 'DELETE' });
                    this.impresoras = this.impresoras.filter((i) => i.id !== f.id);
                    window.toast('Impresora quitada.', 'exito');
                } catch (e) {
                    window.toast(e.message, 'error');
                }
            });
        },

        confirmar(titulo, mensaje, accion) {
            this.confirmacion = {
                abierta: true,
                titulo,
                mensaje,
                accion: async () => {
                    this.confirmacion.abierta = false;
                    await accion();
                },
            };
        },
    };
}
