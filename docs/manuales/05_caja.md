# Manual de usuario — Caja y Turnos

## ¿Para qué sirve este módulo?

El módulo de Caja gestiona los turnos de trabajo del local, los retiros de efectivo y el arqueo al cierre del día. Sin turno abierto no se pueden registrar ventas.

---

## Turnos de trabajo

### ¿Qué es un turno?

Un turno es el período en que el local está operativo. Registra quién abrió la caja, con cuánto efectivo, y quiénes trabajaron durante el día. Al cerrar, genera el arqueo automáticamente.

### Iniciar un turno

Desde la pantalla de inicio del celular del local:

1. Tocá el área del turno (muestra "Sin turno activo").
2. Se abre el panel de apertura.
3. Ingresá el **efectivo inicial en caja** (el dinero físico que hay al abrir).
4. Tocá **"Confirmar"**.

El turno queda abierto y podés empezar a vender.

### Unirte a un turno ya abierto

Si otra vendedora abrió el turno antes que vos:

1. Tocá el área del turno.
2. El panel muestra quién lo abrió y a qué hora.
3. Tocá **"Unirme al turno"**.

Quedás registrada como parte del turno sin modificar el efectivo inicial.

### Turno del día anterior sin cerrar

Si el turno anterior quedó abierto, el sistema **bloquea todas las operaciones** hasta cerrarlo. Aparece un aviso en rojo en la pantalla de inicio.

> Cerrá siempre el turno al terminar el día.

---

## Retiros de efectivo

Un retiro registra cuando se saca dinero de la caja antes del cierre (por ejemplo, para depositar en el banco o hacer un pago).

### Registrar un retiro

Requiere permiso de retiro de caja.

1. En el turno activo, buscá la opción **"Retiro de efectivo"**.
2. Ingresá el **monto** a retirar.
3. Seleccioná el **motivo** del retiro.
4. Si el retiro requiere autorización, indicá quién lo autorizó.
5. Confirmá.

El retiro queda registrado en el turno y se descuenta del efectivo esperado en el arqueo.

---

## Novedades de caja

Una novedad registra plata que entra o sale de la caja y que no es una venta ni un retiro de efectivo (por ejemplo, un pago a un proveedor en el momento o un ingreso extra). Si es una entrada o una salida lo define el **concepto** que elijas: se muestra en pantalla, pero no se edita.

### Registrar una novedad

Requiere permiso de caja y un turno abierto en el local.

1. En el celular, desde la pantalla de inicio, tocá **"Operaciones de caja"** y después **"Novedad"**.
2. Elegí el **concepto**.
3. Ingresá el **monto**.
4. En **"Autorizó"**, elegí de la lista quién aprobó el movimiento.
5. Si querés, agregá **notas**.
6. Tocá **"Registrar novedad"**.

### ¿Quiénes aparecen en "Autorizó"?

Los usuarios **activos** que la Cuenta Maestra habilitó como **"Autorizador de cambios y novedades de caja"** desde Configuración → Usuarios. Es la misma lista que se usa para autorizar los cambios por falla. El paso a paso para habilitar a alguien está en el manual de Usuarios y Roles, en la sección *"Autorizador de cambios y novedades de caja"*.

---

## Movimientos de caja (celular)

Muestra todo lo que entró y salió de la caja en cada turno del día, para controlar el recorrido antes de cerrar. Requiere permiso de caja.

1. En el celular, tocá **"Caja"** en la barra inferior.
2. Elegí el **día** (por defecto, hoy).

Cada turno aparece como una tarjeta con su horario y tres secciones bien separadas:

- **Saldo inicial**: el efectivo con el que se abrió la caja, con la hora de apertura. Va aparte y en negro (no en verde) porque no es una venta ni plata que entró durante el turno: es con lo que se arrancó.
- **Ventas y movimientos**: cada venta, seña, cobro de joyero, novedad y retiro de efectivo, en orden de hora, con su medio de pago. Los ingresos se ven en verde con "+", los egresos en rojo con "−". La parte de una venta pagada con seña aparece en gris con la leyenda *"no suma"*, porque esa plata ya entró cuando se dejó la seña.
- **Totales**: lo que entró y salió durante el turno, **sin el saldo inicial**:
  - Una **barra de colores** que muestra qué parte de los ingresos entró por cada medio de pago.
  - Debajo, la lista de **ingresos por medio de pago** (efectivo, tarjetas, transferencias, etc.), de mayor a menor, cada uno con su color. Cada medio tiene siempre el mismo color, en cualquier turno o día.
  - **Ingresos del turno** (la suma de los medios), **egresos del turno** y, destacado abajo, el **efectivo esperado en caja**, que es lo que tendría que dar el arqueo al cerrar.

