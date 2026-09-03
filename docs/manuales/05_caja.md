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

**¿Puedo ver el arqueo de otro local?**
Solo si tenés permiso de supervisor o superior. Las vendedoras solo ven el turno de su propio local.
