# Soleil / Mallorca — ERP

ERP para PyME: gestión de productos, stock, ventas, facturación y tesorería.
Backend FastAPI + PostgreSQL; el frontend (HTMX + Alpine.js + Jinja2) se sirve
desde el mismo backend, sin build process ni node_modules.

Estado: **sesiones 01 y 02 completas**.

- **01 — Infraestructura:** estructura, PostgreSQL, auditoría inmutable,
  layout del frontend con modo claro/oscuro.
- **02 — Autenticación y usuarios:** login con JWT, sistema de permisos por
  rol con overrides individuales, ABM de roles y usuarios, árbol de permisos,
  historial de accesos y consulta de auditoría.

---

## 1. Requisitos previos

| Herramienta      | Versión mínima | Verificar con              |
|------------------|----------------|----------------------------|
| Docker           | 24             | `docker --version`         |
| Docker Compose   | v2             | `docker compose version`   |
| Git              | cualquiera     | `git --version`            |

No hace falta Python ni Node instalados en la máquina: todo corre en contenedores.

---

## 2. Clonar y configurar

```bash
git clone <url-del-repo> soleil
cd soleil
cp .env.example .env
```

Editar `.env` si hace falta. Para desarrollo local los valores por defecto
funcionan tal cual. **Antes de producción**, cambiar como mínimo:

```bash
# Generar un secreto JWT nuevo
openssl rand -hex 32
```

y pegarlo en `JWT_SECRET`, además de cambiar `POSTGRES_PASSWORD`.

---

## 3. Levantar el entorno

```bash
docker compose up --build
```

Levanta dos servicios:

| Servicio  | Qué es                                | Puertos          |
|-----------|---------------------------------------|------------------|
| `db`      | PostgreSQL 15 con volumen persistente | 5432             |
| `backend` | FastAPI + Uvicorn (`--reload`)        | 8000 (dev), 80   |

No hay servicio `frontend`: FastAPI sirve el HTML con Jinja2 en el mismo proceso.

> **Si algún puerto ya está ocupado** (`failed to bind host port ... address
> already in use`), no hace falta tocar el `docker-compose.yml`: los puertos
> que se publican en el host se configuran desde `.env`.
>
> ```bash
> POSTGRES_PORT_HOST=5433   # si ya tenés PostgreSQL local
> BACKEND_PORT_HOST=8010    # si el 8000 está tomado por otro proyecto
> BACKEND_PORT_PROD=8080    # si el 80 está tomado
> ```
>
> El puerto interno del contenedor sigue siendo 8000 siempre. Para ver qué
> está ocupando un puerto: `ss -tlnp | grep :8000`.

El código está montado como volumen: **editar un archivo `.py` recarga el
servidor solo**, sin rebuild.

---

## 4. Migraciones y datos iniciales

Con los contenedores arriba, en otra terminal:

```bash
# Crear las tablas
docker compose exec backend alembic upgrade head

# Cargar los datos iniciales (idempotente: se puede correr varias veces)
docker compose exec -T db psql -U soleil -d soleil < backend/migrations/seed.sql
```

El seed carga:

- La fila de `configuracion_sistema` con los valores por defecto
- Los motivos de baja: Rotura, Robo, Muestra, Merma
- Los 6 roles del sistema y sus permisos base
- El usuario Cuenta Maestra (`admin`)

Es idempotente: se puede correr las veces que haga falta sin duplicar nada.

### Crear una migración nueva

```bash
docker compose exec backend alembic revision --autogenerate -m "descripcion"
docker compose exec backend alembic upgrade head
```

Los modelos nuevos tienen que estar importados en `backend/app/models/__init__.py`,
si no Alembic no los detecta.

---

## 5. URLs de acceso

> Las URLs usan el puerto por defecto (8000). Si cambiaste `BACKEND_PORT_HOST`
> en el `.env`, reemplazá el puerto en todas.

| Qué                    | URL                                    |
|------------------------|----------------------------------------|
| Dashboard              | http://localhost:8000/                 |
| Login                  | http://localhost:8000/login            |
| Swagger (API docs)     | http://localhost:8000/docs             |
| ReDoc                  | http://localhost:8000/redoc            |
| Healthcheck            | http://localhost:8000/api/v1/health    |
| Healthcheck + base     | http://localhost:8000/api/v1/health/db |
| Usuarios               | http://localhost:8000/usuarios         |
| Roles                  | http://localhost:8000/roles            |

---

## 6. Credenciales iniciales

| Usuario | Contraseña   | Rol            |
|---------|--------------|----------------|
| `admin` | `Admin1234!` | Cuenta Maestra |

El sistema obliga a cambiarla en el primer ingreso: mientras
`usuarios.ultimo_acceso` siga en NULL, el login redirige a
`/cambiar-password` y no deja entrar a ninguna otra pantalla.

> **Cambiar esta contraseña antes de exponer el sistema.**

