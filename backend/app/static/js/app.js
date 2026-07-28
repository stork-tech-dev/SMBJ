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
