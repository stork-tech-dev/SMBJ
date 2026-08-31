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

/**
 * Importe en pesos, mostrando EXACTAMENTE lo que guarda el backend.
 *
 * Los decimales aparecen solo si existen. La pantalla NO vuelve a redondear:
 * el redondeo del precio es una regla de negocio, lo hace el backend y es
 * CEIL sobre el múltiplo configurado. Una versión anterior de esta función
 * usaba `maximumFractionDigits: 0`, que aplica su propio redondeo half-up:
 * con el redondeo del sistema en 0,50, un precio guardado como 1234,49 se
 * mostraba "$1.234" — menos de lo que se cobra.
 *
 * Vive acá y no en cada componente porque la usan productos, clientes, el
 * carrito, el cobro y el listado de ventas: copiada seis veces, alcanzaba
 * con corregir una para que las demás mostraran otra cosa (Principio 2).
 */
window.pesos = function (valor) {
    if (valor === null || valor === undefined || valor === '') return '—';
    const n = Number(valor);
    const decimales = Number.isInteger(n) ? 0 : 2;
    return n.toLocaleString('es-AR', {
        style: 'currency',
        currency: 'ARS',
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
 * Estado de un combobox: un campo con su lista desplegable propia. Lo usa el
 * macro `components/combobox.html`.
 *
 * Existe porque un `<select>` nativo no se puede filtrar —tipear solo salta
 * por la primera letra— y las categorías se muestran con su camino completo
 * ("Joyas - Anillos - Plata"), así que todas las de una misma rama empiezan
 * igual y ni ese salto sirve.
 *
 * También lo usan los campos que NO se buscan (`buscable=false` en el macro,
 * como Temporada, que tiene tres opciones): el input va `readonly`, así que
 * `filtrando` nunca se prende y la lista se muestra entera. Es el mismo
 * componente para que todos los desplegables de una pantalla se vean y se
 * manejen igual, que es lo que un `<select>` nativo no permite: su lista la
 * dibuja el sistema operativo y no se puede estilar.
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
window.combobox = function ({ id, opciones, texto, valor, elegir, vacio = null }) {
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
   Captura de foto desde webcam
   --------------------------------------------------------------------------

   Abre un overlay con el video de la cámara y devuelve un Blob JPEG al
   capturar. Si el usuario cancela devuelve null. Si la cámara no está
   disponible la promesa se rechaza.

   Uso:
     const blob = await window.webcamCapture();
     if (blob) { ... }
   -------------------------------------------------------------------------- */

window.webcamCapture = function () {
    return new Promise((resolve, reject) => {
        if (!navigator.mediaDevices?.getUserMedia) {
            reject(new Error('El navegador no soporta acceso a la cámara'));
            return;
        }

        // Crear overlay.
        const overlay = document.createElement('div');
        overlay.className = 'fixed inset-0 z-[60] grid place-items-center bg-black/80 p-4';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');

        const card = document.createElement('div');
        card.className = 'w-full max-w-[36rem] bg-surface rounded-[10px] shadow-[0_0_15px_0_rgba(0,0,0,0.25)] overflow-hidden';
        overlay.appendChild(card);

        // Video.
        const video = document.createElement('video');
        video.autoplay = true;
        video.playsInline = true;
        video.className = 'w-full aspect-[4/3] object-cover bg-black';
        card.appendChild(video);

        // Botones.
        const barra = document.createElement('div');
        barra.className = 'flex justify-center gap-4 px-6 py-4';
        card.appendChild(barra);

        const btnCancelar = document.createElement('button');
        btnCancelar.type = 'button';
        btnCancelar.textContent = 'Cancelar';
        btnCancelar.className = 'h-boton px-5 rounded-input border border-borde text-base hover:border-primary hover:text-primary';
        barra.appendChild(btnCancelar);

        const btnCapturar = document.createElement('button');
        btnCapturar.type = 'button';
        btnCapturar.textContent = 'Capturar';
        btnCapturar.className = 'h-boton px-8 rounded-input bg-primary text-white text-base font-medium hover:bg-primary-hover';
        barra.appendChild(btnCapturar);

        document.body.appendChild(overlay);

        let stream = null;

        function limpiar() {
            if (stream) stream.getTracks().forEach((t) => t.stop());
            overlay.remove();
        }

        // Iniciar cámara.
        navigator.mediaDevices
            .getUserMedia({
                video: { facingMode: 'environment', width: { ideal: 1280 } },
            })
            .then((s) => {
                stream = s;
                video.srcObject = stream;
            })
            .catch((err) => {
                limpiar();
                reject(new Error('No se pudo acceder a la cámara: ' + err.message));
            });

        btnCapturar.addEventListener('click', () => {
            const canvas = document.createElement('canvas');
            canvas.width = video.videoWidth || 1280;
            canvas.height = video.videoHeight || 960;
            canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
            canvas.toBlob(
                (blob) => { limpiar(); resolve(blob); },
                'image/jpeg', 0.85
            );
        });

        btnCancelar.addEventListener('click', () => {
            limpiar();
            resolve(null);
        });

        // Escape cierra.
        function onEscape(e) {
            if (e.key === 'Escape') {
                document.removeEventListener('keydown', onEscape);
                limpiar();
                resolve(null);
            }
        }
        document.addEventListener('keydown', onEscape);
    });
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

/**
 * Sesión terminada: avisa y manda al login.
 *
 * Con `AuthRefreshMiddleware` en el backend, un 401 significa que la sesión
 * ya no sirve: pasaron los minutos de inactividad, se cumplieron los 7 días
 * o alguien cerró sesión. Es el final del camino, así que no se reintenta
 * nada.
 *
 * `yendoAlLogin` evita que varios requests en paralelo disparen tres toasts y
 * tres redirecciones a la vez.
 */
let yendoAlLogin = false;

function sesionTerminada() {
    if (yendoAlLogin) return;
    yendoAlLogin = true;
    window.toast('Tu sesión venció. Volvé a ingresar.', 'error');
    setTimeout(() => { window.location.href = '/login'; }, 1200);
}

// Envolver `fetch` una sola vez acá evita que cada pantalla tenga que
// acordarse de mirar el 401 (Principio 2: DRY). No renueva ni reintenta: de
// eso se ocupa el middleware, mucho antes de que la respuesta llegue.
const fetchOriginal = window.fetch.bind(window);
window.fetch = async function (...args) {
    // Cada request que sale es actividad, y es exactamente lo que el servidor
    // cuenta para correr la ventana: el reloj de esta pantalla y el de la
    // base miran el mismo hecho.
    document.dispatchEvent(new CustomEvent('sesion:actividad'));

    const respuesta = await fetchOriginal(...args);
    if (respuesta.status === 401) {
        const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
        // El login contesta 401 con las credenciales mal: ahí el 401 es la
        // respuesta esperada, no una sesión caída.
        if (!url.includes('/api/v1/auth/')) sesionTerminada();
    }
    return respuesta;
};

// HTMX no pasa por `fetch` —usa XMLHttpRequest—, así que sus requests se
// cuentan por su propio evento. Sin esto, una pantalla que trabaje solo con
// HTMX vería el cartel mientras la sesión se está renovando sola.
document.addEventListener('htmx:afterRequest', function () {
    document.dispatchEvent(new CustomEvent('sesion:actividad'));
});

/**
 * Aviso de "tu sesión está por vencer", con el botón para seguir.
 *
 * El servidor cierra la sesión después de N minutos sin actividad. Este
 * componente lleva el mismo reloj del lado del navegador para avisar DOS
 * minutos antes: en el punto de venta, que te saquen con una venta a medio
 * cargar cuesta la venta.
 *
 * `minutos` lo inyecta el backend desde la misma constante que aplica la
 * regla (`SESION_INACTIVIDAD_MINUTOS`): dos números que puedan separarse
 * terminarían avisando a destiempo, o no avisando nunca.
 *
 * No cuenta clicks ni teclas a propósito: cuenta REQUESTS, que es lo único
 * que el servidor ve. Mover el mouse no mantiene viva una sesión.
 */
const AVISO_ANTES_MS = 2 * 60 * 1000;

window.avisoSesion = function (minutos) {
    return {
        visible: false,
        restante: '2 minutos',
        vence: 0,
        reloj: null,

        init() {
            document.addEventListener('sesion:actividad', () => this.reiniciar());
            this.reiniciar();
        },

        /** Vuelve a arrancar la cuenta: hubo actividad. */
        reiniciar() {
            this.visible = false;
            this.vence = Date.now() + minutos * 60 * 1000;

            clearInterval(this.reloj);
            this.reloj = setInterval(() => this.mirar(), 1000);
        },

        mirar() {
            const falta = this.vence - Date.now();

            if (falta <= 0) {
                // Se acabó: el próximo request va a volver 401 igual, pero no
                // se espera a que el usuario haga uno para decírselo.
                clearInterval(this.reloj);
                this.visible = false;
                sesionTerminada();
                return;
            }

            this.visible = falta <= AVISO_ANTES_MS;
            if (this.visible) {
                const segundos = Math.ceil(falta / 1000);
                this.restante = segundos > 60
                    ? `${Math.ceil(segundos / 60)} minutos`
                    : `${segundos} segundos`;
            }
        },

        /**
         * "Seguir trabajando": renueva la sesión contra el servidor.
         *
         * Va por `/auth/refresh` —que ya existe y ya corre la ventana— y no
         * por un request cualquiera: así el reloj del navegador y el de la
         * base se reinician por el mismo hecho. Si el servidor dice que no,
         * la sesión ya estaba caída y el 401 hace el resto.
         */
        async seguir() {
            if (!this.visible) return;
            this.visible = false;
            try {
                const resp = await fetch('/api/v1/auth/refresh', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({}),
                });
                if (!resp.ok) throw new Error();
                this.reiniciar();
            } catch {
                sesionTerminada();
            }
        },
    };
};

// Cualquier respuesta de error de la API muestra un toast, sin que cada
// pantalla tenga que manejarlo (Principio 2: DRY).
document.addEventListener('htmx:responseError', function (evt) {
    if (evt.detail.xhr.status === 401) {
        sesionTerminada();
        return;
    }

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