### Los 6 roles del sistema

Se cargan con el seed, no se pueden eliminar ni renombrar, y el código los
referencia siempre por `roles.nombre` (nunca por id):

| Rol | Alcance |
|-----|---------|
| `cuenta_maestra` | Acceso total. Único usuario con clave especial. Solo puede existir uno |
| `dueno` | Gestión completa del negocio |
| `supervisor` | Operación diaria. Solo puede gestionar usuarios con rol `vendedor` |
| `vendedor` | Punto de venta |
| `distribucion` | Depósito, remitos y transferencias |
| `auditor` | Solo lectura de auditoría y reportes |

### Cómo funcionan los permisos

Todo el control de acceso pasa por **una sola función**:
`resolver_permiso()` en `app/core/permisos.py`. Ningún endpoint valida
acceso por su cuenta.

- Los permisos base son del **rol** (`rol_permisos`).
- Cada usuario puede tener **overrides individuales** (`usuario_permisos`),
  siempre **aditivos**: `permiso_final = permiso_rol OR override`. Un
  override nunca quita un permiso.
- `recurso = NULL` significa acceso general al módulo; un recurso puntual
  (ej. `reporte.ventas_diarias`) habilita solo eso. Tener el módulo completo
  habilita sus recursos; tener un recurso NO habilita el módulo.

En un endpoint:

```python
@router.get("/reportes/ventas")
async def reporte(
    _=Depends(requiere_permiso(Modulo.REPORTES, "ver", Recurso.REPORTE_VENTAS_DIARIAS))
): ...
```

---

## 7. Estructura del proyecto

```
/backend
  main.py                  → app FastAPI: monta /api/v1 y las rutas HTML
  config.py                → variables de entorno tipadas (pydantic-settings)
  alembic.ini
  requirements.txt
  Dockerfile
  /app
    /api
      pages.py             → rutas que renderizan HTML
      /v1                  → routers de la API REST, uno por módulo
    /models                → modelos SQLAlchemy
    /schemas               → esquemas Pydantic (separados de los modelos)
    /services              → lógica de negocio (vale para cualquier consumidor)
    /core                  → database, auditoria, templates, utils
    /reports               → generación de PDF (WeasyPrint) y Excel (openpyxl)
    /templates
      base.html            → layout: sidebar + header
      /components          → macros Jinja2 reutilizables
      /pages               → una carpeta por módulo
      /auth
    /static                → css/custom.css (tokens del design system), js/app.js
  /migrations              → Alembic + seed.sql
docker-compose.yml
.env.example
```

---

## 8. Notas de arquitectura

Las reglas completas están en `CLAUDE.md`. Lo mínimo para trabajar acá:

- **La API es el contrato.** Los endpoints devuelven datos crudos y tipados;
  formatear importes y fechas es tarea del frontend.
- **Auditoría inmutable.** Toda acción sensible pasa por
  `registrar_auditoria()` (`app/core/auditoria.py`), en la misma transacción
  que la acción. La tabla `auditoria` tiene triggers que abortan cualquier
  UPDATE, DELETE o TRUNCATE: es append-only a nivel de base de datos.
- **DRY.** Estructuras de UI repetidas van como macro en
  `/templates/components/`; lógica compartida, en `/services` o
  `/core/utils.py`. Los colores viven una sola vez, como CSS variables en
  `static/css/custom.css`.
- **Modo oscuro.** Ya funciona. Se resuelve invirtiendo esas mismas variables
  bajo `.dark`; ningún template repite un color.
- **Zona horaria.** Usar siempre `app.core.utils.ahora()` (UTC-03:00), nunca
  `datetime.now()`.

### Verificar la inmutabilidad de la auditoría

```bash
docker compose exec db psql -U soleil -d soleil \
  -c "UPDATE auditoria SET accion = 'hack' WHERE id = 1;"
# ERROR: La tabla auditoria es de solo inserción (append-only): UPDATE no permitido
```

---

## 9. Tests

```bash
docker compose exec backend pytest
```

Corren contra una base PostgreSQL descartable (`soleil_test`) que se crea y
se migra sola: así se prueban también los triggers de inmutabilidad y los
UNIQUE, que con SQLite no existirían. Cada test corre en una transacción que
se revierte, así que el orden no importa y no ensucian la base de desarrollo.

---

## 10. Comandos útiles

```bash
docker compose up -d              # levantar en segundo plano
docker compose logs -f backend    # ver logs del backend
docker compose exec backend bash  # shell dentro del contenedor
docker compose exec db psql -U soleil -d soleil   # consola SQL
docker compose down               # bajar los servicios
docker compose down -v            # bajar y BORRAR la base de datos
```

---

## 11. Orden de las sesiones de desarrollo

Los prompts de cada módulo están en `/prompts`. Tienen dependencias entre sí:
no saltear el orden (ver `prompts/COMO_USAR.md`).
