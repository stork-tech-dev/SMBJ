# Manual de usuario — Compras a proveedores

## ¿Para qué sirve este módulo?

El módulo de Compras registra las órdenes de compra a proveedores y la recepción de mercadería. Permite hacer seguimiento de qué se pidió, cuándo llegó y a qué precio, y actualizar los precios de costo cuando cambian.

Accedé desde el sidebar: **Compras**.

---

## Listado de compras

La tabla muestra todas las órdenes de compra con su estado actual.

### Estados de una compra

| Estado | Significado |
|---|---|
| Borrador | En preparación, no enviada al proveedor |
| Enviada | Pedido enviado, esperando mercadería |
| Recibida | Mercadería recibida completa |
| Recibida parcial | Se recibió solo parte del pedido |
| Cancelada | La compra no se concretó |

### Filtros disponibles

| Filtro | Cómo funciona |
|---|---|
| Texto libre | Busca en número y notas |
| Proveedor | Filtra por proveedor |
| Estado | Filtra por estado actual |
| Fecha desde / hasta | Rango de fechas |

---

## Crear una nueva compra

1. Hacé clic en **"+ Nueva compra"** o accedé a **/compras/nueva**.
2. Seleccioná el **proveedor**.
3. Completá los datos de cabecera:
   - Número de orden / referencia del proveedor (opcional).
   - Fecha esperada de entrega (opcional).
   - Notas generales (opcional).

### Agregar ítems

1. En el campo **"Código"**, escaneá el código de barras o escribí el SKU del artículo.
2. El sistema busca la variante y la agrega a la lista.
3. Ajustá la **cantidad** pedida.
4. El **precio USD** se pre-carga con el precio actual del producto; modificalo si el proveedor ofrece un precio distinto para esta compra.
5. Repetí para cada artículo.

> Si el código no existe, podés dar de alta el producto directamente desde esta pantalla con el botón **"Nuevo producto"**.

### Guardar como borrador

Hacé clic en **"Guardar borrador"** para guardar sin enviar. Podés volver a editarlo.

### Enviar la compra

1. Revisá todos los ítems y cantidades.
2. Hacé clic en **"Marcar como enviada"**.
3. El estado cambia a "Enviada" y ya no se puede editar la lista de ítems.

---

## Recibir mercadería

Cuando llega la mercadería del proveedor:

1. En el listado, buscá la compra en estado "Enviada".
2. Hacé clic en **"Recibir"**.
3. Para cada ítem, ingresá la **cantidad recibida** (viene pre-cargada con la cantidad pedida).
4. Si el precio de algún ítem cambió respecto al pedido, actualizalo.
5. Hacé clic en **"Confirmar recepción"**.

El stock se acredita al **Centro de Distribución** en este momento.

### Recepción parcial

Si no llegó todo el pedido:

1. En la pantalla de recepción, modificá las cantidades recibidas a lo que llegó realmente.
2. Los ítems no recibidos quedan pendientes.
3. Hacé clic en **"Confirmar recepción parcial"**.

El estado de la compra queda en "Recibida parcial" hasta que llegue el resto.

---

## Actualización de precios

Cuando un proveedor cambia sus precios, el sistema puede actualizar los precios de costo de los productos de esa compra.

### Confirmar o rechazar un cambio de precio

1. En el detalle de la compra, buscá los ítems marcados con "Precio modificado".
2. Para cada uno, podés:
   - **Confirmar**: el precio de costo del producto se actualiza al nuevo valor.
   - **Rechazar**: el producto mantiene el precio anterior.

> Solo usuarios con permiso de edición de precios pueden realizar esta acción.

---

## Exportar una compra

Desde el detalle de la compra, hacé clic en **"Exportar PDF"** o **"Exportar XLS"** para descargar el detalle completo.

---

## Preguntas frecuentes

**¿Puedo editar una compra después de marcarla como enviada?**
No se pueden agregar ni quitar ítems, pero sí ajustar cantidades y precios al momento de recibir.

**¿Dónde entra el stock al recibir?**
Siempre al Centro de Distribución. Desde ahí se distribuye a los locales con remitos.

**¿Qué pasa si el precio que cobró el proveedor es distinto al que está en el sistema?**
Podés actualizar el precio al momento de recibir. El sistema registra el cambio y te permite confirmar o rechazar la actualización del precio de costo.

**¿Puedo cancelar una compra?**
Sí, mientras esté en estado Borrador o Enviada. Las compras recibidas no se pueden cancelar.
