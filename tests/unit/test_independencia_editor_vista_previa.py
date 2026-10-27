"""Tests para la independencia estricta entre Editor y Vista previa en Baco:

1) Editor y Vista previa son dos secciones independientes con estado propio.
2) El Editor contiene ÚNICAMENTE el texto escrito por la persona, en todas las rutas de enriquecer/actualizar.
3) Ningún cambio en la Vista previa sobrescribe ni regenera el contenido del Editor.
4) Cambiar de modo (Editor <-> Vista previa) no dispara llamadas que alteren la otra sección.
5) Cada modo mantiene su propio estado en el servidor (texto_editor vs bloques_texto/texto_limpio),
   con skills deshabilitadas en enriquecimiento y persistencia separada en recarga/reconexión.
"""
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from baco.server.app.api import get_buscador_duplicados, get_baco_agent
from baco.server.app.main import app
from baco.server.app.middleware import API_KEY
from baco.server.schemas.chat_orquestado import EstadoFlujo
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.orquestador.sesion import SESIONES

NODE = shutil.which("node") or shutil.which("nodejs")

TEXTO_ARTICULO_BASE = (
    "Guía original del artículo existente en Finneg.\n\n"
    "1. Ingresar al menú de Contabilidad.\n\n"
    "2. Seleccionar el ejercicio fiscal y guardar."
)


@pytest.fixture(autouse=True)
def limpiar():
    from baco.server.services.orquestador.validaciones import limpiar_cache_catalogos
    SESIONES.clear()
    limpiar_cache_catalogos()
    yield
    SESIONES.clear()
    limpiar_cache_catalogos()


@pytest.fixture
def mock_buscador():
    buscador = MagicMock(spec=BuscadorDuplicados)
    buscador.cur = MagicMock()
    buscador.obtener_articulo.return_value = {
        "id": 4001,
        "titulo": "Guía de Contabilidad Finneg",
        "url": "https://bc.finneg.com/t/4001",
        "texto": TEXTO_ARTICULO_BASE,
        "categoria_id": 2,
        "tags": ["instructivo", "contabilidad"],
    }
    return buscador


@pytest.fixture
def client(mock_buscador):
    def override_buscador():
        yield mock_buscador

    app.dependency_overrides[get_buscador_duplicados] = override_buscador
    app.dependency_overrides[get_baco_agent] = lambda: MagicMock()
    with patch("baco.server.db.config.crear_ro_pool"), \
         patch("baco.server.services.embeddings.get_model_titulo"), \
         patch("baco.server.services.embeddings.get_model_texto"):
        with TestClient(app, headers={"X-API-Key": API_KEY}) as c:
            yield c
    app.dependency_overrides.clear()


