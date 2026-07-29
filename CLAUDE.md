# CLAUDE.md — Proyecto Soleil/Mallorca

Este archivo se carga automáticamente al inicio de cada sesión de Claude Code.
Contiene el contexto completo del proyecto y los principios de arquitectura
que rigen todo el desarrollo. No hace falta incluirlo manualmente en cada
sesión: Claude Code lo lee solo.

Para el prompt específico de cada módulo, usar el comando `/file`:
```
/file prompts/01_infraestructura.md
/file prompts/02_auth_usuarios.md
... etc.
```

---

# CONTEXTO DEL PROYECTO: Soleil/Mallorca

Eres un desarrollador full-stack senior especializado en aplicaciones de
gestión empresarial para PyMEs. Estás desarrollando un ERP moderno que
reemplaza soluciones como Tango Gestión o Flexxus, priorizando la experiencia
de usuario sobre la cantidad de funciones.

## STACK TECNOLÓGICO
- Backend: Python con FastAPI
- Frontend: HTMX + Alpine.js + Jinja2 (servido desde FastAPI)
- Estilos: Tailwind CSS vía CDN (sin build process)
- Base de datos: PostgreSQL
- ORM: SQLAlchemy con Alembic para migraciones
- Autenticación: JWT con refresh tokens
- Reportes: WeasyPrint (PDF) y openpyxl (Excel)
- Containerización: Docker + docker-compose

---

## PRINCIPIO 1: API-FIRST

- La API REST es el contrato principal del sistema; el frontend es un
  consumidor más, no una extensión del backend.
- Cada módulo se diseña primero como endpoints versionados (`/api/v1/...`)
  con su esquema Pydantic de request/response, documentados en OpenAPI,
  antes de tocar el frontend correspondiente.
- Ningún endpoint devuelve datos formateados para una vista particular
  (strings en pesos, fechas localizadas, textos armados para mostrar).
  La API devuelve datos crudos y tipados; la presentación vive en el frontend.
- Cada endpoint debe ser 100% testeable desde Swagger o curl sin que
  exista el frontend.
- Las reglas de negocio y validaciones críticas (stock, permisos, estados,
  cálculos) viven en `/services` del backend y se aplican siempre, sin
  importar qué cliente llama a la API.

---

## PRINCIPIO 2: NO REPETIR CÓDIGO (DRY)

- Si una misma lógica, estructura o bloque de estilos aparece más de una
  vez, se extrae a una única definición reutilizable.
- **Python:** funciones, clases o constantes compartidas van en `/services`,
  `/schemas` o `/app/core/utils.py`. Nunca copiar validaciones o cálculos
  entre módulos.
- **CSS/Tailwind:** estilos repetidos se extraen a clases utilitarias o
  variables en `tailwind.config.js`. No repetir combinaciones de clases
  largas en múltiples componentes.
- **Jinja2/HTML:** estructuras de UI repetidas (tablas, modales, formularios,
  badges) se extraen como macros reutilizables en `/templates/components/`,
  parametrizadas con argumentos de macro. Nunca copiar bloques HTML entre páginas.
- El criterio es: si cambiar una copia debería implicar cambiar todas,
  hay que unificarlas.

---

## PRINCIPIO 3: AUDITORÍA INMUTABLE

- Toda acción sensible se registra en una tabla `auditoria` de solo
  inserción (append-only). A nivel de base de datos, esa tabla no permite
  UPDATE ni DELETE — la garantía vive en la base de datos, no solo en el código.
- **Acciones sensibles incluyen:** altas, ediciones y anulaciones en cualquier
  módulo; cambios de precio (individuales y masivos); cambios del valor del
  dólar; cambios de stock manuales; cambios de permisos o roles; anulación
  de facturas; cobros y pagos; login y logout; retiros de efectivo de caja;
  cambios de PIN de ubicaciones; operaciones de la Cuenta Maestra.
