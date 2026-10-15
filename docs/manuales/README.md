# Manuales de usuario

Documentación de usuario del sistema, organizada por módulo.

## Archivos

| Archivo | Módulo |
|---|---|
| `01_ventas.md` | Ventas (mobile y desktop) |
| `02_productos.md` | Productos, variantes, etiquetas |
| `03_stock.md` | Stock, movimientos, auditorías, remitos |
| `04_compras.md` | Compras a proveedores |
| `05_caja.md` | Turnos y arqueo de caja |
| `06_usuarios_roles.md` | Usuarios y roles |
| `07_configuracion.md` | Medios de pago, cuotas, descuentos, promociones |

## Compilar los PDFs

Los PDFs se generan con WeasyPrint **desde el host**, parado en la raíz del repo. No se puede hacer desde el contenedor del backend: ahí solo está montado `backend/` (en `/app`), y `docs/` no existe adentro.

Requiere `markdown` y `weasyprint` instalados en el Python del host (`pip install markdown weasyprint`).

```bash
# Compilar todos los manuales
python3 docs/manuales/compilar_pdf.py

# Compilar solo uno (por prefijo)
python3 docs/manuales/compilar_pdf.py 01
```

Los PDFs se guardan en `docs/manuales/pdfs/` (ignorado por git).

## Actualizar la documentación

Cuando cambia una funcionalidad:

1. Editá el archivo `.md` del módulo correspondiente.
2. Recompilá ese manual: `python3 docs/manuales/compilar_pdf.py XX` (donde `XX` es el número del módulo).
3. Commiteá solo el `.md` — los PDFs no van al repositorio.
