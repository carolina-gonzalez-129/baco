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
                        ayuda: 'Escribí el cuerpo del artículo (mínimo 20 caracteres) y enviálo.' },
  DECISION_TEXTO:     { etiqueta: 'Contenido similar',   tono: 'alerta',  paso: 2,
                        ayuda: 'El contenido se parece a uno existente. Elegí si lo enriquecés o continuás con el tuyo.' },
  ESPERANDO_PLANTILLA:{ etiqueta: 'Elegir plantilla',    tono: 'proceso', paso: 3,
                        ayuda: 'Elegí qué plantilla aplicar: instructivo o soluciones.' },
  ESPERANDO_METADATOS:{ etiqueta: 'Faltan etiquetas',    tono: 'proceso', paso: 3,
                        ayuda: 'Agregá al menos un tag temático además del tipo de plantilla y elegí la categoría.' },
  REVISION_BORRADOR:  { etiqueta: 'En revisión',         tono: 'info',    paso: 4,
                        ayuda: 'El borrador está validado. Podés editarlo, sanitizarlo, aprobarlo o rechazarlo.' },
  SUBSANANDO_BORRADOR:{ etiqueta: 'Corrigiendo',          tono: 'alerta',  paso: 4,
                        ayuda: 'Hay observaciones bloqueantes. Corregilas en el panel y guardá los cambios.' },
  APROBADO:           { etiqueta: 'Aprobado',            tono: 'ok',      paso: 5,
                        ayuda: 'El artículo quedó aprobado y sanitizado, listo para publicar.' },
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
  APROBADO:            { titulo: false, texto: false, tags: false, categoria: false },
  RECHAZADO:           { titulo: false, texto: false, tags: false, categoria: false }
};

/* Etiqueta y payload del botón principal, según el estado */
BACO.ACCION_PRINCIPAL = {
  ESPERANDO_TITULO:    { label: 'Buscar duplicados',  campo: 'titulo' },
  ESPERANDO_TEXTO:     { label: 'Enviar contenido',   campo: 'texto'  },
  ESPERANDO_METADATOS: { label: 'Enviar etiquetas',   campo: 'tags'   },
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
  enriquecer:        { label: 'Enriquecer el existente', estilo: 'btn-dark' },
  actualizar:        { label: 'Actualizar el existente', estilo: 'btn-dark' },
  descartar:         { label: 'Es un tema distinto',     estilo: 'btn-ghost' },
  continuar:         { label: 'Continuar con mi texto',  estilo: 'btn-ghost' },
  instructivo:       { label: 'Instructivo',             estilo: 'btn-dark' },
  soluciones:        { label: 'Soluciones',              estilo: 'btn-dark' },
  aprobar:           { label: 'Aprobar',                 estilo: 'btn-primary' },
  editar:            { label: 'Editar',                  estilo: 'btn-ghost' },
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
  const ETAPAS_DEFAULT = ['Título y duplicados', 'Contenido', 'Plantilla y etiquetas', 'Revisión', 'Aprobación'];

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

    /* lo que el usuario está escribiendo, antes de enviarlo */
    form: { titulo: '', texto: '', tags: [], categoria_id: 1 },

    enviando: false,
    error: null
  };

  const notificar = () => oyentes.forEach((fn) => fn(estado));

  return {
    get: () => estado,
    suscribir(fn) { oyentes.push(fn); fn(estado); },
    set(cambios) { Object.assign(estado, cambios); notificar(); },
    setForm(campos) { Object.assign(estado.form, campos); notificar(); },

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
        const pasoFallback = (BACO.ESTADOS[r.estado] || {}).paso || 1;
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

      /* El borrador del backend es la fuente de verdad del formulario */
      if (r.borrador) {
        estado.form.titulo = r.borrador.titulo || '';
        estado.form.texto = r.borrador.texto || '';
        estado.form.tags = (r.borrador.tags || []).slice();
        estado.form.categoria_id = r.borrador.categoria_id || 1;
      } else if (estado.tags_acumulados.length) {
        estado.form.tags = estado.tags_acumulados.slice();
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
      estado.form = { titulo: '', texto: '', tags: [], categoria_id: 1 };
      notificar();
    }
  };
})();

/* Porcentaje de avance del flujo, dictado por etapa del servidor */
BACO.avance = function (s) {
  const actual = (s.etapa && s.etapa.actual) || (BACO.ESTADOS[s.flujo] || {}).paso || 1;
  const total = (s.etapa && s.etapa.total) || 5;
  return Math.min(100, Math.round((actual / total) * 100));
};
