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

/**
 * Sesión terminada: avisa y manda al login.
 *
 * Con `AuthRefreshMiddleware` en el backend, un 401 ya no significa "venció
 * el token de 30 minutos" —eso se renueva solo— sino que tampoco hay refresh:
 * pasaron los 7 días o alguien cerró sesión. Es el final del camino, así que
 * no se reintenta nada.
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
    const respuesta = await fetchOriginal(...args);
    if (respuesta.status === 401) {
        const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
        // El login contesta 401 con las credenciales mal: ahí el 401 es la
        // respuesta esperada, no una sesión caída.
        if (!url.includes('/api/v1/auth/')) sesionTerminada();
    }
    return respuesta;
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