- **Cada registro guarda:** `usuario_id` (o `"sistema"`), `accion`
  (ej. `"venta.anular"`), `entidad`, `entidad_id`, `timestamp` (UTC-03:00),
  `estado_anterior` y `estado_nuevo` en JSON (solo cuando modifica datos
  existentes), `ip_origen`.
- El registro de auditoría se escribe en la misma transacción que la acción
  que audita: si la acción falla no queda registro huérfano; si el registro
  falla, la acción no se confirma.
- Endpoint de solo lectura: `GET /api/v1/auditoria`, visible únicamente para
  Cuenta Maestra y Auditor, con filtros por usuario, módulo, entidad y fechas.
- La auditoría es distinta al historial de accesos del módulo de usuarios:
  son registros con propósitos diferentes.

---

## PRINCIPIO 4: ARQUITECTURA DE BASE DE DATOS

### Identificadores y claves primarias
- Toda tabla tiene una PK de tipo `BIGSERIAL` llamada `id`, salvo que
  se justifique explícitamente lo contrario con un comentario en el modelo.
- Las relaciones entre tablas se establecen siempre mediante ese `id`
  numérico como FK — nunca usar campos de negocio (CUIT, código de
  producto, número de factura) como FK aunque sean únicos.
- Los campos de negocio que deban ser únicos llevan su propio índice
  `UNIQUE`, independiente de la PK.

### Normalización (3FN pragmática)
- Las tablas siguen 3FN como regla general: sin dependencias transitivas,
  sin grupos repetidos.
- **Excepciones justificadas a 3FN** (desnormalización por integridad
  histórica o rendimiento):
  - Guardar `precio_unitario` y `descuento` en el detalle de ventas/compras,
    porque deben reflejar el precio al momento de la transacción.
  - Guardar `razon_social` o `cuit` en comprobantes fiscales por el mismo
    motivo.
  - Toda excepción debe estar comentada en el modelo SQLAlchemy explicando
    por qué se desnormalizó.
- Campos calculables (saldo de cliente, total de venta, stock actual) **no**
  se persisten en la base de datos salvo justificación de rendimiento
  documentada — se calculan en `/services` o con queries al momento de
  necesitarse.

---

## PRINCIPIO 5: FILTROS POR DEFECTO EN PANTALLAS DE CONSULTA

Toda pantalla de listado o ABM incluye filtros por defecto según el tipo
de dato de cada columna relevante:

- **VARCHAR/TEXT:** búsqueda de texto libre, insensible a mayúsculas y
  tildes (`ILIKE %valor%`).
- **ENUM:** selector desplegable con todas las opciones + "Todos" por defecto.
- **BOOLEAN:** selector "Todos / Sí / No", con "Todos" por defecto.
- **NUMERIC/DECIMAL:** rango "desde" / "hasta", ambos opcionales.
- **TIMESTAMP/DATE:** rango de fechas con calendario, ambos opcionales.

**Comportamiento estándar:**
- Tablas de alto volumen (ventas, movimientos): filtros con botón "Buscar"
  explícito. Tablas pequeñas (proveedores, clientes, productos): en tiempo real.
- Los filtros **no persisten** al navegar entre páginas.
- Siempre hay un botón "Limpiar filtros".
- El resultado muestra el total de registros encontrados.
- Todos los filtros se resuelven en el backend — nunca filtrar en el frontend
  sobre datos ya cargados.

**No generan filtro:** claves primarias (`id`), claves foráneas (`_id`),
campos de auditoría internos (`updated_at`, `password_hash`).

---

## Principio 6: de Frontend y Diseño Responsivo

### 1. Enfoque "Mobile-First" Obligatorio
* **Estrategia:** Diseña y escribe los estilos pensando primero en pantallas móviles pequeñas. Agrega complejidad y layouts para pantallas más grandes mediante media queries progresivas (`min-width`).
* **Regla:** Evita modificar layouts mediante `max-width` descendente a menos que sea estrictamente necesario para casos de borde.

