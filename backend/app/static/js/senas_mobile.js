/* ==========================================================================
   Señas — alta desde el celular del local.

   Acá no se decide nada: si el cliente ya tiene una seña vigente, si hay
   turno abierto o si el medio sirve, lo valida el backend y su mensaje se
   muestra tal cual. La pantalla solo avisa antes lo que ya sabe (la seña
   vigente del cliente elegido) para no hacer cargar un monto de gusto.
   ========================================================================== */

const API_SENAS = '/api/v1/senas';

function senaNueva() {
    const nuevoVacio = () => ({ nombre: '', dni: '', telefono: '' });

    return {
        ...window.buscadorClientes(),

        medios: [],
        cliente: null,
        senaVigente: null,
        creandoCliente: false,
        nuevo: nuevoVacio(),
        monto: '',
        medioId: null,
        descripcion: '',
        enviando: false,
        hecha: null,

        pesos: (v) => window.pesos(v),

        async cargar() {
            try {
                this.medios = await window.pedir(`${API_SENAS}/medios-de-pago`);
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        async elegirCliente(c) {
            this.cliente = c;
            this.limpiarBusquedaCliente();
            try {
                const vigentes = await window.pedir(`/api/v1/clientes/${c.id}/senas`);
                this.senaVigente = vigentes[0] || null;
            } catch (e) {
                this.senaVigente = null;
            }
        },

        quitarCliente() {
            this.cliente = null;
            this.senaVigente = null;
        },

        nuevoCliente() {
            this.creandoCliente = true;
            // Lo que se escribió en el buscador suele ser el DNI o el nombre:
            // se aprovecha para no tipearlo dos veces.
            const texto = this.clienteBusqueda.trim();
            this.nuevo = nuevoVacio();
            if (/^\d+$/.test(texto)) this.nuevo.dni = texto;
            else this.nuevo.nombre = texto;
            this.limpiarBusquedaCliente();
        },

        get tieneCliente() {
            return this.creandoCliente ? this.nuevo.nombre.trim().length > 0 : !!this.cliente;
        },

        get puedeRegistrar() {
            return this.tieneCliente
                && !(!this.creandoCliente && this.senaVigente)
                && Number(this.monto) > 0
                && !!this.medioId;
        },

        async registrar() {
            if (!this.puedeRegistrar) return;
            this.enviando = true;
            try {
                const cuerpo = {
                    medio_de_pago_id: this.medioId,
                    monto: this.monto,
                    descripcion: this.descripcion.trim() || null,
                };
                if (this.creandoCliente) {
                    cuerpo.cliente_nuevo = {
                        nombre: this.nuevo.nombre.trim(),
                        dni: this.nuevo.dni.trim() || null,
                        telefono: this.nuevo.telefono.trim() || null,
                    };
                } else {
                    cuerpo.cliente_id = this.cliente.id;
                }
                this.hecha = await window.pedir(API_SENAS, {
                    method: 'POST',
                    body: JSON.stringify(cuerpo),
                });
                window.toast('Seña registrada', 'exito');
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.enviando = false;
            }
        },

        reiniciar() {
            this.hecha = null;
            this.quitarCliente();
            this.creandoCliente = false;
            this.nuevo = nuevoVacio();
            this.monto = '';
            this.medioId = null;
            this.descripcion = '';
        },
    };
}
