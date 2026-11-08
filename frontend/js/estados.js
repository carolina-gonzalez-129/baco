/* =============================================================
   Máquina de estados del backend + store del panel
   -------------------------------------------------------------
   Los estados son los de EstadoFlujo
   (baco/server/schemas/chat_orquestado.py).

   EL BACKEND MANDA. El panel no calcula estados: refleja el
   `estado`, `etapa`, `tags_acumulados`, `categorias_disponibles`,
   `opciones`, `navegacion` y `editables` que devuelve cada turno
   (frontend/CONTRATO-API.md, sección contrato de estados).
   ============================================================= */
window.BACO = window.BACO || {};

BACO.ESTADOS = {
  ESPERANDO_TITULO:   { etiqueta: 'Esperando título',    tono: 'proceso',
                        ayuda: 'Escribí el título del artículo (mínimo 15 caracteres) y enviálo. BACO busca duplicados antes de seguir.' },
  DECISION_TITULO:    { etiqueta: 'Título duplicado',    tono: 'alerta',
                        ayuda: 'Encontró un artículo con título parecido. Decidí si lo enriquecés o seguís con uno nuevo.' },
  ESPERANDO_TEXTO:    { etiqueta: 'Esperando contenido', tono: 'proceso',
                        ayuda: 'Escribí o pegá el cuerpo del artículo de a poco (máximo 16777 caracteres, skills disponibles hasta 6687) y tocá "Confirmar texto" cuando esté listo.' },
  DECISION_TEXTO:     { etiqueta: 'Contenido similar',   tono: 'alerta',
                        ayuda: 'El contenido se parece a uno existente. Elegí si lo enriquecés o continuás con el tuyo.' },
  ESPERANDO_PLANTILLA:{ etiqueta: 'Elegir plantilla',    tono: 'proceso',
                        ayuda: 'Elegí qué plantilla aplicar: instructivo o soluciones.' },
  ESPERANDO_METADATOS:{ etiqueta: 'Etiquetas y categoría', tono: 'proceso',
                        ayuda: 'Revisá o completá la categoría y al menos una etiqueta temática además del tipo de plantilla, y tocá "Enviar datos".' },
  REVISION_TIPO:      { etiqueta: 'Revisión de plantilla', tono: 'info',
                        ayuda: 'Podés aplicar la plantilla al borrador o continuar sin aplicarla.' },
  REVISION_METADATOS: { etiqueta: 'Revisión de metadatos', tono: 'info',
                        ayuda: 'Podés auditar el borrador con el validador o continuar sin auditar.' },
  EDICION_FINAL:      { etiqueta: 'Edición final',        tono: 'info',
                        ayuda: 'Revisá y editá los datos finales. Cuando esté listo, tocá Finalizar.' },
  FINALIZADO:         { etiqueta: 'Finalizado',           tono: 'ok',
                        ayuda: 'Borrador registrado. La publicación la hace un moderador.' },
  RECHAZADO:          { etiqueta: 'Rechazado',           tono: 'alerta',
                        ayuda: 'El borrador fue rechazado. Reiniciá para empezar otra carga.' }
};

/* Campos activos: salen exclusivamente de `editables` del último turno del back.
   Misma forma de retorno que antes para no tocar a los que la consumen. */
BACO.camposActivos = function (s) {
  const ed = (s && Array.isArray(s.editables)) ? s.editables : [];
  return {
    titulo: ed.includes('titulo'),
    texto: ed.includes('texto') || ed.includes('texto_editor'),
    tags: ed.includes('tags'),
    categoria: ed.includes('categoria_id'),
    tipo_plantilla: ed.includes('tipo_plantilla')
  };
};

/* Cómo se muestra cada severidad que devuelve el validador */
BACO.SEVERIDAD = {
  'Bloqueante':     { clase: 'stop', orden: 0 },
  'Requiere ajuste':{ clase: 'warn', orden: 1 },
  'Ajuste':         { clase: 'warn', orden: 1 },
  'Sugerencia':     { clase: 'info', orden: 2 }
};

