# Manual de usuario — Productos

## ¿Para qué sirve este módulo?

El módulo de Productos es el catálogo del sistema. Desde acá se dan de alta los artículos, se administran sus variantes (talle, color, etc.), se cargan fotos y se generan las etiquetas con su código.

---

## Listado de productos

Accedé desde el sidebar: **Productos**.

La tabla muestra una fila por cada **variante**, no por producto. Un producto con tres talles ocupa tres filas porque cada una tiene su propio stock y su propia etiqueta.

### Columnas principales

| Columna | Qué muestra |
|---|---|
| SKU | Código interno del sistema |
| Descripción | Nombre del producto + sufijo de variante |
| Categoría | Árbol de categorías |
| Proveedor | Proveedor del artículo |
| Precio USD / Precio $ | Precios actuales |
| Stock | Cantidad disponible en el local o total |
| Estado | Activo / Inactivo |

### Filtros disponibles

| Filtro | Cómo funciona |
|---|---|
| Texto libre | Busca en descripción, SKU y SKU proveedor |
| Categoría | Filtra por rama completa |
| Proveedor | Filtra por proveedor |
| Estado | Todos / Activo / Inactivo |
| Stock 0 | Muestra solo artículos sin stock |

---

## Dar de alta un producto

1. Hacé clic en **"+ Nuevo producto"**.
2. Completá el formulario:

### Campos del formulario

| Campo | Obligatorio | Descripción |
|---|---|---|
| Categoría | Sí | Elegí hasta el último nivel del árbol |
| Proveedor | Sí | Solo en el alta; no se puede cambiar después |
| Descripción | Sí | Nombre del artículo (mínimo 1 carácter) |
| Precio USD | Sí | Precio de costo en dólares |
| SKU Proveedor | No | Código del proveedor para identificar el artículo |
| Descuento % | No | Descuento permanente del producto |
| Peso (gramos) | No | Peso para cálculo de envíos |
| Temporada | No | Atemporal / Otoño-Invierno / Primavera-Verano |
| Foto | No | Una foto inicial (se pueden agregar más desde la ficha) |
| Stock inicial | No | Cantidad en el Centro de Distribución al dar de alta |

> **Descripción duplicada**: el sistema avisa si ya existe un artículo con nombre, categoría y proveedor iguales. Si es el mismo artículo en otro color o talle, usá variantes en vez de crear otro producto.

3. Hacé clic en **"Crear"** (crea el producto con una sola variante base) o **"Crear con variantes"** (abre el formulario de variantes inmediatamente).

---

## Variantes

Un producto puede tener múltiples variantes para representar diferentes talles, colores u otras características.

### Agregar una variante

1. Abrí la ficha del producto (ícono 👁).
2. Hacé clic en **"+ Agregar variante"**.
3. Completá:
   - **Sufijo**: lo que distingue esta variante (ej: `T` para talle, `C` para color).
   - **Descripción del sufijo**: el valor concreto (ej: `38`, `Rojo`).
   - **SKU Proveedor** (opcional).
   - **Precio USD** (si difiere del producto base).
   - **Ubicación en depósito** (opcional).
4. Hacé clic en **"Agregar"**.

### Editar una variante

1. Abrí la ficha del producto.
2. Hacé clic en el ícono de edición ✏️ de la variante.
3. Modificá los campos y guardá.

---

## Fotos

Cada producto tiene hasta 5 fotos. Las fotos pueden ser del producto completo (compartidas por todas las variantes) o específicas de una variante.

### Subir una foto

1. Abrí la ficha del producto.
2. En la sección de fotos, hacé clic en **"Subir foto"** o **"Tomar foto"** (con cámara).
3. La primera foto que subís se marca como principal automáticamente.

### Cambiar la foto principal

Hacé clic en el ícono de estrella ⭐ de la foto que querés como principal.

### Eliminar una foto

Hacé clic en el ícono de papelera 🗑️ de la foto. Se pide confirmación.

---

## Etiquetas

