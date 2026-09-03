# Manual de usuario — Usuarios y Roles

## ¿Para qué sirve este módulo?

El módulo de Usuarios y Roles permite dar de alta a las personas que usan el sistema, asignarles un rol y ajustar sus permisos individuales si es necesario.

Accedé desde el sidebar: **Usuarios**.

---

## Roles del sistema

Cada usuario tiene un **rol** que define qué puede ver y qué puede hacer. Los roles base del sistema son:

| Rol | Descripción |
|---|---|
| Cuenta Maestra | Acceso total. Gestiona roles, configuración y todo lo demás. |
| Supervisor | Acceso amplio: ventas, stock, compras, usuarios. Sin configuración de medios de pago. |
| Vendedora | Registra ventas en el local. Acceso limitado. |
| Depósito | Gestiona movimientos de stock y remitos en el Centro de Distribución. |

> La Cuenta Maestra puede crear roles adicionales desde **Configuración → Roles**.

---

## Listado de usuarios

La tabla muestra todos los usuarios del sistema.

### Filtros disponibles

| Filtro | Cómo funciona |
|---|---|
| Nombre | Búsqueda parcial en nombre completo |
| Usuario | Búsqueda parcial en nombre de usuario |
| Email | Búsqueda parcial en email |
| Rol | Filtra por rol asignado |
| Local | Filtra por punto de venta asignado |
| Estado | Todos / Activos / Inactivos |

---

## Dar de alta un usuario

1. Hacé clic en **"+ Nuevo usuario"**.
2. Completá el formulario:

### Campos del formulario

| Campo | Obligatorio | Descripción |
|---|---|---|
| Nombre completo | Sí | Nombre que aparece en el sistema |
| Usuario (username) | Sí | Nombre de inicio de sesión |
| Contraseña | Sí | Contraseña inicial (el usuario puede cambiarla) |
| Rol | Sí | Rol que define los permisos base |
| Email | No | Para notificaciones |
| Fecha de nacimiento | No | Opcional, informativo |
| Celular | No | Opcional, informativo |
| Punto de venta asignado | No | Local donde trabaja (necesario para vendedoras) |

3. Hacé clic en **"Crear"**.

> Si el usuario va a trabajar en un local específico, **asignale el punto de venta**. Sin esta asignación, el sistema no sabe a qué local pertenece y no puede abrir turnos ni ver stock del local.

---

## Editar un usuario

1. En el listado, hacé clic en el ícono de edición ✏️.
2. Modificá los campos necesarios.
3. Guardá los cambios.

> No se puede cambiar el nombre de usuario (username). Si hace falta cambiarlo, crear un nuevo usuario.

---

## Activar y desactivar usuarios

Un usuario inactivo no puede iniciar sesión.

- **Desactivar**: en el listado, usá el switch de Estado de la fila.
- El usuario mantiene todo su historial; solo pierde acceso al sistema.

---

## Permisos individuales

Cada usuario hereda los permisos de su rol. Si necesitás ajustar permisos para una persona en particular sin cambiarle el rol:

1. Abrí el detalle del usuario (ícono de ojo 👁).
2. Hacé clic en **"Permisos"**.
3. Ves el árbol de permisos: para cada módulo, podés ver si el permiso viene del rol o si está sobreescrito individualmente.
4. Activá o desactivá los permisos que necesitás ajustar.
5. Hacé clic en **"Guardar"**.

Los cambios individuales tienen prioridad sobre los del rol.

### Qué tipos de permiso hay

Por módulo, se puede configurar:

| Permiso | Qué permite |
|---|---|
| Ver | Consultar y leer datos del módulo |
| Crear | Dar de alta registros nuevos |
| Editar | Modificar registros existentes |
| Eliminar | Borrar o anular registros |

Algunos módulos tienen **permisos específicos** adicionales, como autorizar retiros de caja o confirmar cambios de precio.

---

## Historial de accesos

Podés ver cuándo y desde dónde inició sesión cada usuario:

1. Abrí el detalle del usuario.
2. Hacé clic en **"Historial de accesos"**.
3. Filtrá por fecha o resultado (exitoso / fallido).

---

## Gestión de roles (Cuenta Maestra)

Solo la Cuenta Maestra puede crear y editar roles.

Accedé desde **Configuración → Roles**.

### Crear un rol

1. Hacé clic en **"+ Nuevo rol"**.
2. Ingresá nombre y descripción.
3. Hacé clic en **"Crear"**.

El rol nuevo arranca **sin ningún permiso**. Hay que configurarlos antes de asignarlo.

### Configurar los permisos de un rol

1. En el listado de roles, hacé clic en **"Permisos"**.
2. Se muestra el árbol de módulos y recursos.
3. Activá los permisos que debe tener el rol.
4. Hacé clic en **"Guardar"**.

### Desactivar un rol

Los roles no se pueden borrar si tienen usuarios asignados. Se desactivan para que no se puedan asignar a nuevos usuarios.

---

## Preguntas frecuentes

**¿Puedo asignar el mismo usuario a varios locales?**
No. Cada usuario tiene un único local asignado. Si trabaja en varios locales, necesita un usuario por local.

**¿Qué pasa si desactivo a un usuario con turno abierto?**
El turno queda abierto hasta que alguien con permiso lo cierre. El usuario desactivado no puede hacer nada más.

**¿Puedo borrar un usuario?**
No. Los usuarios se desactivan para preservar el historial de ventas y acciones. Un usuario desactivado no puede iniciar sesión.

**¿Qué es la Clave Especial?**
La Cuenta Maestra tiene una clave especial separada de la contraseña de login. Se usa para autorizar operaciones críticas desde el sistema. Solo la Cuenta Maestra la tiene.
