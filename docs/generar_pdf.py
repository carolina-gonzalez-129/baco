import sys
import os
import re
import html
import shutil
import subprocess
from pathlib import Path
import markdown_it

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DOCS_DIR = Path(__file__).resolve().parent
MD_PATH = DOCS_DIR / "ESPECIFICACION_TECNICA.md"
HTML_PATH = DOCS_DIR / "ESPECIFICACION_TECNICA.html"
PDF_PATH = DOCS_DIR / "ESPECIFICACION_TECNICA.pdf"
DOWNLOADS_DIR = Path.home() / "Downloads"
DOWNLOADS_PDF_PATH = DOWNLOADS_DIR / "BACO_Especificacion_Tecnica.pdf"

CHROME_PATHS = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]


def convertir_md_a_html(md_text: str) -> str:
    md = markdown_it.MarkdownIt("commonmark").enable("table").enable("strikethrough")
    html_content = md.render(md_text)

    # Reemplazar bloques de código mermaid para que mermaid.js los procese
    def fix_mermaid(match):
        code = html.unescape(match.group(1)).strip()
        return f'<div class="mermaid-container"><pre class="mermaid">\n{code}\n</pre></div>'

    html_content = re.sub(
        r'<pre><code class="language-mermaid">([\s\S]*?)</code></pre>',
        fix_mermaid,
        html_content,
    )

    # Template HTML con diseño profesional
    html_doc = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>BACO — Especificación Técnica y Arquitectura del Sistema</title>
  <style>
    @page {{
      size: A4;
      margin: 18mm 16mm 18mm 16mm;
    }}
    
    * {{
      box-sizing: border-box;
    }}
    
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      font-size: 10.5pt;
      line-height: 1.55;
      color: #1e293b;
      background-color: #ffffff;
      margin: 0;
      padding: 0;
    }}
    
    h1, h2, h3, h4, h5, h6 {{
      color: #0f172a;
      font-weight: 700;
      line-height: 1.25;
      page-break-after: avoid;
    }}
    
    h1 {{
      font-size: 22pt;
      color: #1e3a8a;
      border-bottom: 2.5px solid #2563eb;
      padding-bottom: 8px;
      margin-top: 0;
      margin-bottom: 12px;
    }}
    
    h2 {{
      font-size: 14pt;
      color: #1e40af;
      border-bottom: 1px solid #e2e8f0;
      padding-bottom: 6px;
      margin-top: 24px;
      margin-bottom: 10px;
    }}
    
    h3 {{
      font-size: 11.5pt;
      color: #1e293b;
      margin-top: 16px;
      margin-bottom: 6px;
    }}
    
    p {{
      margin-top: 0;
      margin-bottom: 8px;
      text-align: justify;
    }}
    
    strong {{
      color: #0f172a;
      font-weight: 600;
    }}
    
    a {{
      color: #2563eb;
      text-decoration: none;
    }}
    
    hr {{
      border: 0;
      height: 1px;
      background: #e2e8f0;
      margin: 18px 0;
    }}
    
    ul, ol {{
      margin-top: 0;
      margin-bottom: 10px;
      padding-left: 22px;
    }}
    
    li {{
      margin-bottom: 4px;
    }}
    
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 14px 0;
      font-size: 9.5pt;
      page-break-inside: avoid;
    }}
    
    th, td {{
      padding: 7px 10px;
      border: 1px solid #cbd5e1;
      text-align: left;
      vertical-align: top;
    }}
    
    th {{
      background-color: #f1f5f9;
      color: #0f172a;
      font-weight: 600;
    }}
    
    tr:nth-child(even) td {{
      background-color: #f8fafc;
    }}
    
    code {{
      font-family: Consolas, "Liberation Mono", Menlo, Courier, monospace;
      font-size: 9pt;
      background-color: #f1f5f9;
      color: #b91c1c;
      padding: 1.5px 4px;
      border-radius: 4px;
      border: 1px solid #e2e8f0;
    }}
    
    pre {{
      background-color: #0f172a;
      color: #f8fafc;
      padding: 10px 14px;
      border-radius: 6px;
      font-family: Consolas, "Liberation Mono", Menlo, Courier, monospace;
      font-size: 8.5pt;
      line-height: 1.45;
      overflow-x: auto;
      margin: 10px 0;
      page-break-inside: avoid;
    }}
    
    pre code {{
      background-color: transparent;
      color: inherit;
      padding: 0;
      border: none;
      font-size: inherit;
    }}
    
    blockquote {{
      margin: 10px 0;
      padding: 8px 14px;
      background-color: #eff6ff;
      border-left: 4px solid #3b82f6;
      color: #1e3a8a;
      border-radius: 0 4px 4px 0;
      page-break-inside: avoid;
    }}
    
    blockquote p {{
      margin: 0;
      text-align: left;
    }}
    
    .mermaid-container {{
      text-align: center;
      margin: 16px 0;
      padding: 12px;
      background-color: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      page-break-inside: avoid;
    }}
    
    .mermaid {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    }}

    .document-header {{
      background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%);
      color: white;
      padding: 18px 20px;
      border-radius: 8px;
      margin-bottom: 20px;
    }}
    
    .document-header h1 {{
      color: white;
      border-bottom: 1px solid rgba(255, 255, 255, 0.3);
      padding-bottom: 6px;
      margin-bottom: 6px;
      font-size: 20pt;
    }}
    
    .document-header .subtitle {{
      font-size: 11pt;
      opacity: 0.95;
      font-weight: 500;
    }}
    
    .document-header .meta {{
      font-size: 8.5pt;
      opacity: 0.8;
      margin-top: 8px;
    }}
  </style>
  <script type="module">
    import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
    mermaid.initialize({{
      startOnLoad: true,
      theme: 'neutral',
      fontFamily: 'Segoe UI, -apple-system, sans-serif',
      fontSize: 12,
      flowchart: {{
        htmlLabels: true,
        curve: 'basis'
      }}
    }});
    window.addEventListener('load', async () => {{
      await mermaid.run();
      document.body.classList.add('mermaid-ready');
    }});
  </script>