El sistema genera etiquetas para imprimir en impresora Zebra GC420t.

### Imprimir etiquetas de un producto

1. Abrí la ficha del producto o seleccioná variantes en el listado.
2. Hacé clic en **"Imprimir etiquetas"**.
3. Indicá la cantidad de etiquetas por variante.
4. Hacé clic en **"Generar"**.

Se descarga un PDF listo para imprimir en la Zebra.

Cada etiqueta lleva un **código cuadrado (DataMatrix)** a la izquierda y el número del código a la derecha, en letra grande para poder leerlo y tipearlo. El código cuadrado es el que se lee con la cámara del celular: aunque la etiqueta esté algo gastada o arrugada, se sigue leyendo.

En la ficha de cada variante se ve el mismo código cuadrado que sale impreso.

> **Etiquetas viejas, con código de barras (rayas):** desde el 20/10/2026 la cámara del celular **ya no las lee**. Hay que reimprimirlas para que salgan con el código cuadrado. Mientras tanto, el número se puede tipear a mano.

---

## Activar / Desactivar productos

Un producto inactivo no aparece en la búsqueda para vender.

### Desactivar un producto

- **Individual**: en el listado, usá el switch de Estado de la fila.
- **Masivo**: marcá varios productos con el checkbox y usá **"Desactivar seleccionados"**.

### Filtro de stock 0

Usá el filtro **"Stock 0"** para ver rápidamente todos los artículos sin stock y desactivarlos masivamente si ya no se venden.

---

## Historial del Producto

Muestra toda la vida de un producto en un solo informe. Está en **Reportes → Reportes de Producto → Historial del Producto** y requiere permiso de **Reportes** para ver.

### Buscar el producto

Escribí al menos 2 caracteres del **SKU**, de la **descripción** o del **código de etiqueta**. A medida que escribís aparecen los productos que coinciden, cada uno con su foto. Tocá el que quieras para ver su historial.

El producto elegido queda en la dirección de la página: podés guardar el link o compartirlo para volver directo a ese producto.

### Qué muestra

Arriba, una ficha con el precio de venta, el stock actual y la cantidad de variantes. Debajo, cinco partes, cada una ordenada de lo más reciente a lo más viejo:

- **Carga**: cuándo se dio de alta el producto y cada variante, y cada ingreso de mercadería (cantidad, dónde y quién).
- **Movimientos de stock**: todos los movimientos, con tipo, variante, cantidad, origen → destino, quién lo hizo y su referencia (remito, venta o compra).
- **Ventas**: un resumen por local (unidades e importe) y el detalle de cada venta. Solo cuentan las ventas confirmadas.
- **Fallas**: los cambios por falla (con quién los autorizó) y las bajas de stock (con su motivo: rotura, robo, merma…).
- **Modificaciones de precio**: los cambios de precio en dólares, de precio de venta o de descuento (antes → después y quién), y cada cambio del dólar del proveedor desde el alta del producto, aclarando si fue masivo o por importación de Excel.

En los cambios de dólar se ve el dólar anterior y el nuevo, no el precio de venta que resultó: ese precio no queda guardado.

### Descargar en PDF

Con el producto elegido, tocá **"Descargar PDF"** para bajar el mismo informe con el logo de la empresa.

---

## Preguntas frecuentes

**¿Puedo cambiar el proveedor de un producto?**
No. El proveedor determina el tipo de cambio para calcular el precio en pesos y no se puede cambiar después del alta.

**¿Cómo se actualiza el precio en pesos?**
Automáticamente cuando cambia el dólar del proveedor. No hace falta tocar nada en el producto.

**¿Puedo borrar un producto?**
Los productos no se borran, se desactivan. Esto preserva el historial de ventas.

**¿Qué es el SKU?**
Un código único que genera el sistema para identificar cada variante. Se usa en las etiquetas y en el punto de venta.

**¿Por qué una venta no aparece en el Historial del Producto?**
Solo se muestran las ventas confirmadas. Las anuladas o las que todavía están en curso no aparecen.
