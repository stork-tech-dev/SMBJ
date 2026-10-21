/* ==========================================================================
   Cliente mínimo de Zebra Browser Print: el programa de Zebra instalado en
   cada PC desde donde se imprimen etiquetas. Hace lo mismo que la librería
   oficial (BrowserPrint.js): habla con su servicio local. Portado del
   prototipo del cliente, probado el 20/10/2026 con sus dos Zebra GC420t.

   ES EL ÚNICO LUGAR QUE MANDA A IMPRIMIR (regla del cliente): si un día se
   cambia Browser Print por otro programa, se cambia solo este archivo.

   Reglas:
    - La etiqueta va como TEXTO ZPL tal cual la arma el servidor; Browser
      Print no la modifica.
    - La impresora se elige por el NOMBRE de su ficha, nunca por la
      "predeterminada": cada rollo va a la Zebra que lo tiene puesto.
    - Si Browser Print no responde, se avisa y NO se da nada por impreso
      (las funciones tiran el error; quien llama lo muestra).

   Browser Print escucha en http://127.0.0.1:9100 y en https://localhost:9101
   (este último con el certificado que se acepta al instalarlo). Desde una
   página en https se usa el https: el navegador no deja a una página
   segura pedirle nada a un http.
   ========================================================================== */

window.BrowserPrint = {
    base: window.location.protocol === 'https:' ? 'https://localhost:9101' : 'http://127.0.0.1:9100',

    /** Nombres de las impresoras que ve Browser Print en esta PC. */
    async impresoras() {
        let resp;
        try {
            resp = await fetch(this.base + '/available');
        } catch (e) {
            throw new Error('Browser Print no responde en esta PC: ¿está instalado y abierto (el iconito de Zebra al lado del reloj)?');
        }
        if (!resp.ok) throw new Error('Browser Print respondió ' + resp.status);
        const datos = await resp.json();
        return datos.printer || [];
    },

    /** El dispositivo de Browser Print con ese nombre, o null si no lo ve. */
    async buscar(nombre) {
        const lista = await this.impresoras();
        return lista.find((d) => d.name === nombre || d.uid === nombre) || null;
    },

    /** Manda un ZPL a un dispositivo. Tira error si Browser Print no lo acepta. */
    async enviar(dispositivo, zpl) {
        // text/plain evita el "preflight" de CORS; el cuerpo igual es JSON,
        // que es como lo espera Browser Print.
        const resp = await fetch(this.base + '/write', {
            method: 'POST',
            headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
            body: JSON.stringify({ device: dispositivo, data: zpl }),
        });
        if (!resp.ok) throw new Error((await resp.text()) || ('Browser Print respondió ' + resp.status));
    },

    /**
     * Manda varias órdenes ZPL a la impresora de una ficha, en orden.
     * `impresora` = { nombre, browser_print }.
     */
    async imprimir(impresora, zpls) {
        const dispositivo = await this.buscar(impresora.browser_print);
        if (!dispositivo) {
            throw new Error('Browser Print no ve "' + impresora.nombre + '": ¿está prendida la PC que la tiene? ¿Está tildado "Driver Search"?');
        }
        for (const zpl of zpls) await this.enviar(dispositivo, zpl);
    },
};
