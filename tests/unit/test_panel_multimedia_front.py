"""Paso 5: componente del mini panel de carga multimedia en el front.

- Componente propio (js/panel-multimedia.js), sin dependencias.
- Fuente de datos: s.borrador.multimedia (no el texto).
- Visible por s.multimedia_habilitada, sin guard de modo enriquecer/actualizar.
- El editor trabaja solo con texto_limpio; la vista previa agrega los recursos al final.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

FRONT = Path("frontend")
PANEL_JS = (FRONT / "js" / "panel-multimedia.js").read_text(encoding="utf-8")
APP_JS = (FRONT / "js" / "app.js").read_text(encoding="utf-8")
ESTADOS_JS = (FRONT / "js" / "estados.js").read_text(encoding="utf-8")
INDEX = (FRONT / "index.html").read_text(encoding="utf-8")
CSS = (FRONT / "styles.css").read_text(encoding="utf-8")


def test_componente_cargado_y_contenedor_en_index():
    assert 'id="panelMultimedia"' in INDEX
    i_panel = INDEX.index("js/panel-multimedia.js")
    assert INDEX.index("js/estados.js") < i_panel < INDEX.index("js/app.js")


def test_panel_no_depende_del_modo_ni_del_texto():
    # El código del componente (sin comentarios) no mira modo / enriquecimiento / articulo_original_id
    codigo_panel = re.sub(r"/\*.*?\*/", "", PANEL_JS, flags=re.S)
    for prohibido in ("enriquecimiento", "actualizar", "articulo_original_id", ".modo"):
        assert prohibido not in codigo_panel
    # Ni extrae recursos desde el texto
    assert "extraerRecursos" not in APP_JS
    assert "b.multimedia" in PANEL_JS and "multimedia_habilitada" in PANEL_JS
    # app.js llama al panel antes (y por fuera) del guard de contenido adicional
    i_llamada = APP_JS.index("BACO.panelMultimedia.pintar($('#panelMultimedia'), s)")
    i_guard = APP_JS.index("if (!adicionales.length && !esEnriquecerOActualizar)")
    assert i_llamada < i_guard


def test_controles_del_panel_presentes():
    assert 'class="pm-quitar"' in PANEL_JS and ">×</button>" in PANEL_JS      # "x" para quitar
    assert 'data-accion="subir"' in PANEL_JS and 'data-accion="bajar"' in PANEL_JS
    assert 'draggable="' in PANEL_JS and 'class="pm-asa"' in PANEL_JS         # arrastrar y soltar
    assert "+ Agregar multimedia" in PANEL_JS
    assert 'type="file"' in PANEL_JS and 'type="url"' in PANEL_JS            # subir archivo / pegar URL
    assert ".panel-multimedia .pm-quitar" in CSS and ".panel-multimedia .pm-item.destino" in CSS


def test_editor_usa_solo_texto_limpio():
    assert "estado.form.texto = r.borrador.texto_limpio || ''" in ESTADOS_JS
    assert "estado.form.texto = r.borrador.texto || ''" not in ESTADOS_JS
    assert "s.form.texto !== (b.texto_limpio || '')" in APP_JS
    assert "renderMd(textoVistaPrevia(" in APP_JS
    assert "renderMd(s.form.texto)" not in APP_JS


# ---------------------------------------------------------------------------
# Render real con Node (si está disponible)
# ---------------------------------------------------------------------------

NODE = shutil.which("node")

SCRIPT = r"""
const fs = require('fs');
global.window = global;
eval(fs.readFileSync('frontend/js/panel-multimedia.js', 'utf8'));
const casos = JSON.parse(process.argv[1]);
const out = casos.map((s) => {
  const cont = { hidden: true, innerHTML: '' };
  BACO.panelMultimedia.pintar(cont, s);
  return {
    hidden: cont.hidden,
    html: cont.innerHTML,
    preview: BACO.panelMultimedia.componerVistaPrevia(s.form.texto, BACO.panelMultimedia.lista(s)),
  };
});
process.stdout.write(JSON.stringify(out));
"""

MULTI = [
    {"id": "rec_2", "tipo": "video", "nombre": "Tutorial", "referencia": "https://youtu.be/a", "origen": "existente", "orden": 0},
    {"id": "rec_1", "tipo": "imagen", "nombre": "Captura", "referencia": "https://x/1.png", "origen": "existente", "orden": 1},
]


def _render(casos):
    r = subprocess.run([NODE, "-e", SCRIPT, json.dumps(casos)], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(r.stdout)


@pytest.mark.skipif(NODE is None, reason="Node no disponible")
def test_render_real_del_panel():
    base = {"form": {"texto": "Paso 1.\n\nPaso 2."}}
    nuevo = dict(base, flujo="REVISION_BORRADOR", multimedia_habilitada=True,
                 borrador={"modo": "nuevo", "multimedia": MULTI, "recursos": {}})
    enriquecer = dict(nuevo, borrador={"modo": "enriquecimiento", "articulo_original_id": 7, "multimedia": MULTI})
    deshabilitado = dict(nuevo, multimedia_habilitada=False)
    vacio = dict(nuevo, borrador={"modo": "nuevo", "multimedia": []})

    r_nuevo, r_enr, r_des, r_vacio = _render([nuevo, enriquecer, deshabilitado, vacio])

    # Mismo panel en flujo nuevo y en enriquecer (sin guard de modo)
    assert r_nuevo["hidden"] is False and r_enr["hidden"] is False
    assert r_nuevo["html"] == r_enr["html"]
    # Orden del backend respetado, con "x", asa y ↑/↓ en cada ítem
    h = r_nuevo["html"]
    assert h.index('data-id="rec_2"') < h.index('data-id="rec_1"')
    assert h.count('class="pm-quitar"') == 2 and h.count('class="pm-asa"') == 2
    assert 'data-accion="subir" data-idx="0" title="Subir" aria-label="Subir" disabled' in h
    assert 'data-accion="bajar" data-idx="1" title="Bajar" aria-label="Bajar" disabled' in h
    assert "+ Agregar multimedia" in h
    # Antes de superar la deduplicación no se muestra
    assert r_des["hidden"] is True and r_des["html"] == ""
    # Lista vacía: aviso + botón igual visible
    assert "pm-vacio" in r_vacio["html"] and "+ Agregar multimedia" in r_vacio["html"]
    # Vista previa = texto + sección Recursos en el orden de la lista
    assert r_nuevo["preview"] == (
        "Paso 1.\n\nPaso 2.\n\n## Recursos\n\n[Tutorial](https://youtu.be/a)\n\n![Captura](https://x/1.png)"
    )


@pytest.mark.skipif(NODE is None, reason="Node no disponible")
def test_render_escapa_nombres():
    s = {"form": {"texto": ""}, "flujo": "REVISION_BORRADOR", "multimedia_habilitada": True,
         "borrador": {"multimedia": [{"id": "r", "tipo": "otro", "nombre": "<img src=x onerror=alert(1)>",
                                      "referencia": "javascript:alert(1)", "orden": 0}]}}
    (r,) = _render([s])
    assert "<img src=x" not in r["html"]
    assert 'href="javascript:' not in r["html"]


@pytest.mark.skipif(NODE is None, reason="Node no disponible")
def test_aplicar_turno_vuelca_texto_enriquecer_automaticamente():
    script_estados = "global.window = global;\n" + ESTADOS_JS + """
    BACO.store.reiniciarLocal();
    BACO.store.aplicarTurno({
        session_id: 'ses-1',
        estado: 'REVISION_BORRADOR',
        multimedia_habilitada: true,
        borrador: {
            modo: 'enriquecimiento',
            articulo_original_id: 101,
            titulo: 'Artículo Existente',
            texto_limpio: 'Texto original volcado directamente en el panel izquierdo.',
            recursos: [],
            tags: ['instructivo', 'demo']
        }
    });
    console.log(JSON.stringify(BACO.store.get().form));
    """
    r = subprocess.run([NODE, "-e", script_estados], capture_output=True, text=True, encoding="utf-8", check=True)
    form = json.loads(r.stdout)
    assert form["texto"] == "Texto original volcado directamente en el panel izquierdo."
    assert form["titulo"] == "Artículo Existente"


@pytest.mark.skipif(NODE is None, reason="Node no disponible")
def test_confirmar_texto_en_panel_izquierdo_y_no_en_companion():
    script = "global.window = global;\n" + ESTADOS_JS + """
    console.log(JSON.stringify({
        campoActivoTexto: BACO.CAMPOS_ACTIVOS.ESPERANDO_TEXTO.texto,
        accionPrincipal: BACO.ACCION_PRINCIPAL.ESPERANDO_TEXTO
    }));
    """
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    res = json.loads(r.stdout)
    assert res["campoActivoTexto"] is True
    assert res["accionPrincipal"]["label"] == "Confirmar texto"
    assert res["accionPrincipal"]["campo"] == "texto"

    # En app.js se valida que Baco Companion excluya 'confirmar_texto'
    app_code = (FRONT / "js" / "app.js").read_text(encoding="utf-8")
    assert "opcionesCompanion = (opciones || []).filter((op) => op !== 'confirmar_texto')" in app_code


@pytest.mark.skipif(NODE is None, reason="Node no disponible")
def test_vista_previa_respeta_formato_original_api():
    script = "global.window = global;\n" + PANEL_JS + """
    const textoApi = "Paso 1: abrir configuracion.\\n\\n![captura](https://bc.finneg.com/img1.png)\\n\\nPaso 2: guardar.";
    const textoLimpio = "Paso 1: abrir configuracion.\\n\\nPaso 2: guardar.";
    const items = [{ id: 'rec_1', tipo: 'imagen', nombre: 'captura', referencia: 'https://bc.finneg.com/img1.png', orden: 0 }];

    const s = {
        coincidencias: [{ texto_original: textoApi }],
        borrador: { texto_limpio: textoLimpio }
    };

    // 1. Al inicio, la vista previa es exactamente el formato de la API (con la imagen en su lugar original)
    const prevInicio = BACO.panelMultimedia.componerVistaPrevia(textoLimpio, items, s);

    // 2. Si el usuario elimina la imagen (items vacios)
    const prevSinImg = BACO.panelMultimedia.componerVistaPrevia(textoLimpio, [], s);

    // 3. Si el usuario agrega un recurso nuevo
    const itemsConNuevo = items.concat([{ id: 'rec_2', tipo: 'documento', nombre: 'Manual', referencia: 'https://bc.finneg.com/manual.pdf', orden: 1 }]);
    const prevConNuevo = BACO.panelMultimedia.componerVistaPrevia(textoLimpio, itemsConNuevo, s);

    // 4. Si el usuario edita el texto en el editor
    const textoModificado = "Paso 1 modificado.\\n\\nPaso 2 modificado.";
    const prevModificado = BACO.panelMultimedia.componerVistaPrevia(textoModificado, items, s);

    // 5. Si el usuario confirma su texto nuevo y el borrador se actualiza con el texto nuevo:
    const sConfirmado = {
        coincidencias: [{ texto_original: textoApi }],
        borrador: { texto_limpio: textoModificado, texto: textoModificado }
    };
    const prevConfirmado = BACO.panelMultimedia.componerVistaPrevia(textoModificado, items, sConfirmado);

    console.log(JSON.stringify({ prevInicio, prevSinImg, prevConNuevo, prevModificado, prevConfirmado }));
    """
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    res = json.loads(r.stdout)

    # 1. Al inicio mantiene el formato original de la API
    assert "![captura](https://bc.finneg.com/img1.png)" in res["prevInicio"]
    assert "## Recursos" not in res["prevInicio"]
    assert res["prevInicio"].index("Paso 1") < res["prevInicio"].index("![captura]") < res["prevInicio"].index("Paso 2")

    # 2. Al quitar la imagen, ya no figura
    assert "https://bc.finneg.com/img1.png" not in res["prevSinImg"]

    # 3. Al agregar un recurso nuevo, se suma a la vista previa
    assert "https://bc.finneg.com/manual.pdf" in res["prevConNuevo"]

    # 4. Al modificar el texto desde el editor, la vista previa refleja el texto modificado
    assert "Paso 1 modificado." in res["prevModificado"]

    # 5. Luego de confirmar el texto nuevo, no resucita el texto original de la API
    assert "Paso 1 modificado." in res["prevConfirmado"]
    assert "Paso 1: abrir configuracion." not in res["prevConfirmado"]


def test_layout_formulario_sin_banner_coincidencias_y_editor_amplio():
    # 1. El banner 'Ya hay algo parecido publicado' fue removido por completo
    assert "Ya hay algo parecido publicado" not in APP_JS
    assert 'id="slotCoincidencias"' not in INDEX

    # 2. La sección 'Título *' (#campoTitulo) comienza directamente debajo del toolbar ('Empezar de nuevo')
    i_reiniciar = INDEX.index('id="btnReiniciar"')
    i_panebody = INDEX.index('class="panebody scroll"')
    i_titulo = INDEX.index('id="campoTitulo"')
    i_borrador = INDEX.index('id="slotBorrador"')
    assert i_reiniciar < i_panebody < i_titulo < i_borrador

    # 3. Área de texto Markdown ampliada (min-height >= 450px / 50vh) y botón Confirmar en extremo inferior derecho
    assert "min-height: max(450px, 50vh)" in CSS
    assert 'id="btnConfirmarBloques"' in INDEX
    assert "justify-content: flex-end" in CSS

    # 4. Una sola línea divisora con '+' (sin segunda línea divisora debajo del área de texto)
    assert "crearDivisor(0, deshabilitado)" in APP_JS
    assert "crearDivisor(idx + 1, deshabilitado)" not in APP_JS


def test_nodos_ocultos_desacoplados_null_safe():
    # Ninguno de los 4 nodos opcionales/ocultos se desreferencia directo sin guard
    app_code = (FRONT / "js" / "app.js").read_text(encoding="utf-8")
    for sel in ("#fCuerpo", "#preview", "#panelMultimedia", "#editorImgBar"):
        assert f"$('{sel}')." not in app_code
        assert f'$("{sel}").' not in app_code



