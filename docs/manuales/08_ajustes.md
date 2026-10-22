# Manual de usuario — Ajustes

## ¿Para qué sirve este módulo?

Ajustes reúne los parámetros que cambian el comportamiento de todo el sistema y la configuración de las impresoras de etiquetas. Es **exclusivo de la Cuenta Maestra**.

Accedé desde el sidebar: **Ajustes** (abajo de todo). Se abre una página con dos tarjetas:

- **Parámetros generales:** precios, descuentos, señas, puntos y plazos de cambio.
- **Impresoras:** las impresoras Zebra de etiquetas, qué rollo imprime cada una y sus ajustes.

---

## Parámetros generales

| Parámetro | Para qué |
|---|---|
| Redondeo de precios | Múltiplo al que se redondean los precios de venta |
| Máximo por producto | Tope del descuento propio de cada producto |
| Tope total en la venta | La suma del descuento del producto y el de la venta no puede pasarlo |
| Paso de los porcentajes | La vendedora elige el descuento de una lista que va de este valor en este valor |
| Vigencia de las señas | Días desde que se deja la seña hasta que vence |
| Pesos por punto | Cuántos pesos de compra suman un punto |
| Plazo habitual de cambio | Pasado este plazo, el cambio avisa (no se bloquea) |

Al guardar, el sistema pide **dos confirmaciones**: primero muestra qué cambia (antes → después) y después pide aplicarlo. Los cambios rigen desde que se guardan: las ventas, señas y puntos ya registrados no cambian.

---

## Impresoras

### Qué hace falta en cada PC

Las etiquetas salen por **Zebra Browser Print**, un programa gratis de Zebra que va instalado en cada PC desde donde se imprime. El sistema arma la etiqueta y Browser Print se la pasa a la Zebra.

1. Instalar Browser Print (una vez por PC) y aceptar la licencia y el aviso de seguridad que abre el navegador.
2. En la configuración de Browser Print (clic en el iconito de Zebra al lado del reloj → **Settings**), **tildar "Driver Search"**. Sin esto no ve las Zebra compartidas desde otra PC. Hay que hacerlo con **cada usuario de Windows** que use esa PC.
3. La PC que tiene conectada cada Zebra tiene que estar **prendida y sin suspender**.

### Ver las impresoras

Arriba de la pantalla se ve si **Browser Print responde en esta PC** y cuántas impresoras ve. **"Volver a buscar en Browser Print"** vuelve a preguntar.

Cada impresora cargada muestra si Browser Print **la ve** o **no la ve**.

### Agregar una impresora

- Si Browser Print ve una impresora que no está cargada, aparece en un aviso con el botón **"Agregar como impresora nueva"**. Si en realidad es una que **cambió de nombre**, no la agregues: elegí el nombre nuevo en su ficha y guardá.
- También se puede agregar **a mano**, por si en ese momento no está conectada: **"+ Agregar"**, con un nombre para mostrar y el nombre exacto con el que la ve Browser Print (por ejemplo `\\STELLA\ZDesigner GC420t (EPL)`).

### Qué impresora imprime cada tipo de etiqueta

Cada tipo de etiqueta (**Múltiple 32×10** y **Colita 66×11**) tiene **una** impresora asignada: la que tiene puesto ese rollo. Al imprimir no se elige impresora, así no se manda una colita a la Zebra que tiene el rollo de la múltiple. Un tipo **sin impresora no se puede imprimir**.

Elegí la impresora de cada tipo y hacé clic en **"Guardar"**.

### La ficha de cada impresora

| Dato | Para qué |
|---|---|
| Nombre | Para reconocerla en las pantallas |
| Nombre en Browser Print | Cómo la encuentra el sistema |
| Corrimiento horizontal y vertical (mm) | Si la etiqueta sale corrida |
| Oscuridad (0 a 30) | Muy clara no se lee; muy oscura se empasta. 14 es la del sistema anterior |
| Velocidad (2 a 6) | Más lenta imprime más nítido. 2 es la más lenta |

Si una etiqueta sale corrida o clara, **se corrige acá**, no en Browser Print: estos ajustes van dentro de cada etiqueta que se manda a esa impresora.

- **Etiqueta de prueba:** guarda la ficha y manda una fila de prueba con esos ajustes.
- **Calibrar rollo:** la Zebra avanza algunas etiquetas en blanco para medir el rollo. Usalo cuando se cambia el rollo o la cinta y las etiquetas salen corridas.
- **Quitar:** saca la impresora. No se puede si tiene asignado un tipo de etiqueta: primero asigná otra.

---

## Preguntas frecuentes

**Dice "Browser Print no responde en esta PC". ¿Qué hago?**
Fijate que esté el iconito de Zebra al lado del reloj. Si no está, abrí "Zebra Browser Print" desde el menú Inicio. Si se actualizó Windows o el navegador, puede que haya que volver a aceptar el aviso de seguridad de Browser Print.

**Browser Print responde, pero "no ve" una impresora.**
Revisá que la PC que la tiene conectada esté prendida y sin suspender, y que en Browser Print esté tildado **"Driver Search"** con tu usuario de Windows.

**Mandé a imprimir y no salió nada.**
Si la impresora no recibió la orden, el sistema lo avisa y esas etiquetas no se dan por impresas. Browser Print no las guarda para después: cuando la impresora vuelva a estar disponible, mandalas de nuevo.

**¿Cambiar la oscuridad o el corrimiento afecta las etiquetas ya impresas?**
No. Rige para lo que se imprima desde que se guarda la ficha.