/* Texto de cada botón de `opciones` que devuelve el backend */
BACO.OPCIONES = {
  finalizar:         { label: 'Finalizar',               estilo: 'btn-primary' },
  confirmar_plantilla: { label: 'Sí, cambiar plantilla', estilo: 'btn-peligro' },
  cancelar_plantilla:  { label: 'Cancelar',              estilo: 'btn-ghost' },
  aceptar_metadatos: { label: 'Aceptar metadatos heredados', estilo: 'btn-primary' },
  rechazar_metadatos:{ label: 'Rechazar metadatos heredados', estilo: 'btn-secondary' },
  ver_articulo_final: { label: 'Ver artículo', estilo: 'btn-primary' },
  confirmar_texto:   { label: 'Confirmar texto',         estilo: 'btn-primary' },
  enriquecer:        { label: 'Enriquecer el existente', estilo: 'btn-dark' },
  actualizar:        { label: 'Actualizar el existente', estilo: 'btn-dark' },
  descartar:         { label: 'Es un tema distinto',     estilo: 'btn-ghost' },
  continuar:         { label: 'Continuar con mi texto',  estilo: 'btn-ghost' },
  instructivo:       { label: 'Instructivo',             estilo: 'btn-dark' },
  soluciones:        { label: 'Soluciones',              estilo: 'btn-dark' },
  aplicar_plantilla: { label: 'Aplicar plantilla',       estilo: 'btn-dark' },
  auditar:           { label: 'Auditar',                 estilo: 'btn-dark' },
  editar:            { label: 'Seguir editando',         estilo: 'btn-ghost' },
  rechazar:          { label: 'Descartar borrador',      estilo: 'btn-ghost' },
  confirmar_rechazo: { label: 'Sí, descartar',           estilo: 'btn-peligro' },
  cancelar_rechazo:  { label: 'Cancelar',                estilo: 'btn-ghost' },
  volver:            { label: 'Volver',                  estilo: 'btn-ghost' },
  ayuda:             { label: '¿Qué hago acá?',          estilo: 'btn-ghost' },
  reiniciar:         { label: 'Empezar de nuevo',        estilo: 'btn-ghost' }
};

/* -------------------------------------------------------------
   Store
   ------------------------------------------------------------- */
