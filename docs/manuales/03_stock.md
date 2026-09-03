# Manual de usuario — Gestión de Stock

## ¿Para qué sirve este módulo?

El módulo de Stock permite consultar el inventario, registrar ingresos y bajas de mercadería, definir mínimos de reposición, realizar auditorías de conteo físico y gestionar los remitos (transferencias entre locales).

Accedé desde el sidebar: **Gestión de Stock**.

---

## Consulta de stock

Mostrá el stock disponible de todos los artículos en cada ubicación.

### Filtros disponibles

| Filtro | Cómo funciona |
|---|---|
| Texto libre | Busca en descripción, SKU y SKU proveedor |
| Categoría | Filtra por rama del árbol de categorías |
| Proveedor | Filtra por proveedor |
| Local | Filtra por punto de venta (si tenés acceso a varios) |

### Exportar

Hacé clic en **"Exportar XLS"** para descargar el listado en Excel.

---

## Movimientos de stock

Registrá ingresos (entrada de mercadería) y bajas (pérdida, rotura, robo, etc.).

Accedé desde: **Gestión de Stock → Movimientos**.

### Registrar un ingreso

1. Hacé clic en **"+ Nuevo movimiento"**.
2. Seleccioná tipo: **Ingreso**.
3. Elegí el local de destino.
4. Escaneá o ingresá los códigos de los artículos.
5. Indicá la cantidad de cada uno.
6. Hacé clic en **"Confirmar"**.

### Registrar una baja

1. Hacé clic en **"+ Nuevo movimiento"**.
2. Seleccioná tipo: **Baja**.
3. Elegí el motivo de la baja (rotura, vencimiento, robo, etc.).
4. Escaneá o ingresá los artículos afectados con su cantidad.
5. Hacé clic en **"Confirmar"**.

> Los motivos de baja se configuran desde **Configuración → Motivos de baja**.

---

## Mínimos de stock

Definí la cantidad mínima que debe haber de cada artículo. Cuando el stock cae por debajo del mínimo, el sistema lo indica visualmente.

Accedé desde: **Gestión de Stock → Mínimos**.

### Definir un mínimo

1. Buscá el artículo en el listado.
2. Hacé clic en el campo **"Mínimo"** de la fila.
3. Ingresá la cantidad mínima deseada.
4. Guardá con Enter o moviendo el foco a otro campo.

---

## Auditorías de inventario

Una auditoría es un conteo físico del stock para verificar que lo que dice el sistema coincide con lo que hay en la estantería.

Accedé desde: **Gestión de Stock → Auditorías**.

### Crear una auditoría

1. Hacé clic en **"+ Nueva auditoría"**.
2. Seleccioná el local a auditar.
3. Opcionalmente filtrá por categoría.
4. Hacé clic en **"Crear"**.

Se genera una auditoría en estado **"En curso"** con todos los artículos del local.

### Cargar el conteo

1. Abrí la auditoría en estado "En curso".
2. Por cada artículo, ingresá la cantidad contada físicamente.
3. Podés escanear el código del artículo para ubicarlo rápido en la lista.
4. Guardá mientras avanzás — el conteo no se pierde si salís y volvés.

### Cerrar la auditoría

1. Cuando terminaste de contar todos los artículos, hacé clic en **"Cerrar auditoría"**.
2. El sistema muestra las diferencias entre el stock del sistema y el contado.
3. Confirmá el cierre. Las diferencias quedan registradas pero **no ajustan el stock automáticamente** — los ajustes se hacen con movimientos de ingreso o baja.

### Exportar resultados

Desde la auditoría cerrada, hacé clic en **"Exportar XLS"** para descargar el informe completo con diferencias.

---

## Remitos (transferencias entre locales)

Un remito registra la transferencia de mercadería entre dos locales. El stock sale del origen cuando se despacha y entra al destino cuando se confirma la recepción.

### Desde desktop

Accedé desde: **Gestión de Stock → Remitos**.

#### Armar un envío (origen)

1. Hacé clic en **"+ Armar envío"**.
2. Elegí el local de **origen** y el de **destino**.
3. Escaneá o ingresá los códigos de los artículos a enviar.
4. Ajustá las cantidades si es necesario.
5. Agregá notas si hace falta.
6. Hacé clic en **"Crear remito"**.

El stock sale del origen en este momento.

#### Despachar un remito

Un remito armado queda en estado **"Pendiente"** hasta que se despacha (la mercadería sale físicamente).

1. En el listado, buscá el remito en estado "Pendiente".
2. Hacé clic en **"Despachar"**.
3. El sistema genera el PDF del remito para imprimir y enviar con la mercadería.

#### Confirmar la recepción (destino)

1. En el listado, buscá el remito en estado "En camino".
2. Hacé clic en **"Recibir"**.
3. **Ingresá el número del remito** (el que dice el papel que vino con la mercadería). Este es el campo de confirmación obligatorio.
4. Revisá las cantidades recibidas — vienen pre-cargadas con lo enviado. Modificá si recibiste menos.
5. Agregá notas si hay observaciones.
6. Hacé clic en **"Confirmar recepción"**.

Si las cantidades recibidas difieren de las enviadas, el estado queda en **"Con diferencia"** y se notifica al responsable.

### Desde mobile (celular del local)

En el celular del local, accedé a **Remitos** desde la pantalla de inicio.

La pantalla mobile muestra tres secciones:

**1. Pendientes de recibir**: remitos en camino hacia tu local. Tocá **"Recibir"** para confirmar la recepción.

**2. Armados sin despachar**: remitos que creaste pero aún no salieron. Tocá **"Despachar"** cuando la mercadería se va.

**3. Historial reciente**: remitos confirmados o con diferencia. Tocá cualquiera para ver el detalle.

#### Armar un envío desde mobile

1. Tocá el botón flotante **"+ Armar envío"**.
2. Elegí origen y destino.
3. Escaneá los artículos con la cámara del celular.
4. Confirmá.

---

## Preguntas frecuentes

**¿Qué pasa con el stock cuando anulo una venta?**
El stock vuelve automáticamente al local donde se realizó la venta.

**¿Puedo transferir stock al depósito central?**
Sí, los remitos funcionan entre cualquier par de locales, incluido el Centro de Distribución.

**¿La auditoría ajusta el stock automáticamente?**
No. La auditoría solo registra diferencias. Los ajustes se hacen manualmente con movimientos de ingreso o baja según corresponda.

**¿Qué significa "Con diferencia" en un remito?**
Que la cantidad recibida no coincide con la enviada. Queda registrado para revisión del dueño o supervisor.
