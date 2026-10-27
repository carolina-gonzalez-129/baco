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





def test_barra_herramientas_discourse_y_accesibilidad():
    # Barra estilo Discourse sobre #campoTexto reutilizando #btnEditor y #btnPreview
    assert 'id="editorToolbar"' in INDEX
    assert 'role="toolbar"' in INDEX
    for btn_id in (
        "btnEditor",
        "btnPreview",
        "btnMdBold",
        "btnMdItalic",
        "btnMdHeading",
        "btnMdLink",
        "btnMdQuote",
        "btnMdCode",
        "btnMdList",
        "btnEmojiToolbar",
        "btnImagenToolbar",
    ):
        assert f'id="{btn_id}"' in INDEX

    # Botón de imagen deshabilitado por defecto con el tooltip requerido
    assert 'id="btnImagenToolbar"' in INDEX
    assert 'title="Disponible al finalizar las validaciones"' in INDEX

    # #editorBloquesWrapper reactivado (no oculto con display:none fijo en index.html)
    m_wrapper = re.search(r'<div[^>]*id="editorBloquesWrapper"[^>]*>', INDEX)
    assert m_wrapper is not None
    assert "display: none" not in m_wrapper.group(0)
    assert " hidden" not in m_wrapper.group(0)

    # Estilos reutilizando variables CSS existentes
    assert ".edhead.discourse-toolbar" in CSS
    assert "var(--surface-2)" in CSS and "var(--coral-soft)" in CSS


@pytest.mark.skipif(NODE is None, reason="Node no disponible")
def test_actualizar_disponibilidad_recursos_funcion_unica():
    # Ninguna otra parte del front decide etapas por su cuenta
    assert "ESTADOS_PREVIOS_A_DEDUP" not in PANEL_JS
    assert "function actualizarDisponibilidadRecursos(resp)" in ESTADOS_JS
    assert "BACO.actualizarDisponibilidadRecursos" in APP_JS

    script = "global.window = global;\n" + ESTADOS_JS + """
    const btnFake = {
      disabled: true,
      title: '',
      attrs: {},
      setAttribute(k, v) { this.attrs[k] = v; }
    };
    global.document = {
      getElementById(id) { return id === 'btnImagenToolbar' ? btnFake : null; }
    };

    const hab1 = BACO.actualizarDisponibilidadRecursos({ multimedia_habilitada: false });
    const estado1 = { disabled: btnFake.disabled, title: btnFake.title, hab: hab1 };

    const hab2 = BACO.actualizarDisponibilidadRecursos({ multimedia_habilitada: true });
    const estado2 = { disabled: btnFake.disabled, title: btnFake.title, hab: hab2 };

    console.log(JSON.stringify({ estado1, estado2 }));
    """
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    out = json.loads(r.stdout)
    assert out["estado1"] == {
        "disabled": True,
        "title": "Disponible al finalizar las validaciones",
        "hab": False,
    }
    assert out["estado2"] == {
        "disabled": False,
        "title": "Insertar imagen",
        "hab": True,
    }


@pytest.mark.skipif(NODE is None, reason="Node no disponible")
def test_vista_previa_intercalada_respeta_orden_posicion_y_orden():
    script = "global.window = global;\n" + PANEL_JS + """
    const bloques = ["Primer bloque de introducción.", "Segundo bloque intermedio.", "Tercer bloque de cierre."];
    const recursos = [
      { id: 'rec_3', tipo: 'imagen', nombre: 'Final', referencia: 'https://x/fin.png', posicion: 2, orden: 3 },
      { id: 'rec_0', tipo: 'imagen', nombre: 'Portada', referencia: 'https://x/portada.png', posicion: -1, orden: 0 },
      { id: 'rec_2', tipo: 'imagen', nombre: 'Medio2', referencia: 'https://x/m2.png', posicion: 0, orden: 2 },
      { id: 'rec_1', tipo: 'imagen', nombre: 'Medio1', referencia: 'https://x/m1.png', posicion: 0, orden: 1 }
    ];
    const s = { borrador: { bloques_texto: bloques } };
    const preview = BACO.panelMultimedia.renderPreview(bloques.join('\\n\\n'), recursos, s);
    console.log(JSON.stringify({ preview }));
    """
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    preview = json.loads(r.stdout)["preview"]
    partes = preview.split("\n\n")
    assert partes == [
        "![Portada](https://x/portada.png)",
        "Primer bloque de introducción.",
        "![Medio1](https://x/m1.png)",
        "![Medio2](https://x/m2.png)",
        "Segundo bloque intermedio.",
        "Tercer bloque de cierre.",
        "![Final](https://x/fin.png)",
    ]