BACO.store = (function () {
  'use strict';
  const oyentes = [];
  const ETAPAS_DEFAULT = ['Título y duplicados', 'Contenido', 'Plantilla y etiquetas', 'Revisión', 'Conformidad'];
  const TOOLTIP_IMAGEN_DESHABILITADA = 'Disponible al finalizar las validaciones';

  const estado = {
    session_id: null,
    flujo: 'ESPERANDO_TITULO',
    etapa: {
      actual: 1,
      total: 5,
      nombre: ETAPAS_DEFAULT[0],
      etapas: ETAPAS_DEFAULT.slice()
    },
    opciones: [],
    botones: [],
    navegacion: [],
    navegacion_etiquetas: {},
    guardan_campos: [],  // acciones que viajan con los campos del panel (contrato)
    editables: ['titulo'],
    accion_panel: null,
    texto_servidor: '',  // texto_limpio que tiene el back (base para detectar cambios sin borrador)
    skills: null,
    tags_acumulados: [],
    categorias_disponibles: [],
    tags_disponibles: [],
    coincidencias: [],
    borrador: null,
    validacion: null,
    multimedia_habilitada: false,
    skill_plantilla_aplicada: false,


    form: { titulo: '', texto: '', texto_editor: '', tags: [], categoria_id: null },

    enviando: false,
    error: null
  };

  const notificar = () => oyentes.forEach((fn) => fn(estado));

  function ordenarRecursos(lista) {
    return (lista || []).slice().sort((a, b) => {
      const pa = typeof a.posicion === 'number' ? a.posicion : 0;
      const pb = typeof b.posicion === 'number' ? b.posicion : 0;
      if (pa !== pb) return pa - pb;
      return (a.orden || 0) - (b.orden || 0);
    });
  }

  /* Función única que lee multimedia_habilitada de la respuesta del servidor
     y actualiza tanto el store como el botón de imagen de la barra. */
  function actualizarDisponibilidadRecursos(resp) {
    if (resp && typeof resp.multimedia_habilitada === 'boolean') {
      estado.multimedia_habilitada = resp.multimedia_habilitada;
    } else if (!resp) {
      estado.multimedia_habilitada = false;
    }
    const habilitado = Boolean(estado.multimedia_habilitada === true);
    if (typeof document !== 'undefined' && document.getElementById) {
      const btnImg = document.getElementById('btnImagenToolbar');
      if (btnImg) {
        const esEnriq = Boolean(estado.borrador && estado.borrador.modo === 'enriquecimiento');
        const pr = document.getElementById('preview');
        const btnPr = document.getElementById('btnPreview');
        const previewActiva = Boolean((pr && !pr.hidden) || (btnPr && btnPr.classList.contains('sel')));

        let deshab;
        if (esEnriq && previewActiva) {
          deshab = !habilitado || Boolean(estado.enviando);
          btnImg.title = !deshab ? 'Agregar imagen al borrador' : TOOLTIP_IMAGEN_DESHABILITADA;
        } else {
          deshab = !habilitado || Boolean(estado.enviando);
          btnImg.title = habilitado ? 'Insertar imagen' : TOOLTIP_IMAGEN_DESHABILITADA;
        }
        btnImg.disabled = deshab;
        btnImg.setAttribute('aria-disabled', String(deshab));
      }
    }
    return habilitado;
  }

  function sincronizarEstructuraBorrador(b) {
    if (!b) return;
    const recsRaw = Array.isArray(b.recursos)
      ? b.recursos
      : (Array.isArray(b.multimedia) ? b.multimedia : Object.values(b.recursos || {}));
    const ordenados = ordenarRecursos(recsRaw);
    b.multimedia = ordenados;
    b.recursos = ordenados;
    if (!Array.isArray(b.bloques_texto) || !b.bloques_texto.length) {
      b.bloques_texto = [b.texto_limpio || ''];
    }
  }

  return {
    get: () => estado,
    suscribir(fn) { oyentes.push(fn); fn(estado); },
    set(cambios) { Object.assign(estado, cambios); notificar(); },
    setForm(campos) { Object.assign(estado.form, campos); notificar(); },
    actualizarDisponibilidadRecursos,

    /* Aplica la respuesta de un turno del backend */
    aplicarTurno(r) {
      estado.session_id = r.session_id;
      estado.flujo = r.estado;
      if (r.etapa) {
        estado.etapa = {
          actual: Number(r.etapa.actual) || 1,
          total: Number(r.etapa.total) || 5,
          nombre: r.etapa.nombre || '',
          etapas: Array.isArray(r.etapa.etapas) && r.etapa.etapas.length
            ? r.etapa.etapas.slice()
            : ETAPAS_DEFAULT.slice()
        };
      }
      /* Sin `etapa` en la respuesta se conserva la anterior: el back la envía siempre. */
      const normalizarBoton = (b) => {
        if (typeof b === 'object' && b !== null) {
          return {
            accion: b.accion,
            label: b.label || (BACO.OPCIONES[b.accion] || {}).label || b.accion,
            estilo: b.estilo || (BACO.OPCIONES[b.accion] || {}).estilo || 'btn-ghost'
          };
        }
        const def = BACO.OPCIONES[b] || {};
        return { accion: b, label: def.label || b, estilo: def.estilo || 'btn-ghost' };
      };
      const rawOpciones = Array.isArray(r.opciones) ? r.opciones : [];
      if (Array.isArray(r.botones) && r.botones.length) {
        estado.botones = r.botones.map(normalizarBoton);
      } else if (rawOpciones.length) {
        estado.botones = rawOpciones.map(normalizarBoton);
      } else {
        estado.botones = [];
      }
      estado.opciones = rawOpciones.map(normalizarBoton);
      /* Navegación (volver, ver_articulo_final): va en el panel, no en los botones del chat. */
      estado.navegacion = Array.isArray(r.navegacion) ? r.navegacion.slice() : [];
      estado.navegacion_etiquetas = (r.navegacion_etiquetas && typeof r.navegacion_etiquetas === 'object')
        ? Object.assign({}, r.navegacion_etiquetas) : {};
      estado.editables = Array.isArray(r.editables) ? r.editables.slice() : [];
      estado.guardan_campos = Array.isArray(r.guardan_campos) ? r.guardan_campos.slice() : [];
      estado.accion_panel = r.accion_panel || null;
      estado.skills = r.skills || null;
      estado.tags_acumulados = Array.isArray(r.tags_acumulados)
        ? r.tags_acumulados.slice()
        : ((r.borrador && r.borrador.tags) ? r.borrador.tags.slice() : []);
      if (Array.isArray(r.categorias_disponibles) && r.categorias_disponibles.length) {
        estado.categorias_disponibles = r.categorias_disponibles.slice();
      }
      if (Array.isArray(r.tags_disponibles) && r.tags_disponibles.length) {
        estado.tags_disponibles = r.tags_disponibles.slice();
      }
      estado.coincidencias = r.coincidencias || [];
      estado.borrador = r.borrador || null;
      estado.texto_servidor = (typeof r.texto_limpio === 'string') ? r.texto_limpio
        : (r.borrador ? (r.borrador.texto_limpio || '') : '');
      estado.plantilla_pendiente = r.plantilla_pendiente || null;
      estado.validacion = r.validacion || null;
      estado.aviso_metadatos_heredados = r.aviso_metadatos_heredados || null;

      /* Única función autorizada para decidir disponibilidad de recursos */
      actualizarDisponibilidadRecursos(r);

      /* El borrador del backend es la fuente de verdad del formulario.
         Al enriquecer o actualizar, el texto se vuelca inmediatamente en el panel izquierdo.
         El editor trabaja SOLO sobre texto_limpio: los recursos multimedia viven aparte (mini panel). */
      if (r.borrador) {
        if (typeof r.skills_habilitadas === 'boolean' && r.borrador.skills_habilitadas === undefined) {
          r.borrador.skills_habilitadas = r.skills_habilitadas;
        }
        if (r.skills_motivo !== undefined && r.borrador.skills_motivo === undefined) {
          r.borrador.skills_motivo = r.skills_motivo;
        }
        sincronizarEstructuraBorrador(r.borrador);
        estado.form.titulo = r.borrador.titulo || '';
        estado.form.texto = r.borrador.texto_limpio || '';
        if (r.borrador.modo === 'enriquecimiento' || r.borrador.resultado_skill_pendiente === true) {
          estado.form.texto_editor = (typeof r.borrador.texto_editor === 'string')
            ? r.borrador.texto_editor
            : (estado.form.texto_editor || '');
        } else {
          estado.form.texto_editor = estado.form.texto;
        }
        estado.form.tags = (r.borrador.tags || []).slice();
        estado.form.categoria_id = (r.borrador.categoria_id && Number(r.borrador.categoria_id) > 1) ? Number(r.borrador.categoria_id) : null;
      } else {
        if (typeof r.titulo === 'string' && r.titulo) {
          estado.form.titulo = r.titulo;
        }
        if (typeof r.texto_limpio === 'string' && r.texto_limpio) {
          estado.form.texto_editor = r.texto_limpio;
          estado.form.texto = r.texto_limpio;
        } else if (!r.borrador && !r.texto_limpio && r.accion_panel && r.accion_panel.accion === 'confirmar_texto') {
          estado.form.texto_editor = '';
          estado.form.texto = '';
        }
        if (estado.tags_acumulados.length) {
          estado.form.tags = estado.tags_acumulados.slice();
        }
      }
      notificar();
    },

    /* Aplica el EstadoRecursosResponse unificado (o una lista directa por compatibilidad) */
    actualizarRecursos(res) {
      if (!res) return;
      if (res.borrador) {
        estado.borrador = res.borrador;
        sincronizarEstructuraBorrador(estado.borrador);
      }
      if (res.estado) {
        estado.flujo = res.estado;
      }
      if (!estado.borrador) return;
      const esObjetoEstado = !Array.isArray(res) && typeof res === 'object' &&
        (Array.isArray(res.recursos) || Array.isArray(res.bloques_texto));

      if (esObjetoEstado) {
        const recsOrdenados = ordenarRecursos(Array.isArray(res.recursos) ? res.recursos : []);
        estado.borrador.recursos = recsOrdenados.slice();
        estado.borrador.multimedia = recsOrdenados.slice();
        estado.borrador.orden_multimedia = recsOrdenados.map((_, i) => i);
        estado.borrador.posiciones = recsOrdenados.map((r) => (typeof r.posicion === 'number' ? r.posicion : 0));
        if (Array.isArray(res.bloques_texto) && res.bloques_texto.length) {
          estado.borrador.bloques_texto = res.bloques_texto.slice();
        }
        if (typeof res.texto_limpio === 'string') {
          estado.borrador.texto_limpio = res.texto_limpio;
          estado.form.texto = res.texto_limpio;
        } else if (Array.isArray(estado.borrador.bloques_texto)) {
          const derivado = estado.borrador.bloques_texto.map((b) => String(b || '').trim()).filter(Boolean).join('\n\n');
          estado.borrador.texto_limpio = derivado;
          estado.form.texto = derivado;
        }
        if (typeof res.skills_habilitadas === 'boolean') {
          estado.borrador.skills_habilitadas = res.skills_habilitadas;
        }
        if (res.skills_motivo !== undefined) {
          estado.borrador.skills_motivo = res.skills_motivo;
        }
        if (res.estado) {
          estado.flujo = res.estado;
        }
        if (typeof res.multimedia_habilitada === 'boolean') {
          actualizarDisponibilidadRecursos(res);
        }
      } else {
        const lista = Array.isArray(res) ? ordenarRecursos(res) : ordenarRecursos(Object.values(res || {}));
        const mapa = {};
        lista.forEach((r, i) => {
          const id = r.id || ('rec_' + (i + 1));
          mapa[id] = r;
        });
        estado.borrador.recursos = mapa;
        estado.borrador.multimedia = lista.slice();
        estado.borrador.orden_multimedia = lista.map((_, i) => i);
        estado.borrador.posiciones = lista.map((r, i) => (typeof r.posicion === 'number' ? r.posicion : i));
      }
      notificar();
    },

    reiniciarLocal() {
      estado.session_id = null; estado.flujo = 'ESPERANDO_TITULO';
      estado.skill_plantilla_aplicada = false;
      estado.etapa = {
        actual: 1,
        total: 5,
        nombre: ETAPAS_DEFAULT[0],
        etapas: ETAPAS_DEFAULT.slice()
      };
      estado.opciones = []; estado.botones = []; estado.tags_acumulados = [];
      estado.navegacion = []; estado.navegacion_etiquetas = {}; estado.editables = ['titulo'];
      estado.guardan_campos = [];
      estado.accion_panel = null; estado.skills = null;
      estado.coincidencias = [];
      estado.borrador = null; estado.validacion = null; estado.error = null;
      actualizarDisponibilidadRecursos({ multimedia_habilitada: false });
      estado.form = { titulo: '', texto: '', tags: [], categoria_id: null };
      notificar();
    }
  };
})();

BACO.actualizarDisponibilidadRecursos = BACO.store.actualizarDisponibilidadRecursos;