# ==============================================================================
# (a) Test Frontend en Node: editar en Editor, cambiar a Vista previa, modificarla,
#     volver al Editor => el texto escrito por el usuario sigue 100% intacto.
# ==============================================================================
@pytest.mark.skipif(NODE is None, reason="Node.js no disponible para test frontend")
def test_front_editar_cambiar_a_preview_modificar_y_volver_editor_texto_intacto():
    """Valida la condición sine qua non en el frontend:
    - El usuario escribe en el Editor.
    - Cambia a Vista previa (#btnPreview).
    - Se modifica la Vista previa (input en bloque editable o agregado/borrado de recursos).
    - Vuelve al Editor (#btnEditor).
    - El texto del Editor permanece exactamente intacto sin regenerarse ni sobrescribirse.
    """
    script = """
    const fs = require('fs');
    global.window = global;
    global.Event = class Event { constructor(t) { this.type = t; } };

    const elementosCreados = [];
    const nodoDummy = (tag) => {
      const n = {
        tagName: (tag || 'DIV').toUpperCase(),
        innerHTML: '', textContent: '', value: '', hidden: false, disabled: false,
        className: '', style: {}, dataset: {}, children: [], scrollHeight: 0, scrollTop: 0,
        focus() {},
        classList: {
          _set: new Set(),
          add(c){ this._set.add(c); },
          remove(c){ this._set.delete(c); },
          toggle(c, v){ if (v) this._set.add(c); else this._set.delete(c); },
          contains(c){ return this._set.has(c); }
        },
        appendChild(child){ this.children.push(child); return child; },
        replaceChildren(...args){ this.children = args; },
        insertBefore(n, ref){ this.children.push(n); },
        remove(){},
        setAttribute(k, v){ this.dataset[k] = v; },
        getAttribute(k){ return this.dataset[k] || null; },
        addEventListener(e, fn){ this['_on_' + e] = fn; },
        querySelectorAll(sel){
          return this.children.filter(c => sel.includes(c.className) || (c.dataset && sel.includes(c.dataset.bloqueIdx)));
        },
        querySelector(sel){ return this.children[0] || nodoDummy(); },
        closest(sel){ return this; }
      };
      elementosCreados.push(n);
      return n;
    };

    const domMap = {
      '#editorBloquesWrapper': nodoDummy('div'),
      '#contenedorBloques': nodoDummy('div'),
      '#fCuerpo': nodoDummy('textarea'),
      '#preview': nodoDummy('div'),
      '#btnEditor': nodoDummy('button'),
      '#btnPreview': nodoDummy('button'),
      '#campoTexto': nodoDummy('div'),
      '#panelMultimedia': nodoDummy('div'),
      '#editorImgBar': nodoDummy('div'),
      '#modo': nodoDummy('div'),
      '#toast': nodoDummy('div')
    };

    global.document = {
      activeElement: null,
      body: { contains: () => true, appendChild(){}, removeChild(){} },
      querySelector: (sel) => domMap[sel] || nodoDummy(),
      getElementById: (id) => domMap['#' + id] || nodoDummy(),
      createElement: (tag) => nodoDummy(tag),
      createDocumentFragment: () => nodoDummy('fragment'),
      addEventListener: () => {}
    };

    global.BACO = {
      config: { MIN_TITULO: 15, MAX_TITULO: 140, MIN_TEXTO: 20, MAX_TEXTO_PERCENTIL_99: 16777, MIN_TAGS: 2, MAX_TAGS: 5 },
      api: { esMock: true, turno: async () => ({ session_id: 's_test', estado: 'ESPERANDO_TEXTO', mensaje: 'Ok', opciones: [] }) }
    };

    eval(fs.readFileSync('frontend/js/estados.js', 'utf8'));
    eval(fs.readFileSync('frontend/js/panel-multimedia.js', 'utf8'));
    eval(fs.readFileSync('frontend/js/app.js', 'utf8'));

    // Simulamos respuesta de turno enriquecer
    const turnoEnriquecer = {
      session_id: 's_enriq_123',
      estado: 'ESPERANDO_TEXTO',
      borrador: {
        modo: 'enriquecimiento',
        titulo: 'Guía de Contabilidad Finneg',
        bloques_texto: ['Guía original del artículo existente en Finneg.', 'Paso 1: Entrar al menú.'],
        texto_base_limpio: 'Guía original del artículo existente en Finneg.\\n\\nPaso 1: Entrar al menú.',
        texto_editor: 'Mi texto redactado en el editor por el usuario.',
        texto_limpio: 'Guía original del artículo existente en Finneg.\\n\\nPaso 1: Entrar al menú.',
        recursos: {
          rec_1: { id: 'rec_1', nombre: 'diag.png', url: 'https://bc.finneg.com/diag.png', tipo: 'imagen', posicion: 0, orden: 0 }
        },
        multimedia: [{ id: 'rec_1', nombre: 'diag.png', url: 'https://bc.finneg.com/diag.png', tipo: 'imagen', posicion: 0, orden: 0 }],
        skills_habilitadas: false
      }
    };

    BACO.store.aplicarTurno(turnoEnriquecer);

    const btnEditor = domMap['#btnEditor'];
    const btnPreview = domMap['#btnPreview'];
    const preview = domMap['#preview'];

    // 1. El usuario cambia a Vista previa
    if (btnPreview.onclick) btnPreview.onclick();

    // 2. Modificamos la vista previa simulando edición en preview
    if (preview._on_input) {
      preview._on_input({
        target: {
          closest: () => ({
            getAttribute: () => '0',
            childNodes: [{ nodeType: 3, nodeValue: 'Texto modificado en la vista previa directamente por el usuario.' }]
          })
        }
      });
    }

    // 3. El usuario vuelve al Editor
    if (btnEditor.onclick) btnEditor.onclick();

    // Comprobamos que el editor conserva su texto propio sin ser sobreescrito por la vista previa
    const formEstado = BACO.store.get().form;

    console.log(JSON.stringify({
      textoEditorEnStore: formEstado.texto_editor,
      skillsHabilitadas: BACO.store.get().borrador.skills_habilitadas
    }));
    """
    res = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    out = json.loads(res.stdout)
    assert out["textoEditorEnStore"] == "Mi texto redactado en el editor por el usuario."
    assert out["skillsHabilitadas"] is False


