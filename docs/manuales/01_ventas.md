# Manual de usuario — Ventas

## ¿Para qué sirve este módulo?

El módulo de Ventas es el corazón del sistema. Desde acá se registran las ventas al cliente, se consulta el historial y se gestiona el turno del día. Tiene dos vistas: **desktop** para supervisores y dueños, y **mobile** para las vendedoras en el local.

---

## Vista mobile (celular del local)

### Pantalla de inicio

Al abrir la app desde el celular del local aparece la pantalla de inicio con:

- **Alerta de venta sin concluir**: si hay una venta abierta que no se terminó de cobrar, aparece en rojo arriba de todo. Tocala para retomar.
- **Estado del turno**: muestra si el turno está abierto o no.
- **Botón "Nueva venta"** (o "Seguir la venta" si hay una en curso).
- Accesos rápidos: consulta de stock, recepción de mercadería.

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

Solo disponible para usuarios con permiso de anulación.

1. Abrí el detalle de la venta.
2. Hacé clic en **"Anular"**.
3. Seleccioná el motivo.
4. Confirmá.

> La anulación **devuelve el stock** al local. No modifica el turno de caja.

---

## Preguntas frecuentes

**¿Puedo vender si no hay turno abierto?**
No. El sistema requiere un turno activo para registrar ventas.

**¿Qué pasa si se va la señal de internet mientras cobro?**
La venta queda guardada como "en curso" hasta que vuelva la conexión.

**¿Puedo cambiar el medio de pago después de confirmar?**
No. Las ventas confirmadas solo se pueden anular y volver a registrar.