### 2. Layouts Fluídos y Flexibles
* **Grillas y Contenedores:** Usa CSS Grid y Flexbox en lugar de posiciones absolutas o anchos fijos (`width: 500px`).
* **Unidades Relativas:** Prioriza el uso de unidades relativas (`rem`, `em`, `%`, `vw/vh`, `clamp()`) sobre unidades absolutas en píxeles (`px`) para tipografía, márgenes y paddings.
* **Ajuste Automático:** Utiliza propiedades como `grid-template-columns: repeat(auto-fit, minmax(280px, 1fr))` para contenedores de elementos repetitivos.

### 3. Manejo Riguroso de Breakpoints
* **Puntos de quiebre estándar:** Mantén consistencia utilizando una escala definida de breakpoints:
  * Mobile: `< 640px`
  * Tablet: `640px - 1023px`
  * Desktop: `1024px - 1279px`
  * Large Desktop: `>= 1280px`
* **Defensión contra Overflow:** Ningún componente debe generar scroll horizontal inadvertido (`overflow-x: hidden` a nivel global y manejo explicito de `max-width: 100%` en imágenes y media).

### 4. Criterio de Ejecución en Code Reviews/Generación
Antes de entregar o dar por finalizado un componente UI, verifica:
- ¿El componente se adapta limpiamente desde 320px de ancho hasta 1920px+?
- ¿Los elementos interactivos (botones, enlaces) mantienen un área de toque adecuada en pantallas táctiles (mínimo 44x44px)?
- ¿Se preserva la legibilidad tipográfica y la jerarquía visual en todos los tamaños?
---

## ARQUITECTURA Y ESTRUCTURA DE ARCHIVOS

```
/backend
  /app
    /api/v1       → routers por módulo, versionados
    /models       → modelos SQLAlchemy
    /schemas      → esquemas Pydantic (request/response, separados de models)
    /services     → lógica de negocio (válida para cualquier consumidor)
    /core         → utilidades transversales (permisos, auditoría, utils)
    /reports      → generación de PDF y Excel
  /migrations     → Alembic
  main.py
  config.py

/frontend — no existe como proyecto separado. FastAPI sirve el HTML.
/backend/app
  /templates/
    base.html             → layout principal (sidebar, header)
    /components/          → macros Jinja2 reutilizables
      table.html          → macro tabla con paginación y filtros
      modal.html          → macro modal de confirmación
      form_field.html     → macro campo de formulario
      toast.html          → macro notificaciones
      badge.html          → macro badge de estado
    /pages/               → una carpeta por módulo
  /static/
    /css/custom.css       → estilos complementarios a Tailwind
    /js/app.js            → funciones JavaScript globales (shortcuts, utils)
```

## DESIGN SYSTEM (extraído de Figma — archivo Soleil)

Los tokens a continuación son los valores reales del diseño. Usarlos
siempre — no inventar colores, tipografías ni estilos fuera de esta escala.

### Tipografía
- **Familia:** Archivo (Google Fonts) — única familia en todo el sistema
- **Pesos usados:** Light (300), Medium (500), SemiBold (600), Black (900)
- **Tamaños:**
  - xs: 14px (texto secundario, badges, labels de tabla)
  - sm: 15px (texto de apoyo, metadatos)
  - base: 18px (texto de cuerpo, filas de tabla, labels de campo)
  - lg: 22px (ítems de sidebar, títulos de sección)
  - xl: 30px (subtítulos de página)
  - 2xl: 60px (título "Bienvenido" en dashboard)
- **Variación:** `font-variation-settings: 'wdth' 100` en todos los textos

### Colores

**Sidebar / panel izquierdo:**
- Fondo sidebar: `#0073e3` (azul primario — color más importante del sistema)
- Texto sidebar activo: `#ffffff`
- Texto sidebar inactivo: `#ffffff` (mismo, sin distinción en el diseño actual)

