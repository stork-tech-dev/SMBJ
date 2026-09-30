/* ==========================================================================
   Ajustes: parámetros globales del negocio (solo Cuenta Maestra).

   Guardar pide dos confirmaciones: `revision` muestra qué cambia (anterior
   → nuevo) y `confirmacionFinal` aplica. Se manda solo lo que cambió; las
   validaciones que cruzan campos (el paso no puede superar el tope) las
   hace el backend y su mensaje se muestra tal cual.
   ========================================================================== */

const API_AJUSTES = '/api/v1/ajustes';
const API_CATEGORIAS = '/api/v1/ajustes/categorias';

/* Categorías comparables: números, sin espacios de más y ordenadas por
   puntos (así el orden en que se cargaron no cuenta como cambio). */
function normalizarCategorias(lista) {
    return lista
        .map((c) => ({
            nombre: String(c.nombre || '').trim(),
            puntos_desde: Number(c.puntos_desde),
            porcentaje_cumpleanos: Number(c.porcentaje_cumpleanos),
        }))
        .sort((a, b) => a.puntos_desde - b.puntos_desde);
}

function textoCategorias(lista) {
    if (!lista.length) return 'sin categorías';
    return lista
        .map((c) => `${c.nombre} desde ${c.puntos_desde} pts (${c.porcentaje_cumpleanos}%)`)
        .join(', ');
}

// Orden y rótulos del resumen de cambios. `tipo` decide el formato.
const CAMPOS_AJUSTES = {
    redondeo: { nombre: 'Redondeo de precios', tipo: 'pesos' },
    descuento_maximo: { nombre: 'Descuento máximo por producto', tipo: 'pct' },
    tope_descuento_venta: { nombre: 'Tope total de descuento en la venta', tipo: 'pct' },
    paso_descuento: { nombre: 'Paso de los porcentajes de descuento', tipo: 'pct' },
    dias_vigencia_sena: { nombre: 'Vigencia de las señas', tipo: 'dias' },
    pesos_por_punto: { nombre: 'Pesos por punto', tipo: 'pesos' },
    dias_plazo_cambio: { nombre: 'Plazo habitual de cambio', tipo: 'dias' },
};

function ajustesSistema() {
    const modalVacio = () => ({ abierta: false, titulo: '', mensaje: '', accion: () => {} });

    return {
        cargando: true,
        // Sin datos no se muestra el formulario: guardar sobre valores
        // vacíos compararía contra nada y mandaría basura.
        cargado: false,
        guardando: false,
        originales: {},
        valores: {},
        // Categorías de fidelización: la tabla editable y lo que había.
        categoriasOriginales: [],
        categorias: [],
        revision: modalVacio(),
        confirmacionFinal: { ...modalVacio(), advertencia: '' },

        async cargar() {
            try {
                const [ajustes, categorias] = await Promise.all([
                    window.pedir(API_AJUSTES), window.pedir(API_CATEGORIAS),
                ]);
                this.tomar(ajustes);
                this.tomarCategorias(categorias);
                this.cargado = true;
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        /* La API manda los decimales como texto ("1000.00"): se pasan a
           número para compararlos con lo que se escribe en el input. */
        tomar(datos) {
            const numeros = {};
            for (const campo of Object.keys(CAMPOS_AJUSTES)) numeros[campo] = Number(datos[campo]);
            this.originales = numeros;
            this.valores = { ...numeros };
        },

        tomarCategorias(datos) {
            this.categoriasOriginales = normalizarCategorias(datos.categorias);
            this.categorias = this.categoriasOriginales.map((c) => ({ ...c }));
        },

        agregarCategoria() {
            const ultima = this.categorias[this.categorias.length - 1];
            this.categorias.push({
                nombre: '',
                puntos_desde: ultima ? ultima.puntos_desde + 100 : 0,
                porcentaje_cumpleanos: 0,
            });
        },

        quitarCategoria(indice) {
            this.categorias.splice(indice, 1);
        },

        get cambioCategorias() {
            return JSON.stringify(normalizarCategorias(this.categorias))
                !== JSON.stringify(this.categoriasOriginales);
        },

        cambio(campo) {
            return Number(this.valores[campo]) !== this.originales[campo];
        },

        get cambios() {
            return Object.keys(CAMPOS_AJUSTES).filter((c) => this.cambio(c));
        },

        get hayCambios() {
            return this.cambios.length > 0 || this.cambioCategorias;
        },

        /* Preview de la lista de la vendedora con lo que está en pantalla. */
        get listaPorcentajes() {
            const paso = Number(this.valores.paso_descuento);
            const tope = Number(this.valores.tope_descuento_venta);
            if (!(paso > 0) || !(tope > 0) || paso > tope) return 'ninguno (revisá el paso y el tope)';
            const lista = [];
            for (let p = paso; p <= tope; p += paso) lista.push(`${p}%`);
            return lista.join(', ');
        },

        formato(campo, valor) {
            const tipo = CAMPOS_AJUSTES[campo].tipo;
            if (tipo === 'pesos') return window.pesos(valor);
            if (tipo === 'pct') return `${valor}%`;
            return `${valor} días`;
        },

        descartar() {
            this.valores = { ...this.originales };
            this.categorias = this.categoriasOriginales.map((c) => ({ ...c }));
        },

        /* Confirmación 1: el resumen de lo que cambia. */
        revisar() {
            if (!this.hayCambios) return;
            const renglones = this.cambios.map((c) =>
                `• ${CAMPOS_AJUSTES[c].nombre}: ${this.formato(c, this.originales[c])} → ${this.formato(c, this.valores[c])}`
            );
            if (this.cambioCategorias) {
                renglones.push(
                    `• Categorías de fidelización: ${textoCategorias(this.categoriasOriginales)}`
                    + ` → ${textoCategorias(normalizarCategorias(this.categorias))}`
                );
            }
            this.revision = {
                abierta: true,
                titulo: 'Revisá los cambios',
                mensaje: renglones.join('\n'),
                accion: () => this.confirmarFinal(),
            };
        },

        /* Confirmación 2: aplicar. */
        confirmarFinal() {
            this.revision.abierta = false;
            const n = this.cambios.length + (this.cambioCategorias ? 1 : 0);
            this.confirmacionFinal = {
                abierta: true,
                titulo: 'Confirmación final',
                mensaje: `Se van a aplicar ${n} ${n === 1 ? 'cambio' : 'cambios'} a todo el sistema.`,
                advertencia: 'Rigen para todas las operaciones desde ahora. ¿Aplicarlos?',
                accion: () => this.guardar(),
            };
        },

        async guardar() {
            this.confirmacionFinal.abierta = false;
            const cuerpo = {};
            for (const c of this.cambios) cuerpo[c] = this.valores[c];

            this.guardando = true;
            try {
                if (this.cambios.length) {
                    this.tomar(await window.pedir(API_AJUSTES, {
                        method: 'PATCH',
                        body: JSON.stringify(cuerpo),
                    }));
                }
                if (this.cambioCategorias) {
                    this.tomarCategorias(await window.pedir(API_CATEGORIAS, {
                        method: 'PUT',
                        body: JSON.stringify({ categorias: normalizarCategorias(this.categorias) }),
                    }));
                }
                window.toast('Ajustes guardados', 'exito');
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.guardando = false;
            }
        },
    };
}
