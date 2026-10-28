"""Pruebas unitarias para la página de sólo lectura de Artículo Final y botón en el chat."""
import json
import re
import shutil
import subprocess
from pathlib import Path
import pytest

FRONT = Path("frontend")
ARTICULO_HTML = (FRONT / "articulo.html").read_text(encoding="utf-8")
ARTICULO_JS = (FRONT / "js" / "articulo.js").read_text(encoding="utf-8")
CSS = (FRONT / "styles.css").read_text(encoding="utf-8")
ESTADOS_JS = (FRONT / "js" / "estados.js").read_text(encoding="utf-8")
APP_JS = (FRONT / "js" / "app.js").read_text(encoding="utf-8")

NODE = shutil.which("node")


def test_pagina_articulo_solo_lectura_sin_formularios_ni_edicion():
    """La página debe ser estrictamente de solo lectura: sin <form>, <textarea> ni <input> editables."""
    assert "<form" not in ARTICULO_HTML.lower()
    assert "<textarea" not in ARTICULO_HTML.lower()
    assert "<input" not in ARTICULO_HTML.lower()

    # Debe contener contenedores para metadatos superiores
    assert 'id="articuloTitulo"' in ARTICULO_HTML
    assert 'id="articuloCategoria"' in ARTICULO_HTML
    assert 'id="articuloTags"' in ARTICULO_HTML

    # Contenedor para el texto dividido por secciones
    assert 'id="articuloSecciones"' in ARTICULO_HTML

    # Mensaje de estado cuando no existe o está vacío
    assert 'id="mensajeEstado"' in ARTICULO_HTML


def test_reutilizacion_de_css_e_identidad_visual():
    """La página debe reutilizar styles.css en vez de duplicar estilos."""
    assert 'href="styles.css"' in ARTICULO_HTML
    assert 'class="topbar"' in ARTICULO_HTML
    assert 'class="brand"' in ARTICULO_HTML
    assert 'class="modo"' in ARTICULO_HTML
    assert 'class="pill info"' in ARTICULO_HTML


def test_encabezados_clase_css_unica_y_variables():
    """Encabezados: única clase CSS con tamaño 2x del cuerpo vía variable CSS y color celeste accesible."""
    assert "--articulo-heading-size: 2em;" in CSS or "--articulo-heading-size:2em;" in CSS
    assert "--articulo-heading-color: #1B6CA8;" in CSS or "--articulo-heading-color:#1B6CA8;" in CSS

    m = re.search(r"\.encabezado-articulo\s*\{([^}]+)\}", CSS)
    assert m is not None, "No se encontró la clase .encabezado-articulo en styles.css"
    reglas = m.group(1)
    assert "var(--articulo-heading-size" in reglas
    assert "var(--articulo-heading-color" in reglas

    assert "encabezado-articulo" in ARTICULO_JS


def test_boton_ver_articulo_en_chat():
    """Botón 'Ver artículo' disponible en chat en color naranja (coral) al registrar conformidad."""
    assert "ver_articulo_final" in ESTADOS_JS
    assert "Ver artículo" in ESTADOS_JS

    # app.js maneja la acción y abre en nueva pestaña
    assert "op === 'ver_articulo_final'" in APP_JS
    assert "articulo.html?session_id=" in APP_JS
    assert "window.open(" in APP_JS
    assert "'_blank'" in APP_JS

    assert "opcionesTurno.unshift('ver_articulo_final')" in APP_JS or "opcionesTurno.includes('ver_articulo_final')" in APP_JS
    assert "btn.id = 'btnVerArticuloFinal'" in APP_JS

    # Estilos del botón en styles.css (color naranja/coral idéntico a Copiar borrador)
    assert "#btnVerArticuloFinal" in CSS
    assert "var(--coral)" in CSS


def test_secciones_separacion_y_orden_estricto():
    """Cada sección debe ordenarse: Encabezado -> Texto -> Imagen (si tiene)."""
    i_enc = ARTICULO_JS.index("secEl.appendChild(h)")
    i_txt = ARTICULO_JS.index("secEl.appendChild(txtEl)")
    i_img = ARTICULO_JS.index("secEl.appendChild(imgsWrap)")
    assert i_enc < i_txt < i_img

    assert ".articulo-seccion" in CSS
    assert "border-bottom" in CSS


