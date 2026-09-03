#!/usr/bin/env python3
"""
Compila los manuales de usuario en Markdown a PDF.

Uso:
    python compilar_pdf.py           # compila todos los manuales
    python compilar_pdf.py 01        # compila solo el que empieza con "01"

Los PDF se generan en docs/manuales/pdfs/.
Requiere: markdown, weasyprint (ya incluidos en requirements.txt).
"""

import sys
from pathlib import Path

import markdown
from weasyprint import HTML

BASE = Path(__file__).parent
PDFS = BASE / "pdfs"
PDFS.mkdir(exist_ok=True)

# Estilos básicos para el PDF
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@300;400;500;600;900&display=swap');

body {
    font-family: 'Archivo', Arial, sans-serif;
    font-size: 14px;
    line-height: 1.6;
    color: #000;
    max-width: 800px;
    margin: 0 auto;
    padding: 40px 50px;
}

h1 {
    font-size: 28px;
    font-weight: 900;
    color: #0073e3;
    border-bottom: 3px solid #0073e3;
    padding-bottom: 8px;
    margin-bottom: 24px;
}

h2 {
    font-size: 20px;
    font-weight: 600;
    color: #353737;
    margin-top: 32px;
    margin-bottom: 12px;
    border-bottom: 1px solid #f0f0f0;
    padding-bottom: 4px;
}

h3 {
    font-size: 16px;
    font-weight: 600;
    color: #353737;
    margin-top: 20px;
    margin-bottom: 8px;
}

h4 {
    font-size: 14px;
    font-weight: 600;
    margin-top: 16px;
    margin-bottom: 6px;
}

p {
    margin-bottom: 10px;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0;
    font-size: 13px;
}

th {
    background: #0073e3;
    color: #fff;
    font-weight: 600;
    padding: 8px 12px;
    text-align: left;
}

td {
    padding: 7px 12px;
    border-bottom: 1px solid #f0f0f0;
}

tr:nth-child(even) td {
    background: #f0f0f0;
}

blockquote {
    background: #f0f0f0;
    border-left: 4px solid #0073e3;
    margin: 16px 0;
    padding: 12px 16px;
    border-radius: 0 5px 5px 0;
    font-size: 13px;
    color: #353737;
}

blockquote p {
    margin: 0;
}

code {
    background: #f0f0f0;
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 12px;
    font-family: 'Courier New', monospace;
}

pre {
    background: #f0f0f0;
    padding: 12px 16px;
    border-radius: 5px;
    overflow-x: auto;
    font-size: 12px;
}

ul, ol {
    padding-left: 20px;
    margin-bottom: 10px;
}

li {
    margin-bottom: 4px;
}

hr {
    border: none;
    border-top: 1px solid #f0f0f0;
    margin: 24px 0;
}

@page {
    size: A4;
    margin: 20mm 15mm;
    @bottom-right {
        content: counter(page) " / " counter(pages);
        font-size: 11px;
        color: #737c7c;
    }
}
"""


def compilar_archivo(md_path: Path) -> Path:
    """Convierte un archivo .md en PDF y lo guarda en pdfs/."""
    texto = md_path.read_text(encoding="utf-8")
    html_body = markdown.markdown(texto, extensions=["tables", "fenced_code"])
    html_completo = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<style>{CSS}</style>
</head>
<body>
{html_body}
</body>
</html>"""

    pdf_path = PDFS / md_path.with_suffix(".pdf").name
    HTML(string=html_completo, base_url=str(BASE)).write_pdf(str(pdf_path))
    return pdf_path


def main():
    filtro = sys.argv[1] if len(sys.argv) > 1 else None

    archivos = sorted(BASE.glob("*.md"))
    if filtro:
        archivos = [f for f in archivos if f.name.startswith(filtro)]

    if not archivos:
        print(f"No se encontraron archivos{' que empiecen con ' + filtro if filtro else ''}.")
        sys.exit(1)

    for md_path in archivos:
        print(f"Compilando {md_path.name}...", end=" ", flush=True)
        try:
            pdf_path = compilar_archivo(md_path)
            print(f"OK → {pdf_path.name}")
        except Exception as e:
            print(f"ERROR: {e}")

    print(f"\n✓ PDFs generados en {PDFS}/")


if __name__ == "__main__":
    main()
