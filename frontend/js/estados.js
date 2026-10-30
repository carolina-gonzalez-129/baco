/* =============================================================
   Máquina de estados del backend + store del panel
   -------------------------------------------------------------
   Los estados son los de EstadoFlujo
   (baco/server/schemas/chat_orquestado.py).

   EL BACKEND MANDA. El panel no calcula estados: refleja el
   `estado`, `etapa`, `tags_acumulados`, `categorias_disponibles`
   y `opciones` que devuelve cada turno.
   ============================================================= */
window.BACO = window.BACO || {};

BACO.ESTADOS = {
  ESPERANDO_TITULO:   { etiqueta: 'Esperando título',    tono: 'proceso', paso: 1,
                        ayuda: 'Escribí el título del artículo (mínimo 15 caracteres) y enviálo. BACO busca duplicados antes de seguir.' },
  DECISION_TITULO:    { etiqueta: 'Título duplicado',    tono: 'alerta',  paso: 1,
                        ayuda: 'Encontró un artículo con título parecido. Decidí si lo enriquecés o seguís con uno nuevo.' },
  ESPERANDO_TEXTO:    { etiqueta: 'Esperando contenido', tono: 'proceso', paso: 2,
                        ayuda: 'Escribí o pegá el cuerpo del artículo de a poco (máximo 16777 caracteres, skills disponibles hasta 6687) y tocá "Confirmar texto" cuando esté listo.' },
  DECISION_TEXTO:     { etiqueta: 'Contenido similar',   tono: 'alerta',  paso: 2,
                        ayuda: 'El contenido se parece a uno existente. Elegí si lo enriquecés o continuás con el tuyo.' },
  ESPERANDO_PLANTILLA:{ etiqueta: 'Elegir plantilla',    tono: 'proceso', paso: 3,
                        ayuda: 'Elegí qué plantilla aplicar: instructivo o soluciones.' },
  ESPERANDO_METADATOS:{ etiqueta: 'Faltan etiquetas',    tono: 'proceso', paso: 3,
                        ayuda: 'Agregá al menos un tag temático además del tipo de plantilla y elegí la categoría.' },
  REVISION_BORRADOR:  { etiqueta: 'En revisión',         tono: 'info',    paso: 4,
                        ayuda: 'El borrador está validado. Podés editarlo, sanitizarlo, confirmar tu conformidad o rechazarlo.' },
  SUBSANANDO_BORRADOR:{ etiqueta: 'Corrigiendo',          tono: 'alerta',  paso: 4,
                        ayuda: 'Hay observaciones bloqueantes. Corregilas en el panel y guardá los cambios.' },
  CONFORMIDAD_USUARIO:{ etiqueta: 'Conforme',            tono: 'ok',      paso: 5,
                        ayuda: 'El artículo quedó con tu conformidad registrada y sanitizado.' },
  APROBADO:           { etiqueta: 'Conforme',            tono: 'ok',      paso: 5,
                        ayuda: 'El artículo quedó con tu conformidad registrada y sanitizado.' },
  RECHAZADO:          { etiqueta: 'Rechazado',           tono: 'alerta',  paso: 5,
                        ayuda: 'El borrador fue rechazado. Reiniciá para empezar otra carga.' }
};

/* Qué campos del formulario están activos en cada estado */
BACO.CAMPOS_ACTIVOS = {
  ESPERANDO_TITULO:    { titulo: true,  texto: false, tags: false, categoria: false },
  DECISION_TITULO:     { titulo: false, texto: false, tags: false, categoria: false },
  ESPERANDO_TEXTO:     { titulo: false, texto: true,  tags: false, categoria: false },
  DECISION_TEXTO:      { titulo: false, texto: false, tags: false, categoria: false },
  ESPERANDO_PLANTILLA: { titulo: false, texto: false, tags: false, categoria: false },
  ESPERANDO_METADATOS: { titulo: false, texto: false, tags: true,  categoria: true },
  REVISION_BORRADOR:   { titulo: true,  texto: true,  tags: true,  categoria: true },
  SUBSANANDO_BORRADOR: { titulo: true,  texto: true,  tags: true,  categoria: true },
  CONFORMIDAD_USUARIO: { titulo: false, texto: false, tags: false, categoria: false },
  APROBADO:            { titulo: false, texto: false, tags: false, categoria: false },
  RECHAZADO:           { titulo: false, texto: false, tags: false, categoria: false }
};