def test_lectura_desde_servidor_por_session_id():
    """La página debe hacer fetch al servidor usando session_id en header X-Session-ID."""
    assert "/chat/borrador" in ARTICULO_JS
    assert "X-Session-ID" in ARTICULO_JS
    assert "session_id" in ARTICULO_JS


@pytest.mark.skipif(NODE is None, reason="Node no disponible")
def test_parsear_secciones_orden_e_imagenes_sin_seccion_con_numero():
    """Verifica con Node el comportamiento de parseo: no inventa 'Sección N', y respeta encabezados reales."""
    script = """
    const fs = require('fs');
    global.window = {
        location: { search: '?session_id=test-123' },
        BACO: { config: { BASE_URL: 'http://127.0.0.1:8080', API_KEY: 'test' } }
    };
    global.document = {
        getElementById: () => null,
        querySelector: () => null
    };

    const src = fs.readFileSync('frontend/js/articulo.js', 'utf8');
    const funcMatch = src.match(/function parsearSecciones[\\s\\S]*?\\n  \\}/);
    if (!funcMatch) throw new Error('No se encontró parsearSecciones');
    const extraMatch = src.match(/function extraerImagenesDeMarkdown[\\s\\S]*?\\n  \\}/);
    const resolverMatch = src.match(/function resolverUrlRecurso[\\s\\S]*?\\n  \\}/);
    eval(resolverMatch[0]);
    eval(extraMatch[0]);
    eval(funcMatch[0]);

    // Caso 1: Con encabezados oficiales de plantilla (ej. Consulta / Pasos a seguir)
    const borradorConHeaders = {
        titulo: 'Instructivo de Facturación',
        texto_alineado_discourse: [
            '## Consulta',
            'Explicación del problema o consulta.',
            '![Captura A](https://finneg.com/a.png)',
            '![Captura B](https://finneg.com/b.png)',
            '',
            '## Pasos a seguir',
            '1. Ingresar a parámetros.',
            '2. Guardar cambios.'
        ].join('\\n')
    };

    const sec1 = parsearSecciones(borradorConHeaders, 'http://127.0.0.1:8080');

    // Caso 2: Bloques sin encabezados Markdown (separadores internos sin texto tipo 'Sección 1')
    const borradorBloquesSinHeaders = {
        titulo: 'Entrada sin headers',
        bloques_texto: [
            'Texto del bloque inicial sin encabezado.',
            'Texto del segundo bloque sin encabezado.'
        ]
    };
    const sec2 = parsearSecciones(borradorBloquesSinHeaders, 'http://127.0.0.1:8080');

    console.log(JSON.stringify({ sec1, sec2 }));
    """
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    out = json.loads(r.stdout)
    sec1 = out["sec1"]
    sec2 = out["sec2"]

    assert len(sec1) == 2
    # Caso 1: muestra Consulta y Pasos a seguir
    assert sec1[0]["encabezado"] == "Consulta"
    assert "Explicación del problema" in sec1[0]["texto"]
    assert len(sec1[0]["imagenes"]) == 2
    assert sec1[0]["imagenes"][0]["url"] == "https://finneg.com/a.png"
    assert sec1[0]["imagenes"][1]["url"] == "https://finneg.com/b.png"

    assert sec1[1]["encabezado"] == "Pasos a seguir"
    assert "1. Ingresar a parámetros." in sec1[1]["texto"]
    assert len(sec1[1]["imagenes"]) == 0

    # Caso 2: NO inventa 'Sección 1' ni 'Sección 2'
    assert len(sec2) == 2
    for s in sec2:
        assert not re.match(r"^Secci[oó]n\s*\d*$", s.get("encabezado", ""), re.IGNORECASE)

def test_reutilizacion_vista_post_skill_y_boton_en_chat():
    """Tras ejecutar una skill, el botón 'Ver artículo' debe ofrecerse en el chat y
    articulo.js debe ser capaz de leer el borrador existente de sesión."""
    # Verificar que invocarAgente emite 'ver_articulo_final' en las opciones del turno/mensaje
    assert "decir(msgHtml, ['ver_articulo_final'], true)" in APP_JS
    # Verificar que el borrador preserva texto_alineado_discourse resultante
    assert "s.borrador.texto_alineado_discourse = texto;" in APP_JS
    # Verificar que articulo.js tiene la capacidad de leer la sesin existente (vía opener / store)
    assert "obtenerBorradorSesionExistente" in ARTICULO_JS

