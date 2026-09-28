/* ==========================================================================
   Campanita de notificaciones del header (Dueño y Cuenta Maestra).

   Hoy las genera el cierre de turno con diferencia de arqueo. El número se
   pide a /api/v1/notificaciones/contador al cargar y cada minuto; la lista
   recién al abrir el panel.
   ========================================================================== */

const API_NOTIFICACIONES = '/api/v1/notificaciones';
const MAX_EN_PANEL = 20;

function notificaciones() {
    return {
        abierto: false,
        cargando: false,
        noLeidas: 0,
        lista: [],

        iniciar() {
            this.contar();
            setInterval(() => this.contar(), 60_000);
        },

        async contar() {
            try {
                this.noLeidas = (await window.pedir(`${API_NOTIFICACIONES}/contador`)).no_leidas;
            } catch {
                // Silencioso: un badge que no se actualiza no es motivo de toast.
            }
        },

        async alternar() {
            this.abierto = !this.abierto;
            if (!this.abierto) return;
            this.cargando = true;
            try {
                this.lista = (await window.pedir(API_NOTIFICACIONES)).slice(0, MAX_EN_PANEL);
            } catch (e) {
                window.toast(e.message, 'error');
            } finally {
                this.cargando = false;
            }
        },

        async leer(n) {
            if (n.leida) return;
            try {
                await window.pedir(`${API_NOTIFICACIONES}/${n.id}/leer`, { method: 'PATCH' });
                n.leida = true;
                this.noLeidas = Math.max(0, this.noLeidas - 1);
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        async leerTodas() {
            try {
                await window.pedir(`${API_NOTIFICACIONES}/leer-todas`, { method: 'PATCH' });
                this.lista.forEach((n) => { n.leida = true; });
                this.noLeidas = 0;
            } catch (e) {
                window.toast(e.message, 'error');
            }
        },

        fecha(iso) {
            return new Date(iso).toLocaleString('es-AR', {
                day: '2-digit', month: '2-digit', year: '2-digit',
                hour: '2-digit', minute: '2-digit', hour12: false,
            });
        },
    };
}