# ==============================================================================
# (b) Test Servidor / Handlers: coincidencia por título vs. coincidencia por texto
# ==============================================================================
def test_coincidencia_por_titulo_editor_vacio_y_vista_previa_original(client, mock_buscador):
    """En coincidencia por título (DECISION_TITULO):
    - Al elegir enriquecer:
      - borrador.texto_editor queda vacío ("") porque el usuario solo ingresó título.
      - borrador.bloques_texto y texto_limpio contienen el artículo original completo.
      - skills_habilitadas es False.
    """
    mock_buscador.evaluar_titulo.return_value = {
        "mensaje": "Coincidencia de título encontrada",
        "link": "https://bc.finneg.com/t/4001",
        "coincidencias": [(4001, "Guía de Contabilidad Finneg", "https://bc.finneg.com/t/4001")],
    }

    r1 = client.post("/chat", json={"mensaje": "Guía de Contabilidad Finneg"}).json()
    assert r1["estado"] == EstadoFlujo.DECISION_TITULO
    sid = r1["session_id"]

    r2 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()
    assert r2["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    borrador = r2["borrador"]
    assert borrador is not None
    assert borrador["modo"] == "enriquecimiento"
    # Editor contiene ÚNICAMENTE lo escrito por la persona (en este flujo: "")
    assert borrador["texto_editor"] == ""
    # Vista previa contiene el artículo original de la base
    assert "Guía original del artículo existente" in borrador["texto_limpio"]
    # Skills deshabilitadas para enriquecimiento
    assert r2["skills_habilitadas"] is False
    assert borrador["skills_habilitadas"] is False


def test_coincidencia_por_texto_editor_conserva_aporte_y_vista_previa_original(client, mock_buscador):
    """En coincidencia por texto (DECISION_TEXTO):
    - Al elegir enriquecer:
      - borrador.texto_editor contiene ÚNICAMENTE el aporte escrito por el usuario.
      - borrador.bloques_texto y texto_limpio contienen ÚNICAMENTE el artículo original (sin fusionar automáticamente).
      - skills_habilitadas es False.
    """
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Coincidencia de contenido detectada",
        "link": "https://bc.finneg.com/t/4001",
        "coincidencias": [(4001, "Guía de Contabilidad Finneg", "https://bc.finneg.com/t/4001")],
    }

    # 1. Título
    r1 = client.post("/chat", json={"mensaje": "Procedimiento de Asientos Contables"}).json()
    sid = r1["session_id"]
    assert r1["estado"] == EstadoFlujo.ESPERANDO_TEXTO

    # 2. Envía texto que coincide
    mi_aporte = "Nota adicional: recordar validar la numeración correlativa del asiento antes del cierre."
    r2 = client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": mi_aporte}).json()
    assert r2["estado"] == EstadoFlujo.DECISION_TEXTO

    # 3. Elige enriquecer
    r3 = client.post("/chat", json={"session_id": sid, "accion": "enriquecer"}).json()
    assert r3["estado"] == EstadoFlujo.ESPERANDO_TEXTO
    borrador = r3["borrador"]

    # El Editor contiene ÚNICAMENTE su aporte, sin el texto base de la DB
    assert borrador["texto_editor"] == mi_aporte
    # La Vista previa contiene ÚNICAMENTE el artículo base sin fusión automática
    assert borrador["texto_limpio"].strip() == TEXTO_ARTICULO_BASE.strip()
    assert mi_aporte not in borrador["texto_limpio"]
    # Skills deshabilitadas
    assert r3["skills_habilitadas"] is False
    assert borrador["skills_habilitadas"] is False


# ==============================================================================
# (c) Test Recarga / Reconexión de sesión: persistencia separada de ambos estados
# ==============================================================================
def test_recarga_y_reconexion_sesion_preserva_ambos_estados_separados(client, mock_buscador):
    """Verifica que al recargar o reconectar una sesión existente (cookie de sesión):
    - El borrador devuelto mantiene texto_editor y texto_limpio en campos separados.
    - No se mezclan ni se sobrescriben en el servidor ni al consultar el borrador.
    """
    mock_buscador.evaluar_titulo.return_value = None
    mock_buscador.evaluar_texto.return_value = {
        "mensaje": "Contenido coincidente",
        "link": "https://bc.finneg.com/t/4001",
        "coincidencias": [(4001, "Guía de Contabilidad Finneg", "https://bc.finneg.com/t/4001")],
    }

    r1 = client.post("/chat", json={"mensaje": "Cierre de Ejercicio Contable"}).json()
    sid = r1["session_id"]

    aporte = "Paso especial: verificar balance de sumas y saldos."
    client.post("/chat", json={"session_id": sid, "accion": "confirmar_texto", "texto": aporte})
    client.post("/chat", json={"session_id": sid, "accion": "enriquecer"})

    # Simulamos reconexión o recarga enviando mensaje de consulta de sesión con la misma cookie
    r_recone = client.post("/chat", json={"session_id": sid, "texto_editor": aporte}).json()
    borrador = r_recone["borrador"]

    assert borrador is not None
    # Campo separado del editor
    assert borrador["texto_editor"] == aporte
    # Campo separado de la vista previa (artículo original, sin fusionar automáticamente)
    assert borrador["texto_limpio"].strip() == TEXTO_ARTICULO_BASE.strip()
    assert aporte not in borrador["texto_limpio"]
    # Skills deshabilitadas
    assert borrador["skills_habilitadas"] is False
