/* ==========================================================================
   Diseños de etiqueta (pantalla `/etiquetas/disenos`, Cuenta Maestra).

   Editar un diseño muestra en vivo cómo salen las tres opciones en cada
   rollo: la vista previa la arma el servidor con los parámetros SIN guardar
   (`POST /disenos/vista-previa`), con el mismo motor que imprime. Guardar
   crea una versión nueva; "Volver a esta" restaura una vieja.
   ========================================================================== */

const API_DISENOS = '/api/v1/etiquetas/disenos';

function disenosEtiqueta() {
    return {
        disenos: [],
        archivados: false,
        edicion: null,       // copia editable del diseño elegido
        original: '',        // el elegido tal como está guardado (JSON), para saber si cambió
        versiones: [],
        previa: [],
        errorPrevia: '',
        verZpl: false,
        guardando: false,
        _espera: null,
        confirmacion: { abierta: false, titulo: '', mensaje: '', accion: () => {} },

        async iniciar() {
            await this.cargar();
            if (this.disenos.length) await this.elegir(this.disenos[0]);
            // Sobre `edicion` entera y no `edicion.parametros`: al archivar
            // queda en null y la expresión anidada fallaría.
            this.$watch('edicion', () => this.vistaPrevia());
        },

        async cargar() {
            try {
                this.disenos = await window.pedir(API_DISENOS + '?archivados=' + this.archivados);
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        async verArchivados(si) {
            this.archivados = si;
            await this.cargar();
        },

        async elegir(d) {
            this.edicion = JSON.parse(JSON.stringify(d));
            this.original = JSON.stringify({ nombre: d.nombre, parametros: d.parametros });
            this.vistaPrevia();
            try {
                this.versiones = await window.pedir(API_DISENOS + '/' + d.id + '/versiones');
            } catch (e) {
                this.versiones = [];
            }
        },

        hayCambios() {
            if (!this.edicion) return false;
            return JSON.stringify({ nombre: this.edicion.nombre, parametros: this.edicion.parametros }) !== this.original;
        },

        descartar() {
            const guardado = JSON.parse(this.original);
            this.edicion.nombre = guardado.nombre;
            this.edicion.parametros = guardado.parametros;
        },

        vistaPrevia() {
            clearTimeout(this._espera);
            this._espera = setTimeout(async () => {
                if (!this.edicion) return;
                try {
                    const r = await window.pedir(API_DISENOS + '/vista-previa', {
                        method: 'POST',
                        body: JSON.stringify({ parametros: this.edicion.parametros }),
                    });
                    this.previa = r.rollos;
                    this.errorPrevia = '';
                } catch (e) {
                    // Un valor fuera de rango mientras se tipea: se avisa y
                    // se deja la última vista previa buena.
                    this.errorPrevia = e.message;
                }
            }, 300);
        },

        /* Reemplaza el diseño en la lista y lo vuelve a elegir (queda como guardado). */
        async tomar(d) {
            await this.cargar();
            await this.elegir(d);
        },

        async guardar() {
            this.guardando = true;
            try {
                const d = await window.pedir(API_DISENOS + '/' + this.edicion.id, {
                    method: 'PUT',
                    body: JSON.stringify({ nombre: this.edicion.nombre, parametros: this.edicion.parametros }),
                });
                await this.tomar(d);
                window.toast('Diseño guardado (versión ' + d.version + ').', 'exito');
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.guardando = false;
            }
        },

        async duplicar() {
            try {
                const d = await window.pedir(API_DISENOS + '/' + this.edicion.id + '/duplicar', { method: 'POST' });
                this.archivados = false;
                await this.tomar(d);
                window.toast('Se creó "' + d.nombre + '".', 'exito');
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        pedirArchivar() {
            const archivar = !this.edicion.archivado;
            this.confirmar(
                archivar ? 'Archivar diseño' : 'Desarchivar diseño',
                archivar
                    ? 'Deja de ofrecerse al imprimir. No se pierde: se puede desarchivar.'
                    : 'Vuelve a ofrecerse al imprimir.',
                async () => {
                    try {
                        await window.pedir(API_DISENOS + '/' + this.edicion.id + (archivar ? '/archivar' : '/desarchivar'), { method: 'POST' });
                        this.edicion = null;
                        await this.cargar();
                        window.toast(archivar ? 'Diseño archivado.' : 'Diseño desarchivado.', 'exito');
                    } catch (e) {
                        window.toast(e.message, 'error');
                    }
                },
            );
        },

        pedirRestaurar(v) {
            this.confirmar(
                'Volver a la versión ' + v.version,
                'Se guarda como una versión nueva con esos valores: no se pierde ninguna versión.',
                async () => {
                    try {
                        const d = await window.pedir(API_DISENOS + '/' + this.edicion.id + '/versiones/' + v.version + '/restaurar', { method: 'POST' });
                        await this.tomar(d);
                        window.toast('Se volvió a la versión ' + v.version + '.', 'exito');
                    } catch (e) {
                        window.toast(e.message, 'error');
                    }
                },
            );
        },

        /* Subir un archivo: va como multipart, así que no pasa por `window.pedir` (que manda JSON). */
        async subir(archivo) {
            if (!archivo) return;
            const cuerpo = new FormData();
            cuerpo.append('archivo', archivo);
            try {
                const resp = await fetch(API_DISENOS + '/importar', { method: 'POST', body: cuerpo, credentials: 'same-origin' });
                const datos = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(datos.detail || 'No se pudo subir el archivo');
                this.archivados = false;
                await this.tomar(datos);
                window.toast('Se subió "' + datos.nombre + '".', 'exito');
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        fecha(iso) {
            return new Date(iso).toLocaleString('es-AR', {
                day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
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