**Contenido principal:**
- Fondo general: blanco `#ffffff`
- Título de bienvenida: `#5f8ab4` (azul grisáceo)
- Texto principal: `#000000`
- Texto secundario / muted: `#353737`
- Texto deshabilitado / placeholder: `#bcbec0`
- Texto de headers de tabla: `#737c7c`

**Estados:**
- Pendiente / error: `#f60509` (rojo)
- Autorizado / éxito: `#00bf29` (verde)
- Activo (badge): fondo `#557eaa`, texto `#ffffff` (azul medio)

**Inputs y tarjetas:**
- Fondo input / fila alternada: `#f0f0f0`
- Borde de inputs y tarjetas: `#f0f0f0`
- Border radius inputs: `5px`
- Border radius badges / pills: `15px`
- Border radius botones: `5px`

**Botones:**
- Botón primario (Continuar, Procesar, Crear, Finalizar):
  fondo `#0073e3`, texto `#ffffff`, alto 35px, border-radius 5px
- Botón secundario (Editar): borde visible, texto oscuro
- Botón Ver: icono visual sin fondo
- Botón Borrar: icono papelera sin fondo

**Navbar / header superior:**
- Fondo buscador: borde `#f0f0f0`, border-radius `25px`
- Badge de usuario logueado: fondo `#557eaa`, texto `#ffffff`,
  border-radius `15px`, padding horizontal generoso

### Layout
- **Ancho total:** 1440px (desktop)
- **Sidebar:** 290px de ancho, fondo `#0073e3`, altura completa
- **Área de contenido:** desde x=358px, padding interno desde los bordes
- **Header superior:** altura ~95px, contiene logo (izquierda) +
  buscador central + badge de usuario (derecha)


### Estructura del sidebar
De arriba hacia abajo (con íconos + texto):
1. Logo en la parte superior
2. Home
3. Usuarios / Productos / etc. (según el rol)
4. Configuración
5. (módulos adicionales según rol)
6. Ajustes (pegado al fondo del sidebar)

### Componentes recurrentes

**Tabla de listado:**
- Header con fondo `#0073e3` o `#f0f0f0` (varía por pantalla)
- Filas alternadas: blanco y `#f0f0f0`
- Borde de fila: `#f0f0f0`, border-radius `5px`
- Columnas separadas por líneas verticales sutiles
- Acciones por fila: botones "Ver" + "Editar" + "Borrar" alineados a la derecha
- Texto de estado coloreado inline (sin badge box): rojo para pendiente,
  verde para autorizado/activo

**Filtros de búsqueda:**
- Inputs horizontales en fila, fondo `#f0f0f0`, border-radius `5px`
- Dropdowns con chevron (▼) a la derecha
- Botón "+ Crear nuevo" en el extremo derecho de la fila de filtros

**Formularios:**
- Labels en texto 18px medium, encima del input
- Inputs: fondo blanco, borde `#f0f0f0`, alto 40px, border-radius `5px`
- Layout en grilla de 2-4 columnas según el ancho disponible
- Botón de acción principal alineado abajo a la derecha

**Modal / panel flotante:**
- Fondo de la card: blanco, borde sutil
- Header del modal: badge de estado (izquierda) + fecha (derecha)
- Botones Autorizar / Denegar en fila al pie del modal
- Botón cerrar (×) en esquina superior derecha

### UX general
- Tablas con paginación, búsqueda y exportación a Excel/PDF
- Feedback visual en todas las acciones (toasts de éxito/error)
- Confirmación antes de eliminar o anular registros
- Campos obligatorios claramente marcados
- Shortcuts en punto de venta: F2 buscar, F10 confirmar, ESC cancelar
- Modo oscuro: estructurar con CSS variables desde el arranque para
  facilitar la inversión de colores cuando se implemente

## RESTRICCIONES GENERALES

- Sin dependencias de servicios externos de pago (todo self-hosted)
- Priorizar que funcione bien sobre que tenga muchas funciones
- Código comentado en español
- Cada módulo debe poder desarrollarse y probarse de forma independiente

