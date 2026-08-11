/* ==========================================================================
   Soleil / Mallorca — JavaScript global

   Solo utilidades transversales. La interactividad de cada componente
   vive en su propio x-data de Alpine (ver /templates/components/).
   ========================================================================== */

/**
 * Estado del tema claro/oscuro. Se usa como x-data del <html> en base.html.
 * La preferencia persiste en localStorage y se aplica sin recargar.
 */
function temaApp() {
    return {
        dark: localStorage.getItem('theme') === 'dark',

        aplicar() {
            document.documentElement.classList.toggle('dark', this.dark);
        },

        alternar() {
            this.dark = !this.dark;
            localStorage.setItem('theme', this.dark ? 'dark' : 'light');
            this.aplicar();
        },
    };
}

/**
 * Dispara un toast desde cualquier lugar: window.toast('Guardado', 'exito').
 * Tipos: 'exito' | 'error' | 'info'.
 */
/**
 * Valor del dólar para mostrar: sin decimales cuando no los tiene.
 *
 * `Number.isInteger` y no `maximumFractionDigits: 0`: ese modificador
 * aplica su PROPIO redondeo half-expand, así que 1234,49 se mostraría
 * "1.234" y 1400,50 se mostraría "1.401" — números que nadie guardó. Acá lo
 * que se muestra tiene que ser exactamente lo que hay en la base.
 *
 * Vive en app.js porque la usan la pantalla de proveedores y la de cambio
 * masivo: estaba copiada en las dos y cualquier ajuste tenía que hacerse
 * dos veces para que no divergieran (Principio 2).
 */
window.formatearDolar = function (v) {
    if (v === null || v === undefined || v === '') return '—';
    const n = Number(v);
    const decimales = Number.isInteger(n) ? 0 : 2;
    return n.toLocaleString('es-AR', {
        minimumFractionDigits: decimales,
        maximumFractionDigits: decimales,
    });
};

window.toast = function (mensaje, tipo = 'info', duracion = 4000) {
    window.dispatchEvent(
        new CustomEvent('toast', { detail: { mensaje, tipo, duracion } })
    );
};

/**
 * Texto comparable: sin mayúsculas y sin acentos.
 *
 * Se descompone en NFD para separar la letra de su tilde y se borran los
 * diacríticos, así "Diseño" se encuentra escribiendo "diseno" y "Bijouterie"
 * escribiendo "bijou". Sin esto habría que acertar el acento para que el
 * buscador devuelva algo, que es exactamente lo que se quiere evitar.
 */
const normalizarTexto = (valor) =>
    String(valor ?? '')
        .normalize('NFD')
        .replace(/\p{Diacritic}/gu, '')
        .toLowerCase();

/**
 * Estado de un combobox: un campo de texto que filtra una lista mientras se
 * escribe. Lo usa el macro `components/combobox.html`.
 *
 * Existe porque un `<select>` nativo no se puede filtrar —tipear solo salta
 * por la primera letra— y las categorías se muestran con su camino completo
 * ("Joyas - Anillos - Plata"), así que todas las de una misma rama empiezan
 * igual y ni ese salto sirve.
 *
 * Config (todo son funciones para que se evalúen contra el scope de Alpine
 * que envuelve al componente, y sigan siendo reactivas):
 *   id        prefijo de los ids de cada fila, para `aria-activedescendant`.
 *   opciones  () => array de objetos con `id`.
 *   texto     (o) => etiqueta visible de una opción.
 *   valor     () => id seleccionado.
 *   elegir    (id) => guarda el elegido y dispara lo que corresponda.
 *   vacio     etiqueta de una primera opción que limpia la selección, o null.
 */
