# Manual de usuario — Configuración

## ¿Para qué sirve este módulo?

El módulo de Configuración centraliza los parámetros del sistema: medios de pago, planes de cuotas, motivos de descuento y promociones. Solo pueden acceder usuarios con los permisos correspondientes (normalmente Cuenta Maestra y, en algunos casos, Supervisor).

Accedé desde el sidebar: **Configuración**.

---

## Medios de pago

Los medios de pago son las formas en que los clientes pueden pagar: efectivo, débito, crédito, transferencia, etc.

### Ver los medios de pago

Accedé desde: **Configuración → Medios de pago**.

La tabla muestra todos los medios de pago con su estado y si soportan cuotas.

### Dar de alta un medio de pago

1. Hacé clic en **"+ Nuevo medio de pago"**.
2. Ingresá el nombre (ej: "Tarjeta Visa").
3. Indicá si soporta cuotas.
4. Hacé clic en **"Crear"**.

### Editar un medio de pago

1. Hacé clic en el ícono de edición ✏️.
2. Modificá los datos.
3. Guardá los cambios.

### Desactivar un medio de pago

Los medios de pago **no se borran**: las ventas ya cobradas apuntan a ellos y borrarlos dejaría esos registros sin referencia.

Usá el switch de Estado para desactivarlos. Un medio inactivo no aparece en el punto de venta.

---

## Planes de cuotas

Los planes de cuotas se configuran para cada medio de pago que soporta cuotas.

### Ver planes de un medio de pago

En el listado de medios de pago, hacé clic en **"Ver planes"** del medio correspondiente.

### Agregar un plan de cuotas

1. Hacé clic en **"+ Nuevo plan"**.
2. Completá:
   - **Cantidad de cuotas** (ej: 3, 6, 12).
   - **Recargo al cliente** (%): lo que paga de más el cliente por pagar en cuotas.
   - **Costo del medio** (%): lo que cobra la terminal o el banco (no afecta el precio al cliente).
3. Hacé clic en **"Agregar"**.

> El recargo al cliente y el costo del medio son dos campos distintos. El costo del medio es solo informativo — no se suma al precio de la venta.

### Desactivar un plan

Los planes no se borran. Desactivalos con el switch de Estado. Un plan inactivo no aparece en el punto de venta.

---

## Motivos de descuento

Los motivos de descuento son las razones por las que una vendedora puede aplicar un descuento: empleado, mayorista, promoción especial, etc.

Accedé desde: **Configuración → Motivos de descuento**.

### Dar de alta un motivo

1. Hacé clic en **"+ Nuevo motivo"**.
2. Ingresá el nombre del motivo.
3. Indicá si el motivo **habilita cuotas sin interés** (ej: el descuento de empleado puede incluir cuotas sin recargo).
4. Opcionalmente, ingresá un **porcentaje sugerido** (en múltiplos de 5: 5%, 10%, 15%...).
5. Hacé clic en **"Crear"**.

> El porcentaje sugerido es solo una preselección para la vendedora; puede cambiarlo al aplicar el descuento si tiene permiso.

### Desactivar un motivo

Los motivos no se borran. Las ventas ya realizadas con ese motivo mantienen el registro. Usá el switch de Estado para desactivarlos.

---

## Promociones

Las promociones permiten configurar descuentos automáticos que se aplican al agregar ciertos productos al carrito.

Accedé desde: **Configuración → Promociones**.

> El Supervisor también puede crear y editar promociones, aunque no tenga acceso a los demás ítems de configuración.

### Tipos de promoción

| Tipo | Cómo funciona |
|---|---|
| Porcentaje | Descuento de X% sobre los artículos incluidos |
| 2×1 / 3×2 | El cliente lleva N artículos y paga M |

### Crear una promoción

1. Hacé clic en **"+ Nueva promoción"**.
2. Ingresá el nombre de la promoción.
3. Seleccioná el tipo.
4. Definí el **alcance**: qué productos o categorías aplican.
   - Podés agregar categorías completas (incluye todos los subproductos de esa categoría) o productos individuales.
5. Definí las fechas de vigencia (inicio y fin).
6. Hacé clic en **"Crear"**.

### Activar y desactivar promociones

Una promoción puede estar activa (configurada) pero fuera de vigencia (las fechas no coinciden con hoy). Son dos cosas distintas:

- **Activa/Inactiva**: switch de Estado. Una promoción inactiva nunca aplica.
- **Vigente**: si la fecha de hoy cae entre inicio y fin. Aparece como indicador en el listado.

Las promociones no se borran: las ventas ya confirmadas guardan la referencia a la promoción que aplicó.

---

## Preguntas frecuentes

**¿Puedo borrar un medio de pago que creé por error?**
No. Los medios de pago se desactivan, no se borran. Si lo creaste por error y todavía no se usó en ninguna venta, contactá al soporte técnico para evaluarlo.

**¿Las promociones se aplican automáticamente?**
Sí. Cuando la vendedora agrega productos al carrito, el sistema detecta si aplica alguna promoción vigente y la aplica solo.

**¿Cuántas promociones pueden estar activas al mismo tiempo?**
No hay límite. Si dos promociones aplican al mismo artículo, el sistema aplica la que sea más beneficiosa para el cliente.

**¿Puedo cambiar las fechas de una promoción que ya empezó?**
Sí. Las ventas ya realizadas no se modifican (guardaron el precio y la promoción que aplicó); solo las ventas futuras usan las nuevas fechas.

**¿Qué pasa si desactivo el medio de pago "Efectivo"?**
No va a aparecer en el punto de venta. Asegurate de desactivarlo solo si tenés razón de hacerlo — en la mayoría de los locales el efectivo siempre debe estar disponible.
