# Manual de usuario — Productos

## ¿Para qué sirve este módulo?

El módulo de Productos es el catálogo del sistema. Desde acá se dan de alta los artículos, se administran sus variantes (talle, color, etc.), se cargan fotos y se generan etiquetas con código de barras.

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

## Etiquetas con código de barras

El sistema genera etiquetas para imprimir en impresora Zebra GC420t.

### Imprimir etiquetas de un producto

1. Abrí la ficha del producto o seleccioná variantes en el listado.
2. Hacé clic en **"Imprimir etiquetas"**.
3. Indicá la cantidad de etiquetas por variante.
4. Hacé clic en **"Generar"**.

El archivo ZPL se descarga listo para enviar a la impresora Zebra.

---

## Activar / Desactivar productos

Un producto inactivo no aparece en la búsqueda para vender.

### Desactivar un producto

- **Individual**: en el listado, usá el switch de Estado de la fila.
- **Masivo**: marcá varios productos con el checkbox y usá **"Desactivar seleccionados"**.

### Filtro de stock 0

Usá el filtro **"Stock 0"** para ver rápidamente todos los artículos sin stock y desactivarlos masivamente si ya no se venden.

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