> Los ingresos del turno **no** incluyen el saldo inicial (se ve aparte, arriba). El **efectivo esperado en caja** sí lo incluye, porque es toda la plata que tiene que haber en la caja. Lo pagado con seña tampoco suma en los ingresos: esa plata ya entró el día que se dejó la seña.

### Ver el detalle de una venta

Las ventas de la lista tienen una flechita (›): tocá una para abrir su detalle. Se abre un panel desde abajo con:

- Número de venta, fecha y hora, cliente (si tiene) y promoción aplicada.
- Los **productos**, igual que en el carrito: descripción, categoría y código (SKU), promoción o descuento con su motivo, y el precio final (con el de lista tachado si hubo descuento).
- **Subtotal**, **descuentos y promociones**, **recargo por cuotas** (si hubo) y **total**.
- Los **pagos**: cada medio de pago con su monto y las cuotas, si las hubo.
- El **código de cambio** (tachado si ya se usó) y los **puntos sumados**.

Para cerrarlo tocá la **✕**. Es solo de consulta: desde acá no se modifica la venta.

> Para ver el detalle hace falta también permiso de **Ventas** para ver. Las señas, novedades, retiros y cobros de joyero no tienen detalle.

---

## Cierre de turno y arqueo

El cierre del turno incluye un **arqueo de caja**: comparación entre lo que el sistema esperaba recaudar y lo que la vendedora declara que hay físicamente.

### Cerrar el turno

1. En la pantalla de inicio, tocá **"Cerrar turno"** (o el área del turno).
2. Se abre la pantalla de arqueo.
3. El sistema muestra el **monto esperado** por cada medio de pago, calculado a partir de las ventas del turno.
4. Para cada medio, ingresá el **monto que contás físicamente**:
   - Efectivo: contá los billetes.
   - Tarjetas / transferencias: el sistema muestra el total esperado como referencia (son informativos, no se ingresan manualmente).
5. El sistema calcula automáticamente la **diferencia** (monto declarado − monto esperado).
6. Tocá **"Confirmar cierre"**.

El turno queda cerrado y el arqueo queda registrado.

### ¿Qué pasa con las diferencias?

Las diferencias (sobrante o faltante) quedan registradas en el sistema para revisión del supervisor o dueño. No se ajustan automáticamente.

---

## Vista desktop — Listado de turnos

Accedé desde el sidebar: **Caja**.

La tabla muestra todos los turnos con:

| Columna | Qué muestra |
|---|---|
| Fecha | Fecha y hora de apertura |
| Local | Punto de venta |
| Quien abrió | Usuario que inició el turno |
| Estado | Abierto / Cerrado |

### Ver el detalle de un turno

Hacé clic en el ícono de ojo (👁) para ver:

- Lista de vendedoras que participaron.
- Retiros de efectivo registrados.
- Resultado del arqueo: esperado vs. declarado por medio de pago, y diferencias.

---

## Preguntas frecuentes

**¿Puedo vender sin turno?**
No. El sistema requiere un turno activo para registrar ventas.

**¿Varias vendedoras pueden trabajar en el mismo turno?**
Sí. Cada una se une al turno con "Unirme al turno". Todas las ventas quedan registradas bajo el mismo turno del día.

**¿Qué pasa si me equivoco en el efectivo inicial?**
Una vez confirmado no se puede cambiar. El sistema registra el monto declarado al abrir; si hubo un error, anotalo en las notas del turno.

**¿El arqueo ajusta el stock o las ventas?**
No. El arqueo solo registra las diferencias de caja. No modifica ningún otro dato.

**¿Por qué no aparece nadie en "Autorizó" al cargar una novedad?**
Porque no hay ningún usuario activo habilitado como autorizador, o porque tu usuario no tiene permiso de Ventas para crear. Pedile a la Cuenta Maestra que habilite al menos a una persona (manual de Usuarios y Roles) o que revise tus permisos.

**¿Puedo ver el arqueo de otro local?**
Solo si tenés permiso de supervisor o superior. Las vendedoras solo ven el turno de su propio local.