/* Etiqueta y payload del botón principal, según el estado */
BACO.ACCION_PRINCIPAL = {
  ESPERANDO_TEXTO:     { label: 'Confirmar texto',    campo: 'texto'  },
  ESPERANDO_METADATOS: { label: 'Enviar datos',       campo: 'tags'   },
  REVISION_BORRADOR:   { label: 'Guardar cambios',    campo: 'todo'   },
  SUBSANANDO_BORRADOR: { label: 'Guardar cambios',    campo: 'todo'   }
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
  ver_articulo_final: { label: 'Ver artículo', estilo: 'btn-primary' },
  confirmar_texto:   { label: 'Confirmar texto',         estilo: 'btn-primary' },
  quitar_recursos:   { label: 'Quitar recursos (usar skills)',    estilo: 'btn-dark' },
  seguir_con_recursos: { label: 'Seguir con recursos (sin skills)', estilo: 'btn-ghost' },
  enriquecer:        { label: 'Enriquecer el existente', estilo: 'btn-dark' },
  actualizar:        { label: 'Actualizar el existente', estilo: 'btn-dark' },
  descartar:         { label: 'Es un tema distinto',     estilo: 'btn-ghost' },
  continuar:         { label: 'Continuar con mi texto',  estilo: 'btn-ghost' },
  instructivo:       { label: 'Instructivo',             estilo: 'btn-dark' },
  soluciones:        { label: 'Soluciones',              estilo: 'btn-dark' },
  conforme:          { label: 'Estoy conforme',          estilo: 'btn-primary' },
  aprobar:           { label: 'Estoy conforme',          estilo: 'btn-primary' },
  editar:            { label: 'Seguir editando',         estilo: 'btn-ghost' },
  seguir_editando:   { label: 'Seguir editando',         estilo: 'btn-ghost' },
  copiar_borrador:   { label: 'Copiar borrador',         estilo: 'btn-primary' },
  sanitizar:         { label: 'Sanitizar',               estilo: 'btn-ghost' },
  rechazar:          { label: 'Descartar borrador',      estilo: 'btn-ghost' },
  confirmar_rechazo: { label: 'Sí, descartar',           estilo: 'btn-peligro' },
  volver:            { label: '← Volver',                estilo: 'btn-ghost' },
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
    tags_acumulados: [],
    categorias_disponibles: [],
    tags_disponibles: [],
    coincidencias: [],
    borrador: null,
    validacion: null,
    multimedia_habilitada: false,

    /* lo que el usuario está escribiendo, antes de enviarlo */
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
        const estadosPermitidos = ['ESPERANDO_TEXTO', 'ESPERANDO_PLANTILLA', 'ESPERANDO_METADATOS', 'REVISION_BORRADOR', 'SUBSANANDO_BORRADOR', 'CONFORMIDAD_USUARIO'];

        let deshab;
        if (esEnriq && previewActiva) {
          deshab = !estadosPermitidos.includes(estado.flujo) || Boolean(estado.enviando);
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
    const recsRaw = Array.isArray(b.multimedia)
      ? b.multimedia
      : (Array.isArray(b.recursos) ? b.recursos : Object.values(b.recursos || {}));
    const ordenados = ordenarRecursos(recsRaw);
    b.multimedia = ordenados;
    const mapa = {};
    ordenados.forEach((r, idx) => {
      const id = r.id || ('rec_' + (idx + 1));
      mapa[id] = r;
    });
    b.recursos = mapa;
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
      } else {
        let pasoFallback = (BACO.ESTADOS[r.estado] || {}).paso || 1;
        if (r.borrador && r.borrador.metadatos_anteriores && !r.borrador.metadatos_heredados_revisados && pasoFallback > 3) {
          pasoFallback = 3;
        }
        estado.etapa = {
          actual: pasoFallback,
          total: 5,
          nombre: ETAPAS_DEFAULT[pasoFallback - 1] || '',
          etapas: ETAPAS_DEFAULT.slice()
        };
      }
      estado.opciones = r.opciones || [];
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
        if (r.borrador.modo === 'enriquecimiento') {
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
        } else if (!r.borrador && !r.texto_limpio && r.estado === 'ESPERANDO_TEXTO') {
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
      if (!estado.borrador) return;
      const esObjetoEstado = res && !Array.isArray(res) && typeof res === 'object' &&
        (Array.isArray(res.recursos) || Array.isArray(res.bloques_texto));

      if (esObjetoEstado) {
        const recsOrdenados = ordenarRecursos(res.recursos || []);
        const mapa = {};
        recsOrdenados.forEach((r, i) => {
          const id = r.id || ('rec_' + (i + 1));
          mapa[id] = r;
        });
        estado.borrador.recursos = mapa;
        estado.borrador.multimedia = recsOrdenados;
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
        if (res.borrador && typeof res.borrador.conforme === 'boolean') {
          estado.borrador.conforme = res.borrador.conforme;
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
      estado.etapa = {
        actual: 1,
        total: 5,
        nombre: ETAPAS_DEFAULT[0],
        etapas: ETAPAS_DEFAULT.slice()
      };
      estado.opciones = []; estado.tags_acumulados = [];
      estado.coincidencias = [];
      estado.borrador = null; estado.validacion = null; estado.error = null;
      actualizarDisponibilidadRecursos({ multimedia_habilitada: false });
      estado.form = { titulo: '', texto: '', tags: [], categoria_id: null };
      notificar();
    }
  };
})();

BACO.actualizarDisponibilidadRecursos = BACO.store.actualizarDisponibilidadRecursos;

/* Porcentaje de avance del flujo, dictado por etapa del servidor */
BACO.avance = function (s) {
  const actual = (s.etapa && s.etapa.actual) || (BACO.ESTADOS[s.flujo] || {}).paso || 1;
  const total = (s.etapa && s.etapa.total) || 5;
  return Math.min(100, Math.round((actual / total) * 100));
};