window.comboboxBuscable = function ({ id, opciones, texto, valor, elegir, vacio = null }) {
    return {
        abierto: false,
        consulta: '',
        resaltado: 0,
        // Al abrir se muestra la lista ENTERA aunque el campo tenga escrito
        // el camino de la opción ya elegida: filtrar por él dejaría una sola
        // fila y no se podría ver el resto sin borrar a mano.
        filtrando: false,

        /** La opción vacía va primera y se filtra como cualquier otra. */
        todas() {
            const lista = opciones() || [];
            return vacio === null ? lista : [{ id: '', etiquetaVacio: vacio }, ...lista];
        },

        etiquetaDe(opcion) {
            if (!opcion) return '';
            return opcion.etiquetaVacio !== undefined ? opcion.etiquetaVacio : texto(opcion);
        },

        /** Se compara como texto: el filtro guarda strings y el form, números. */
        opcionElegida() {
            const actual = valor();
            if (actual === '' || actual === null || actual === undefined) return null;
            return this.todas().find((o) => String(o.id) === String(actual)) || null;
        },

        /**
         * Todos los términos tipeados tienen que aparecer, en cualquier orden:
         * "plata anillo" encuentra "Joyas - Anillos - Plata". Buscar la frase
         * completa obligaría a escribir la ruta en el orden exacto del árbol.
         */
        filtradas() {
            const lista = this.todas();
            if (!this.filtrando) return lista;

            const terminos = normalizarTexto(this.consulta).split(/\s+/).filter(Boolean);
            if (!terminos.length) return lista;

            return lista.filter((o) => {
                const etiqueta = normalizarTexto(this.etiquetaDe(o));
                return terminos.every((termino) => etiqueta.includes(termino));
            });
        },

        idOpcion(indice) {
            return `${id}-opcion-${indice}`;
        },

        /**
         * Deja el campo mostrando lo que está elegido. Corre en un `x-effect`,
         * así que también reacciona cuando el valor lo cambia otro —abrir la
         * edición de un producto ya cargado— y no solo cuando se elige acá.
         *
         * No toca nada con la lista abierta: ahí el texto es lo que el usuario
         * está escribiendo. Y no lee `this.consulta`, que es la variable que
         * escribe, para no reactivarse a sí misma.
         */
        sincronizar() {
            const etiqueta = this.etiquetaDe(this.opcionElegida());
            if (!this.abierto) this.consulta = etiqueta;
        },

        abrir() {
            this.abierto = true;
            this.filtrando = false;
            const elegida = this.opcionElegida();
            const lista = this.todas();
            this.resaltado = elegida ? Math.max(lista.indexOf(elegida), 0) : 0;
            this.$nextTick(() => this.desplazarALaResaltada());
        },

        /**
         * Cierra sin cambiar el valor y devuelve el campo al camino de la
         * opción elegida. Si no, quedaría mostrando "ani" mientras el producto
         * tiene guardado "Joyas - Anillos": el campo estaría mintiendo.
         */
        cerrar() {
            this.abierto = false;
            this.filtrando = false;
            this.consulta = this.etiquetaDe(this.opcionElegida());
        },

        alEscribir() {
            this.abierto = true;
            this.filtrando = true;
            this.resaltado = 0;
        },

        seleccionar(opcion) {
            if (!opcion) return;
            elegir(opcion.id);
            this.abierto = false;
            this.filtrando = false;
            this.consulta = this.etiquetaDe(opcion);
        },

        /* --- Teclado --- */

        mover(paso) {
            if (!this.abierto) {
                this.abrir();
                return;
            }
            const total = this.filtradas().length;
            if (!total) return;
            this.resaltado = Math.min(Math.max(this.resaltado + paso, 0), total - 1);
            this.$nextTick(() => this.desplazarALaResaltada());
        },

        elegirResaltada() {
            this.seleccionar(this.filtradas()[this.resaltado]);
        },

        /** `block: 'nearest'` mueve solo la lista, nunca la página de atrás. */
        desplazarALaResaltada() {
            document
                .getElementById(this.idOpcion(this.resaltado))
                ?.scrollIntoView({ block: 'nearest' });
        },
    };
};

/**
 * Cierra la sesión: revoca el refresh token y borra las cookies.
 * Se llama desde el menú de usuario del header.
 */
window.cerrarSesion = async function () {
    try {
        await fetch('/api/v1/auth/logout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: '{}',
        });
    } catch (e) {
        /* Aunque falle la revocación, se sale igual: las cookies se pierden */
    }
    window.location.href = '/login';
};

/* --------------------------------------------------------------------------
   Integración con HTMX
   -------------------------------------------------------------------------- */

// El backend puede disparar toasts con el header:
//   HX-Trigger: {"toast": {"mensaje": "...", "tipo": "exito"}}
// HTMX convierte ese header en un evento del mismo nombre sobre el body.
document.addEventListener('DOMContentLoaded', function () {
    document.body.addEventListener('toast', function (evt) {
        if (evt.detail) {
            window.toast(evt.detail.mensaje, evt.detail.tipo, evt.detail.duracion);
        }
    });
});

// Cualquier respuesta de error de la API muestra un toast, sin que cada
// pantalla tenga que manejarlo (Principio 2: DRY).
document.addEventListener('htmx:responseError', function (evt) {
    let mensaje = 'Ocurrió un error al procesar la solicitud.';
    try {
        const cuerpo = JSON.parse(evt.detail.xhr.responseText);
        if (cuerpo.detail) {
            mensaje = typeof cuerpo.detail === 'string'
                ? cuerpo.detail
                : JSON.stringify(cuerpo.detail);
        }
    } catch (e) {
        /* respuesta no-JSON: se usa el mensaje genérico */
    }
    window.toast(mensaje, 'error');
});

document.addEventListener('htmx:sendError', function () {
    window.toast('Sin conexión con el servidor.', 'error');
});

// Adjunta el fingerprint del dispositivo a cada request de HTMX, para que
// el backend pueda recuperar la identidad cuando no hay cookie.
document.body?.addEventListener('htmx:configRequest', function (evt) {
    if (window.__deviceFingerprint) {
        evt.detail.headers['X-Device-Fingerprint'] = window.__deviceFingerprint;
    }
});

/* --------------------------------------------------------------------------
   Atajos de teclado globales

   Los definidos por el design system: F2 buscar, F10 confirmar, ESC cancelar.
   Cada pantalla decide qué hacer escuchando los eventos que se despachan acá.
   -------------------------------------------------------------------------- */

document.addEventListener('keydown', function (evt) {
    // No interceptar mientras se escribe en un campo, salvo ESC.
    const editando = ['INPUT', 'TEXTAREA', 'SELECT'].includes(
        document.activeElement?.tagName
    );

    switch (evt.key) {
        case 'F2':
            evt.preventDefault();
            document.getElementById('buscador-global')?.focus();
            window.dispatchEvent(new CustomEvent('atajo-buscar'));
            break;

        case 'F10':
            if (editando && document.activeElement.tagName === 'TEXTAREA') return;
            evt.preventDefault();
            window.dispatchEvent(new CustomEvent('atajo-confirmar'));
            break;

        case 'Escape':
            window.dispatchEvent(new CustomEvent('atajo-cancelar'));
            break;
    }
});
