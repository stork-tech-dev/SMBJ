# Manual de usuario — Ventas

## ¿Para qué sirve este módulo?

El módulo de Ventas es el corazón del sistema. Desde acá se registran las ventas al cliente, se consulta el historial y se gestiona el turno del día. Tiene dos vistas: **desktop** para supervisores y dueños, y **mobile** para las vendedoras en el local.

---

## Vista mobile (celular del local)

### Pantalla de inicio

Al abrir la app desde el celular del local aparece la pantalla de inicio con:

- **Estado del turno**: muestra si el turno está abierto o no. Va primero porque sin turno abierto no se puede vender.
- **Alerta de venta sin concluir**: si hay una venta abierta que no se terminó de cobrar, aparece en rojo. Tocala para retomar.
- **Botón "Nueva venta"**: solo aparece si no tenés ninguna venta sin concluir. Si la tenés, el botón se oculta a propósito — para seguirla usás la alerta roja, así no se te ocurre arrancar una segunda venta antes de cerrar la primera.
- Accesos rápidos: consulta de stock, recepción de mercadería, anulaciones y cambios (según tu permiso — ver más abajo).

---

### Turno del día

El turno es el período de trabajo del local. Sin turno abierto **no se puede vender**.

#### Iniciar turno

1. En la pantalla de inicio, tocá el área del turno.
2. Se abre un panel con el campo **"Efectivo inicial en caja"**.
3. Ingresá el monto en efectivo que hay en caja al abrir.
4. Tocá **Confirmar**.

#### Sumarse a un turno existente

Si otra vendedora ya abrió el turno del día:

1. Tocá el área del turno.
2. Aparece el panel con el nombre de quien lo abrió y la hora.
3. Tocá **"Unirme al Turno"**.

#### Cerrar turno

El cierre del turno incluye el arqueo de caja (ver módulo Caja).

1. Tocá **"Cerrar"** en el área del turno.
2. Seguí el proceso de arqueo.

> **Importante:** Si el turno del día anterior quedó sin cerrar, el sistema bloquea todas las operaciones hasta cerrarlo.

---

### Nueva venta

1. Tocá **"Nueva venta"** en la pantalla de inicio.
2. Aparece el carrito vacío.

#### Agregar productos

- **Por código de barras**: apuntá la cámara o ingresá el código manualmente.
- **Por búsqueda**: escribí el nombre o parte del código y seleccioná de la lista.
- Si el código corresponde a una única variante, se agrega sola. Si hay ambigüedad, el sistema pide que elijas.

#### Modificar cantidades

- Tocá el producto en el carrito para cambiar la cantidad.
- Deslizá a la derecha para eliminarlo.

#### Aplicar descuento

Si tenés permiso:

1. Tocá el ícono de descuento.
2. Ingresá el porcentaje o monto de descuento.
3. Confirmá.

#### Cobrar

1. Tocá **"Cobrar"** (o el botón de confirmación con el total).
2. Seleccioná el medio de pago (efectivo, tarjeta, transferencia, etc.).
3. Si el pago es en cuotas, elegí el plan.
4. Si usás señas, podés aplicar el saldo disponible del cliente.
5. Ingresá el monto para cada medio si la venta es mixta.
6. Tocá **"Confirmar venta"**.

> El sistema descuenta el stock automáticamente al confirmar la venta.

#### Cancelar una venta en curso

Tocá la flecha de retorno. La venta queda guardada como "en curso" por si querés retomar. Para descartarla definitivamente, usá el botón de eliminar del carrito.

---

### Anular una venta desde el celular

Si tenés permiso, en la pantalla de inicio aparece la tarjeta **"Anulaciones"**.

1. Tocá **"Anulaciones"**.
2. Aparece la lista de ventas confirmadas del turno abierto en tu local.
3. Tocá la venta que querés anular.
4. Leé el aviso: la devolución de dinero (si corresponde) la maneja aparte una supervisora o el dueño — anular acá solo revierte el stock, los puntos del cliente y la seña usada.
5. Marcá el casillero **"Entendido"** (obligatorio) y, si querés, escribí un motivo.
6. Tocá **"Anular venta"**.

> **Importante:** Desde el celular solo se pueden anular ventas del **turno que está abierto ahora mismo**. Si la venta es de un turno ya cerrado, el sistema la rechaza — pedile a una supervisora o al dueño que la anule desde la computadora, donde no tienen ese límite.

---

## Vista desktop (supervisores y dueños)

### Listado de ventas

Accedé desde el sidebar: **Ventas**.

La tabla muestra todas las ventas con sus columnas principales: número, fecha, local, vendedora, total y estado.

#### Filtros disponibles

| Filtro | Cómo funciona |
|---|---|
| Número | Busca por número exacto o parcial |
| Estado | Dropdown: todas / confirmada / anulada |
| Fecha desde / hasta | Rango de fechas |
| Local | Filtra por punto de venta (si tenés acceso a varios) |

Tocá **Buscar** para aplicar los filtros, y **Limpiar filtros** para resetearlos.

#### Ver detalle de una venta

Hacé clic en el ícono de ojo (👁) en la fila. Se abre un panel lateral con:

- Datos de cabecera: número, fecha, vendedora, local.
- Ítems vendidos: descripción, variante, cantidad, precio unitario, descuento, total.
- Medios de pago usados.
- Historial de cambios (si fue anulada).

#### Anular una venta

Solo disponible para usuarios con permiso de anulación. Supervisoras y dueños pueden anular **cualquier** venta, sin límite de fecha ni de turno — a diferencia de las vendedoras, que desde el celular solo anulan ventas del turno actual (ver "Anular una venta desde el celular" más arriba).

1. Abrí el detalle de la venta.
2. Hacé clic en **"Anular"**.
3. Seleccioná el motivo.
4. Confirmá.

> La anulación **devuelve el stock** al local. No modifica el turno de caja.

---

## Cambios de producto

### ¿Para qué sirve?

Permite que un cliente devuelva uno o varios productos y se lleve otros distintos, calculando automáticamente cuánto hay que cobrarle o reconocerle de diferencia. Se accede desde la tarjeta o el menú **"Cambios"**, tanto en el celular del local como en la computadora.

### Los cuatro tipos de cambio

| Tipo | Cuándo se usa | Qué hace falta |
|---|---|---|
| Cambio común | El cliente trae un producto de una compra normal | El código de cambio del ticket |
| Cambio de promoción | El producto devuelto se compró en una promo (2x1, 3x2) | El código de cambio del ticket |
| Cambio por falla | El producto está fallado y no hay ticket a mano | Elegir un **autorizador** de la lista |
| Gift card física | El cliente canjea una gift card de cartón/plástico | El código de cambio del ticket |

> **Importante:** El código de cambio es el que el sistema generó al confirmar la venta original (8 caracteres, se lo llevó el cliente impreso en el ticket). Vence a los 30 días — si pasó ese plazo, el sistema avisa pero **no bloquea**: se puede seguir igual.

### Paso a paso

1. Elegí el **tipo de cambio**.
2. Si es común, de promoción o gift card: ingresá el **código de cambio** del ticket.
   Si es por falla: elegí de la lista quién **autoriza** el cambio (ver más abajo quién puede aparecer ahí).
3. Indicá qué producto(s) devuelve el cliente, buscándolos por código o nombre.
4. Indicá qué producto(s) nuevo(s) se lleva, de la misma forma.
5. El sistema muestra la **diferencia**:
   - Si el cliente se lleva algo más caro, paga la diferencia con el medio de pago que elijas.
   - Si se lleva algo más barato, la diferencia queda **a favor del cliente pero no se le devuelve en dinero** — puede usarla para llevarse más productos en el momento, o la pierde.
6. Confirmá. El sistema entrega un **código de cambio nuevo** para los productos que se lleva, por si en el futuro los quiere cambiar también.

### Cómo se calcula lo que vale el producto devuelto

- **Cambio común**: se reconoce el precio de lista al momento de la compra original (no lo que el cliente pagó con descuentos).
- **Cambio de promoción**: se reconoce un porcentaje del precio de lista, según si el producto nuevo es del mismo material que el devuelto:

  | Promo original | Mismo material | Otro material |
  |---|---|---|
  | 2x1 | 100% | 50% |
  | 3x2 | 100% | 66% |

  *Ejemplo:* un anillo de plata de $10.000 comprado en una promo 2x1 se cambia por una cadena de plata (mismo material): se reconocen $10.000. Si en cambio se cambia por algo de oro (otro material), se reconocen $5.000.
- **Cambio por falla** y **gift card física**: se reconoce el precio de venta **actual** del producto, sin importar cuánto costaba antes.

### El autorizador del cambio por falla

Como un cambio por falla no tiene ticket, alguien tiene que responsabilizarse de aprobarlo. Por eso se elige de una lista de personas habilitadas como **"Autorizador de cambios"** — esa lista la administra la Cuenta Maestra desde el módulo de Usuarios (ver el manual de Usuarios y Roles). Si no aparece nadie en la lista, avisale a la Cuenta Maestra para que habilite al menos una persona.

---

## Preguntas frecuentes

**¿Puedo vender si no hay turno abierto?**
No. El sistema requiere un turno activo para registrar ventas.

**¿Qué pasa si se va la señal de internet mientras cobro?**
La venta queda guardada como "en curso" hasta que vuelva la conexión.

**¿Puedo cambiar el medio de pago después de confirmar?**
No. Las ventas confirmadas solo se pueden anular y volver a registrar.

**¿Puedo anular desde el celular una venta de ayer?**
Solo si el turno de ayer sigue abierto (no se cerró). Si ya se cerró el turno, esa venta solo la puede anular una supervisora o el dueño desde la computadora.

**¿Qué pasa si el cambio de un producto tarda varios días y el precio subió?**
Para cambio común y de promoción no importa: se reconoce el precio de lista **del día de la compra original**. Para cambio por falla y gift card física sí importa, porque ahí se usa el precio **actual**.

**¿El cliente puede pedir que le devuelvan la diferencia en efectivo si le queda a favor?**
No. Si la diferencia queda a favor del cliente, se la puede usar para llevarse más productos en el momento, pero no se devuelve en dinero.