def test_conteo_code_points_y_copiar_texto_alineado_discourse():
    assert "Array.from(" in APP_JS
    assert "b.texto_alineado_discourse" in APP_JS
    assert "skills_motivo" in APP_JS


@pytest.mark.skipif(NODE is None, reason="Node no disponible")
def test_api_mock_paridad_particion_atomica_y_fusion_al_borrar():
    script = """
    const fs = require('fs');
    global.window = global;
    global.BACO = {
      config: {
        MIN_TITULO: 15, MAX_TITULO: 140, MIN_TEXTO: 20,
        MAX_TEXTO_PERCENTIL_99: 16777, MIN_TAGS: 2, MAX_TAGS: 5,
        CATEGORIA_DEFAULT: 5,
        mock: { LATENCIA_MS: 0, LATENCIA_AGENTE_MS: 0, TASA_ERROR: 0 }
      },
      datos: {
        baseConocimiento: [],
        categorias: [{ id: 5, nombre: 'Ventas' }],
        etiquetas: [{ tag: 'facturacion', usos: 10 }],
        plantillas: { instructivo: 'Plantilla instructivo' }
      }
    };
    eval(fs.readFileSync('frontend/js/api-mock.js', 'utf8'));
    (async () => {
      await BACO.apiMock.turno({});
      await BACO.apiMock.turno({ titulo: 'Instructivo completo de facturación electrónica' });
      const rTxt = await BACO.apiMock.turno({
        accion: 'confirmar_texto',
        texto: 'Paso 1 detallando la configuración inicial del módulo en el sistema.'
      });
      const estadoSubida = await BACO.apiMock.subirRecursoMultimedia(
        { name: 'captura.png', type: 'image/png', size: 2048 },
        0,
        ['Bloque 1 con CUIT 20-12345678-9 antes de imagen.', 'Bloque 2 después de imagen.']
      );

      let errorSvg = null;
      try {
        await BACO.apiMock.subirRecursoMultimedia(
          { name: 'malicioso.svg', type: 'image/svg+xml', size: 500 },
          0,
          ['Texto que no debe guardarse', 'Otro bloque']
        );
      } catch (e) {
        errorSvg = e.message;
      }
      const estadoTrasError = await BACO.apiMock.obtenerRecursos();

      const recId = estadoSubida.recursos[0].id;
      const estadoTrasBorrar = await BACO.apiMock.eliminarRecurso(recId);

      console.log(JSON.stringify({
        multiHab: rTxt.multimedia_habilitada,
        estadoSubida,
        errorSvg,
        estadoTrasError,
        estadoTrasBorrar
      }));
    })();
    """
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    out = json.loads(r.stdout)

    assert out["multiHab"] is True
    subida = out["estadoSubida"]
    assert len(subida["bloques_texto"]) == 2
    assert "[CUIT_OCULTO]" in subida["bloques_texto"][0]
    assert "20-12345678-9" not in subida["texto_limpio"]
    assert len(subida["recursos"]) == 1
    assert subida["recursos"][0]["posicion"] == 0
    assert subida["recursos"][0]["orden"] == 0
    assert subida["skills_habilitadas"] is False
    assert "Quitá los recursos" in subida["skills_motivo"]

    # Rollback atómico ante falla (SVG rechazado)
    assert "SVG" in out["errorSvg"]
    assert out["estadoTrasError"]["bloques_texto"] == subida["bloques_texto"]
    assert len(out["estadoTrasError"]["recursos"]) == 1

    # Fusión al borrar el recurso intermedio y reactivación de skills
    borrado = out["estadoTrasBorrar"]
    assert len(borrado["recursos"]) == 0
    assert len(borrado["bloques_texto"]) == 1
    assert "[CUIT_OCULTO]" in borrado["bloques_texto"][0]
    assert "Bloque 2 después de imagen." in borrado["bloques_texto"][0]
    assert borrado["skills_habilitadas"] is True


