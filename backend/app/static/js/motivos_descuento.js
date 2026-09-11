/* ==========================================================================
   Catálogo de motivos de descuento.

   La lista de porcentajes NO está escrita acá: se pide a
   /api/v1/ventas/opciones-descuento, que la sirve desde la misma constante
   que valida el backend. Una lista copiada en el JavaScript terminaría
   ofreciendo un valor que la API rechaza, y el error aparecería recién al
   guardar.

   Un motivo no se borra: se desactiva, porque los ítems con descuento lo
   apuntan y borrarlo dejaría descuentos sin explicación.
   ========================================================================== */

const URL_MOTIVOS_DESC  = '/api/v1/configuracion/motivos-descuento';
const URL_OPCIONES_DESC = '/api/v1/ventas/opciones-descuento';
const URL_CAT_MOTIVOS   = '/api/v1/configuracion/motivos-descuento/catalogos';

function abmMotivosDescuento() {
    return {
        motivos: [],
        porcentajes: [],
        catalogos: { puntos_de_venta: [], medios_de_pago: [] },
        cargando: false,
        filtros: { nombre: '', habilita_cuotas_sin_interes: '', activo: 'true' },

        form: {
            abierto: false, guardando: false, id: null,
            nombre: '', nota: '', porcentaje_sugerido: '',
            habilita_cuotas_sin_interes: false,
            fecha_inicio: '', fecha_fin: '',
            sucursales: [],   // array de {id, nombre}
            medios_pago: [],  // array de {id, nombre}
        },

        porcentaje(valor) {
            if (valor === null || valor === undefined) return '—';
            return `${Number(valor).toLocaleString('es-AR', {
                minimumFractionDigits: 0,
                maximumFractionDigits: 2,
            })}%`;
        },

        async cargar() {
            this.cargando = true;
            try {
                const params = new URLSearchParams();
                for (const [k, v] of Object.entries(this.filtros)) {
                    if (v !== '') params.set(k, v);
                }

                const pedidos = [fetch(`${URL_MOTIVOS_DESC}?${params}`, { credentials: 'same-origin' })];
                if (!this.porcentajes.length) {
                    pedidos.push(fetch(URL_OPCIONES_DESC, { credentials: 'same-origin' }));
                }
                if (!this.catalogos.puntos_de_venta.length) {
                    pedidos.push(fetch(URL_CAT_MOTIVOS, { credentials: 'same-origin' }));
                }

                const [resp, opciones, cats] = await Promise.all(pedidos);
                if (!resp.ok) throw new Error('No se pudo cargar el catálogo');
                this.motivos = await resp.json();

                if (opciones?.ok) {
                    this.porcentajes = (await opciones.json()).porcentajes;
                }
                if (cats?.ok) {
                    this.catalogos = await cats.json();
                }
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        limpiar() {
            this.filtros = { nombre: '', habilita_cuotas_sin_interes: '', activo: 'true' };
            this.cargar();
        },

        _formVacio() {
            return {
                abierto: true, guardando: false, id: null,
                nombre: '', nota: '', porcentaje_sugerido: '',
                habilita_cuotas_sin_interes: false,
                fecha_inicio: '', fecha_fin: '',
                sucursales: [], medios_pago: [],
            };
        },

        abrirAlta() {
            this.form = this._formVacio();
        },

        abrirEdicion(m) {
            this.form = {
                abierto: true, guardando: false, id: m.id,
                nombre: m.nombre,
                nota: m.nota || '',
                porcentaje_sugerido:
                    m.porcentaje_sugerido === null ? '' : String(Number(m.porcentaje_sugerido)),
                habilita_cuotas_sin_interes: m.habilita_cuotas_sin_interes,
                fecha_inicio: m.fecha_inicio || '',
                fecha_fin:    m.fecha_fin    || '',
                // Reconstruir sucursales y medios desde las restricciones
                sucursales: m.restricciones
                    .filter(r => r.tipo === 'punto_de_venta')
                    .map(r => {
                        const pdv = this.catalogos.puntos_de_venta.find(p => p.id === r.referencia_id);
                        return pdv ? { id: pdv.id, nombre: pdv.nombre } : null;
                    })
                    .filter(Boolean),
                medios_pago: m.restricciones
                    .filter(r => r.tipo === 'medio_de_pago')
                    .map(r => {
                        const med = this.catalogos.medios_de_pago.find(p => p.id === r.referencia_id);
                        return med ? { id: med.id, nombre: med.nombre } : null;
                    })
                    .filter(Boolean),
            };
        },

        toggleSucursal(pdv) {
            const idx = this.form.sucursales.findIndex(s => s.id === pdv.id);
            if (idx >= 0) {
                this.form.sucursales.splice(idx, 1);
            } else {
                this.form.sucursales.push({ id: pdv.id, nombre: pdv.nombre });
            }
        },

        sucursalSeleccionada(pdv) {
            return this.form.sucursales.some(s => s.id === pdv.id);
        },

        toggleMedio(medio) {
            const idx = this.form.medios_pago.findIndex(m => m.id === medio.id);
            if (idx >= 0) {
                this.form.medios_pago.splice(idx, 1);
            } else {
                this.form.medios_pago.push({ id: medio.id, nombre: medio.nombre });
            }
        },

        medioSeleccionado(medio) {
            return this.form.medios_pago.some(m => m.id === medio.id);
        },

        async guardar() {
            this.form.guardando = true;
            try {
                const alta = !this.form.id;

                // Construir restricciones desde sucursales + medios
                const restricciones = [];
                for (const s of this.form.sucursales) {
                    restricciones.push({ tipo: 'punto_de_venta', referencia_id: s.id });
                }
                for (const m of this.form.medios_pago) {
                    restricciones.push({ tipo: 'medio_de_pago', referencia_id: m.id });
                }

                const cuerpo = {
                    nombre: this.form.nombre,
                    nota: this.form.nota || null,
                    porcentaje_sugerido:
                        this.form.porcentaje_sugerido === ''
                            ? null
                            : Number(this.form.porcentaje_sugerido),
                    habilita_cuotas_sin_interes: this.form.habilita_cuotas_sin_interes,
                    fecha_inicio: this.form.fecha_inicio || null,
                    fecha_fin:    this.form.fecha_fin    || null,
                    restricciones,
                };

                const resp = await fetch(
                    alta ? URL_MOTIVOS_DESC : `${URL_MOTIVOS_DESC}/${this.form.id}`,
                    {
                        method: alta ? 'POST' : 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify(cuerpo),
                    }
                );
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo guardar');
                }

                this.form.abierto = false;
                window.toast(alta ? 'Motivo creado' : 'Motivo actualizado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.form.guardando = false;
            }
        },

        async cambiarEstado(m, activo) {
            try {
                const resp = await fetch(`${URL_MOTIVOS_DESC}/${m.id}/estado`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ activo }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'No se pudo cambiar el estado');
                }
                window.toast(activo ? 'Motivo activado' : 'Motivo desactivado', 'exito');
                this.cargar();
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },
    };
}