</head>
<body>
  {html_content}
</body>
</html>
"""
    return html_doc


def encontrar_ejecutable_navegador() -> Path:
    for path in CHROME_PATHS:
        if path.exists():
            return path
    raise FileNotFoundError("No se encontró Google Chrome ni Microsoft Edge en las rutas estándar.")


def generar_pdf():
    print(f"1. Leyendo {MD_PATH.name}...")
    md_text = MD_PATH.read_text(encoding="utf-8")

    print("2. Convirtiendo Markdown a HTML con estilos de alta calidad...")
    html_content = convertir_md_a_html(md_text)
    HTML_PATH.write_text(html_content, encoding="utf-8")
    print(f"   HTML guardado en: {HTML_PATH}")

    browser_exe = encontrar_ejecutable_navegador()
    print(f"3. Generando PDF con: {browser_exe.name}...")

    cmd = [
        str(browser_exe),
        "--headless=new",
        "--disable-gpu",
        "--virtual-time-budget=5000",
        "--no-pdf-header-footer",
        f"--print-to-pdf={PDF_PATH}",
        str(HTML_PATH),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error al ejecutar navegador: {result.stderr}", file=sys.stderr)
        sys.exit(result.returncode)

    if not PDF_PATH.exists():
        print("❌ Error: No se pudo generar el archivo PDF.", file=sys.stderr)
        sys.exit(1)

    tamano_kb = PDF_PATH.stat().st_size / 1024
    print(f"✅ PDF generado exitosamente: {PDF_PATH} ({tamano_kb:.1f} KB)")

    # Copiar a Downloads para máxima comodidad
    if DOWNLOADS_DIR.exists():
        shutil.copy2(PDF_PATH, DOWNLOADS_PDF_PATH)
        print(f"📋 Copia adicional lista en Descargas: {DOWNLOADS_PDF_PATH}")


if __name__ == "__main__":
    generar_pdf()