@pytest.mark.skipif(NODE is None, reason="Node no disponible")
def test_particion_cursor_markdown_y_validaciones_cliente_en_app():
    script = """
    const fs = require('fs');
    global.window = global;
    global.Event = class Event { constructor(t) { this.type = t; } };
    const nodoDummy = () => ({
      innerHTML: '', textContent: '', value: '', hidden: false, disabled: false,
      className: '', style: {}, dataset: {}, children: [], scrollHeight: 0, scrollTop: 0,
      classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
      appendChild(){}, replaceChildren(){}, insertBefore(){}, remove(){},
      setAttribute(){}, getAttribute(){ return null; }, addEventListener(){},
      querySelectorAll(){ return []; }, querySelector(){ return nodoDummy(); }, closest(){ return null; }
    });
    global.document = {
      activeElement: null,
      body: { contains: () => true, appendChild(){}, removeChild(){} },
      querySelector: () => nodoDummy(),
      getElementById: () => nodoDummy(),
      createElement: () => nodoDummy(),
      createDocumentFragment: () => nodoDummy(),
      addEventListener: () => {}
    };
    global.BACO = {
      config: { MIN_TITULO: 15, MAX_TITULO: 140, MIN_TEXTO: 20, MAX_TEXTO_PERCENTIL_99: 16777, MIN_TAGS: 2, MAX_TAGS: 5 },
      api: { esMock: true, turno: async () => ({ session_id: 's1', estado: 'ESPERANDO_TITULO', mensaje: 'Hola', opciones: [] }) }
    };
    eval(fs.readFileSync('frontend/js/estados.js', 'utf8'));
    eval(fs.readFileSync('frontend/js/panel-multimedia.js', 'utf8'));
    eval(fs.readFileSync('frontend/js/app.js', 'utf8'));

    // 1. Partición en cursor dentro de bloque 0
    const partConFoco = BACO.partirBloqueEnCursor(['Primera mitad. Segunda mitad.', 'Bloque final.'], 0, 15, 15);
    // 2. Sin foco: agrega al final sin partir
    const partSinFoco = BACO.partirBloqueEnCursor(['Bloque 1', 'Bloque 2'], null, null, null);

    // 3. Validaciones de archivo cliente
    const valSvg = BACO.validarArchivoCliente({ name: 'icono.svg', type: 'image/svg+xml', size: 100 }, [], 1);
    const val10Mb = BACO.validarArchivoCliente({ name: 'grande.png', type: 'image/png', size: 11 * 1024 * 1024 }, [], 1);
    const val50Mb = BACO.validarArchivoCliente(
      { name: 'extra.png', type: 'image/png', size: 6 * 1024 * 1024 },
      [{ id: 'r1', tamano_bytes: 45 * 1024 * 1024 }],
      2
    );
    const valMaxRecs = BACO.validarArchivoCliente(
      { name: 'ok.png', type: 'image/png', size: 1024 },
      Array.from({ length: 20 }, (_, i) => ({ id: 'r' + i, tamano_bytes: 100 })),
      2
    );
    const valMaxBloques = BACO.validarArchivoCliente({ name: 'ok.png', type: 'image/png', size: 1024 }, [], 22);
    const valOk = BACO.validarArchivoCliente({ name: 'ok.png', type: 'image/png', size: 2048 }, [], 2);

    // 4. Formato Markdown en textarea activo
    const fakeTa = {
      value: 'Hola mundo',
      disabled: false,
      selectionStart: 5,
      selectionEnd: 10,
      focus() {},
      setSelectionRange(a, b) { this.selectionStart = a; this.selectionEnd = b; },
      dispatchEvent() {}
    };
    const mdBold = BACO.insertarFormatoMarkdown(fakeTa, 'bold');

    // 5. Conteo de code points con emojis fuera del BMP
    const cpEmoji = BACO.lenCodePoints('A\\u{1F680}B');
    const utf16Len = 'A\\u{1F680}B'.length;

    console.log(JSON.stringify({
      partConFoco, partSinFoco,
      valSvg, val10Mb, val50Mb, valMaxRecs, valMaxBloques, valOk,
      mdBold, cpEmoji, utf16Len
    }));
    """
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    out = json.loads(r.stdout)

    assert out["partConFoco"] == {
        "bloques_texto": ["Primera mitad. ", "Segunda mitad.", "Bloque final."],
        "posicion": 0,
        "partido": True,
    }
    assert out["partSinFoco"] == {
        "bloques_texto": ["Bloque 1", "Bloque 2"],
        "posicion": 1,
        "partido": False,
    }
    assert out["valSvg"]["valido"] is False and "SVG" in out["valSvg"]["error"]
    assert out["val10Mb"]["valido"] is False and "10 MB" in out["val10Mb"]["error"]
    assert out["val50Mb"]["valido"] is False and "50 MB" in out["val50Mb"]["error"]
    assert out["valMaxRecs"]["valido"] is False and "20 recursos" in out["valMaxRecs"]["error"]
    assert out["valMaxBloques"]["valido"] is False and "21 bloques" in out["valMaxBloques"]["error"]
    assert out["valOk"]["valido"] is True
    assert out["mdBold"] == "Hola **mundo**"
    assert out["cpEmoji"] == 3 and out["utf16Len"] == 4
