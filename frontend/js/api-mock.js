/* =============================================================
   Implementación SIMULADA
   -------------------------------------------------------------
   Emula el orquestador de Caro en paridad con el servidor real:
     · bloques_texto es la fuente de verdad en el borrador
     · texto_limpio es derivado (sin marcadores [[recurso:...]])
     · cada recurso tiene posicion (-1..len(bloques_texto)-1) y orden (0..N-1)
     · texto_alineado_discourse intercala bloques_texto y recursos
     · multimedia_habilitada lo decide el servidor tras deduplicación
     · GET/POST/PUT/DELETE de /chat/recursos devuelven el esquema unificado
     · POST /chat/recursos acepta bloques_texto y posicion de forma atómica

   Mismas firmas que api-http.js: la UI no sabe cuál corre.
   ============================================================= */
window.BACO = window.BACO || {};

BACO.apiMock = (function () {
  'use strict';

  const cfg = () => BACO.config.mock;
  const lim = () => BACO.config;
  let sesion = null;

  const BIENVENIDA = 'Hola, soy Baco. Te acompaño en la carga de documentación a la base de conocimiento ' +
    'de Finnegans. Contame, ¿sobre qué te gustaría publicar?';

  const OPS = {
    ENRIQUECER_DESCARTAR: ['enriquecer', 'descartar', 'volver'],
    SERIE_DECISION:       ['actualizar', 'descartar', 'volver'],
    ENRIQUECER_CONTINUAR: ['enriquecer', 'continuar', 'volver'],
    PLANTILLAS:           ['instructivo', 'soluciones', 'volver'],
    REVISION_VALIDO:      ['conforme', 'editar', 'rechazar'],
    REVISION_BLOQUEANTE:  ['editar', 'rechazar'],
    REINICIAR:            ['reiniciar']
  };

  const ESTADOS_SIN_MULTIMEDIA = new Set([
    'ESPERANDO_TITULO',
    'DECISION_TITULO',
    'DECISION_TEXTO',
    'RECHAZADO'
  ]);

  const MAX_RECURSOS = 20;
  const MAX_BLOQUES = 21;
  const MAX_ARCHIVO_BYTES = 10 * 1024 * 1024;
  const MAX_SESION_BYTES = 50 * 1024 * 1024;
  const MAX_SKILLS_CHARS = 6687;

  function cpLen(s) {
    return Array.from(String(s || '')).length;
  }

  function err(codigo, mensaje, http) {
    const e = new Error(mensaje);
    e.codigo = codigo;
    if (http) e.http = http;
    return e;
  }

  function responder(fn, ms) {
    return new Promise((resolve, reject) => {
      setTimeout(() => {
        if (Math.random() < cfg().TASA_ERROR) {
          return reject(err('ERROR_INTERNO', 'Falla simulada del backend. Reintentá.'));
        }
        try { resolve(fn()); } catch (e) { reject(e); }
      }, ms === undefined ? cfg().LATENCIA_MS : ms);
    });
  }

  const uuid = () => 'sim-' + Math.random().toString(36).slice(2, 10);

  function nuevaSesion() {
    return {
      session_id: uuid(), estado: 'ESPERANDO_TITULO',
      titulo: '', texto: '', categoria_id: lim().CATEGORIA_DEFAULT || 1, tags: [],
      coincidencias: [], borrador: null, validacion: null,
      historial: []   // para poder volver
    };
  }

  /* ---------------------------------------------------------
     Helpers de bloques_texto, recursos e invariantes
     --------------------------------------------------------- */
  function aMarkdownRecurso(r) {
    const n = r.nombre || 'Recurso';
    const ref = r.referencia || r.url || '';
    if (r.tipo === 'imagen') return '![' + n + '](' + ref + ')';
    if (r.tipo === 'documento' && (/\/uploads\//.test(ref) || /\/api\/recursos-temp\//.test(ref) || /\.(pdf|zip|docx)$/i.test(ref))) {
      return '[' + n + '|attachment](' + ref + ')';
    }
    return '[' + n + '](' + ref + ')';
  }

  function ordenarRecursosInvariante(lista, numBloques) {
    const maxPos = Math.max(0, (numBloques || 1) - 1);
    const copia = (lista || []).map((r) => {
      const posRaw = typeof r.posicion === 'number' ? r.posicion : maxPos;
      const posClamp = Math.max(-1, Math.min(maxPos, posRaw));
      return Object.assign({}, r, { posicion: posClamp });
    });
    copia.sort((a, b) => {
      if (a.posicion !== b.posicion) return a.posicion - b.posicion;
      return (a.orden || 0) - (b.orden || 0);
    });
    copia.forEach((r, idx) => { r.orden = idx; });
    return copia;
  }

  function sincronizarBorrador(b) {
    if (!b) return null;
    if (!Array.isArray(b.bloques_texto) || !b.bloques_texto.length) {
      b.bloques_texto = [String(b.texto_limpio != null ? b.texto_limpio : (b.texto || ''))];
    }
    const recsRaw = Array.isArray(b.multimedia) && b.multimedia.length
      ? b.multimedia
      : Object.values(b.recursos || {});
    const recsOrd = ordenarRecursosInvariante(recsRaw, b.bloques_texto.length);
    const mapa = {};
    recsOrd.forEach((r, idx) => {
      if (!r.id) r.id = 'rec_' + (idx + 1);
      mapa[r.id] = r;
    });
    b.recursos = mapa;
    b.multimedia = recsOrd;
    b.orden_multimedia = recsOrd.map((_, i) => i);
    b.posiciones = recsOrd.map((r) => r.posicion);

    const derivado = b.bloques_texto
      .map((bl) => String(bl || '').trim())
      .filter(Boolean)
      .join('\n\n');
    b.texto_limpio = derivado;
    b.texto = derivado;

    // Componer texto_alineado_discourse intercalado
    const partes = [];
    recsOrd.filter((r) => r.posicion === -1).forEach((r) => partes.push(aMarkdownRecurso(r)));
    for (let i = 0; i < b.bloques_texto.length; i++) {
      const t = String(b.bloques_texto[i] || '').trim();
      if (t) partes.push(t);
      recsOrd.filter((r) => r.posicion === i).forEach((r) => partes.push(aMarkdownRecurso(r)));
    }
    if (Array.isArray(b.contenido_adicional) && b.contenido_adicional.length) {
      b.contenido_adicional.forEach((it) => {
        if (it && it.contenido) partes.push(String(it.contenido).trim());
      });
    }
    b.texto_alineado_discourse = partes.join('\n\n').trim();

    if (recsOrd.length > 0) {
      b.skills_habilitadas = false;
      b.skills_motivo = 'El artículo contiene recursos multimedia cargados. Quitá los recursos si querés aplicar la plantilla o el validador automático.';
    } else if (cpLen(b.texto_limpio) > MAX_SKILLS_CHARS) {
      b.skills_habilitadas = false;
      b.skills_motivo = 'El texto supera el máximo de ' + MAX_SKILLS_CHARS + ' caracteres para las skills del agente.';
    } else {
      b.skills_habilitadas = true;
      b.skills_motivo = null;
    }
    return b;
  }

  function multimediaHabilitadaActual() {
    if (!sesion || !sesion.borrador) return false;
    return !ESTADOS_SIN_MULTIMEDIA.has(sesion.estado);
  }

  function construirEstadoRecursosMock() {
    if (!sesion || !sesion.borrador) {
      return {
        bloques_texto: [''],
        recursos: [],
        texto_limpio: '',
        multimedia_habilitada: false,
        skills_habilitadas: true,
        skills_motivo: null
      };
    }
    sincronizarBorrador(sesion.borrador);
    return {
      bloques_texto: sesion.borrador.bloques_texto.slice(),
      recursos: sesion.borrador.multimedia.slice(),
      texto_limpio: sesion.borrador.texto_limpio,
      multimedia_habilitada: multimediaHabilitadaActual(),
      skills_habilitadas: sesion.borrador.skills_habilitadas,
      skills_motivo: sesion.borrador.skills_motivo
    };
  }

  function extraerBloquesYRecursosDeTextoExistente(textoOriginal) {
    const src = String(textoOriginal || '').trim();
    if (!src) return { bloques_texto: [''], recursos: [] };
    const regexImg = /!\[([^\]]*)\]\((https?:\/\/[^\s\)]+)\)/g;
    if (!regexImg.test(src)) {
      return { bloques_texto: [src], recursos: [] };
    }
    const bloques = [];
    const recursos = [];
    let lastIndex = 0;
    let m;
    const re = /!\[([^\]]*)\]\((https?:\/\/[^\s\)]+)\)/g;
    let rIdx = 1;
    while ((m = re.exec(src)) !== null) {
      const previo = src.slice(lastIndex, m.index).trim();
      if (previo || bloques.length === 0) {
        if (previo) bloques.push(previo);
      }
      const pos = bloques.length - 1;
      recursos.push({
        id: 'rec_' + rIdx,
        tipo: 'imagen',
        nombre: m[1] || ('Imagen ' + rIdx),
        referencia: m[2],
        origen: 'existente',
        posicion: pos,
        orden: rIdx - 1
      });
      rIdx++;
      lastIndex = m.index + m[0].length;
    }
    const resto = src.slice(lastIndex).trim();
    if (resto || bloques.length === 0) {
      bloques.push(resto);
    }
    return { bloques_texto: bloques, recursos: ordenarRecursosInvariante(recursos, bloques.length) };
  }

  /* ---------------------------------------------------------
     Búsqueda de duplicados simulada, con tipo y score
     --------------------------------------------------------- */
  function normalizar(t) {
    return String(t || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u306f]/g, '')
      .replace(/[^\w\s]/g, ' ').split(/\s+/).filter((p) => p.length > 3);
  }

  function buscar(consulta) {
    const terminos = normalizar(consulta);
    if (!terminos.length) return null;
    let mejor = null, mejorScore = 0;
    BACO.datos.baseConocimiento.forEach((a) => {
      const texto = normalizar(a.titulo + ' ' + a.claves.join(' ') + ' ' + a.categoria);
      let hits = 0;
      terminos.forEach((t) => {
        if (texto.some((p) => p.startsWith(t.slice(0, 5)) || t.startsWith(p.slice(0, 5)))) hits++;
      });
      const score = hits ? Math.min(0.94, 0.52 + hits * 0.06) : 0;
      if (score > mejorScore) { mejorScore = score; mejor = a; }
    });
    if (mejorScore < 0.6) return null;
    const tipo = mejorScore >= 0.9 ? 'semantico' : (mejorScore >= 0.7 ? 'trigrama' : 'serie');
    return {
      id: mejor.id_externo, titulo: mejor.titulo,
      url: 'https://bc-dev.finneg.com/t/' + mejor.id_externo,
      score: Number(mejorScore.toFixed(2)),
      tipo_coincidencia: tipo,
      texto_original: mejor.extracto
    };
  }

  /* ---------------------------------------------------------
     Sanitización y validación
     --------------------------------------------------------- */
  const RE_CUIT = /\b(?:20|23|24|27)-?\d{8}-?\d\b/;
  const RE_CUIL_CONTEXTO = /(?:\b(?:cuil|cuit)(?:\s+(?:nro|n[uú]mero))?[\s:=#]+)(?:20|23|24|27)[-.\s]?\d{8}[-.\s]?\d\b/i;
  const RE_DNI_CONTEXTO = /(?:\b(?:dni|documento)(?:\s+(?:nro|n[uú]mero))?[\s:=#]+)\d{7,8}\b/i;
  const RE_MAIL = /\b[\w.+-]+@[\w-]+\.[\w.]+\b/;

  function sanitizar(texto, titulo) {
    let t = String(texto || ''), cambios = [];
    if (RE_CUIL_CONTEXTO.test(t)) {
      t = t.replace(new RegExp(RE_CUIL_CONTEXTO.source, 'gi'), function(m) {
        var sep = m.match(/^[\s\S]*?[\s:=#]+/i);
        return (sep ? sep[0] : '') + '[CUIT_OCULTO]';
      });
      cambios.push('CUIT/CUIL');
    }
    if (RE_CUIT.test(t)) { t = t.replace(new RegExp(RE_CUIT.source, 'g'), '[CUIT_OCULTO]'); cambios.push('CUIT'); }
    if (RE_DNI_CONTEXTO.test(t)) {
      t = t.replace(new RegExp(RE_DNI_CONTEXTO.source, 'gi'), function(m) {
        var sep = m.match(/^[\s\S]*?[\s:=#]+/i);
        return (sep ? sep[0] : '') + '[DOCUMENTO_OCULTO]';
      });
      cambios.push('DNI');
    }
    if (RE_MAIL.test(t)) { t = t.replace(new RegExp(RE_MAIL.source, 'g'), 'usuario@ejemplo.com'); cambios.push('correo electrónico'); }
    let ti = String(titulo || '').replace(/^(c[oó]mo|como)\s+/i, '').trim();
    if (ti) ti = ti.charAt(0).toUpperCase() + ti.slice(1);
    return { texto_sanitizado: t, titulo_sanitizado: ti, cambios: cambios };
  }

  function sanitizarBloques(bloques, titulo) {
    const cambiosSet = new Set();
    const sanitizados = (bloques || ['']).map((bl) => {
      const res = sanitizar(String(bl || ''), titulo);
      res.cambios.forEach((c) => cambiosSet.add(c));
      return res.texto_sanitizado;
    });
    const titRes = sanitizar('', titulo);
    return {
      bloques_sanitizados: sanitizados.length ? sanitizados : [''],
      titulo_sanitizado: titRes.titulo_sanitizado,
      cambios: Array.from(cambiosSet)
    };
  }

  function avisoPrivacidad(cambios) {
    if (!cambios.length) return null;
    return 'Por seguridad, se detectaron y reemplazaron automáticamente datos personales (' + cambios.join(' y ') + ') por valores genéricos para preservarte. ' +
      'Revisá que el reemplazo no haya cambiado el sentido del texto.';
  }

  function validar(b) {
    b = b || {};
    const findings = [];
    let titulo = b.titulo || '', tags = b.tags || [];
    const L = lim();

    // Autosanitización sobre bloques_texto
    const origenBloques = Array.isArray(b.bloques_texto) && b.bloques_texto.length
      ? b.bloques_texto
      : [b.texto_limpio != null ? b.texto_limpio : (b.texto || '')];
    const limpio = sanitizarBloques(origenBloques, titulo);
    b.bloques_texto = limpio.bloques_sanitizados;
    if (limpio.cambios.length > 0) {
      b.titulo = limpio.titulo_sanitizado;
      titulo = limpio.titulo_sanitizado;
      findings.push({
        severity: 'Sugerencia',
        field: 'texto',
        description: 'Por seguridad, se detectaron y reemplazaron automáticamente datos personales (' + limpio.cambios.join(', ') + ') por marcadores genéricos para preservarte.',
        action: 'Revisar que el contenido conserve el sentido técnico tras el reemplazo automático.'
      });
    }
    sincronizarBorrador(b);
    const texto = b.texto_limpio || '';
    const lenTit = cpLen(titulo);
    const lenTxt = cpLen(texto);

    if (lenTit < L.MIN_TITULO || lenTit > L.MAX_TITULO) {
      findings.push({ severity: 'Bloqueante', field: 'titulo',
        description: 'El título debe tener entre ' + L.MIN_TITULO + ' y ' + L.MAX_TITULO + ' caracteres (actual: ' + lenTit + ').',
        action: 'Ajustar la longitud del título.' });
    }
    if (lenTxt < L.MIN_TEXTO) {
      findings.push({ severity: 'Bloqueante', field: 'texto',
        description: 'El texto debe tener al menos ' + L.MIN_TEXTO + ' caracteres (actual: ' + lenTxt + ').',
        action: 'Ampliar el contenido del artículo.' });
    }
    if (lenTxt > L.MAX_TEXTO_PERCENTIL_99) {
      findings.push({ severity: 'Bloqueante', field: 'texto',
        description: 'El texto supera los ' + L.MAX_TEXTO_PERCENTIL_99 + ' caracteres (actual: ' + lenTxt + ').',
        action: 'Dividir el artículo o resumirlo.' });
    }
    if (/\[Indicar[^\]]*\]/i.test(texto)) {
      findings.push({ severity: 'Bloqueante', field: 'texto',
        description: 'Quedaron marcadores pendientes del tipo [Indicar...] sin completar.',
        action: 'Completar o quitar los marcadores a mano antes de dar conformidad.' });
    }
    if (tags.length > L.MAX_TAGS) {
      findings.push({ severity: 'Bloqueante', field: 'tags',
        description: 'El artículo tiene ' + tags.length + ' etiquetas y el máximo es ' + L.MAX_TAGS + '.',
        action: 'Quitar las etiquetas menos relevantes.' });
    }
    if (/^(c[oó]mo|como)\s/i.test(titulo)) {
      findings.push({ severity: 'Ajuste', field: 'titulo',
        description: 'El título empieza con "Cómo", que es redundante según las pautas.',
        action: 'Comenzar con un verbo en infinitivo.' });
    }
    if (/\berror\b/i.test(titulo) && !/["“][^"”]*error[^"”]*["”]/i.test(titulo)) {
      findings.push({ severity: 'Ajuste', field: 'titulo',
        description: 'Se usa la palabra "Error" fuera de comillas.',
        action: 'Usar "Mensaje" o "Aviso", salvo que sea textual del sistema.' });
    }
    if (!/ruta\s*[:>]/i.test(texto) && lenTxt > 100) {
      findings.push({ severity: 'Sugerencia', field: 'texto',
        description: 'No se indicó la ruta de acceso con el símbolo >.',
        action: 'Agregar «Ruta> Menú > ...» para orientar al lector.' });
    }
    if (tags.length < L.MIN_TAGS) {
      findings.push({ severity: 'Bloqueante', field: 'tags',
        description: 'El artículo tiene menos de ' + L.MIN_TAGS + ' etiquetas.',
        action: 'Agregar al menos ' + L.MIN_TAGS + ' etiquetas requeridas.' });
    }
    if (!b.categoria_id || Number(b.categoria_id) <= 1) {
      findings.push({ severity: 'Bloqueante', field: 'categoria_id',
        description: 'El artículo debe tener asignada una categoría principal (no puede quedar "Sin categoría").',
        action: 'Seleccionar una categoría del catálogo oficial.' });
    }

    const bloqueantes = findings.filter((f) => f.severity === 'Bloqueante').length;
    return {
      valido: bloqueantes === 0,
      fase: 'fase_2_texto_y_estructura',
      status: bloqueantes === 0 ? 'Listo' : 'Pendiente',
      titulo_sanitizado: limpio.titulo_sanitizado,
      texto_sanitizado: b.texto_limpio,
      findings: findings,
      resumen: { longitud_texto: lenTxt, tags_count: tags.length }
    };
  }

  /* ---------------------------------------------------------
     Helpers de flujo
     --------------------------------------------------------- */
  function tipoPlantilla(tags, opcion) {
    const cands = [String(opcion || '').toLowerCase()].concat((tags || []).map((t) => String(t).toLowerCase()));
    for (const c of cands) {
      if (c === 'instructivo' || c === 'instructivos') return 'instructivo';
      if (c === 'soluciones' || c === 'solucion' || c === 'solución') return 'soluciones';
    }
    return null;
  }

  function combinarTags(plantilla, ...listas) {
    const out = [], vistos = new Set();
    if (plantilla) { out.push(plantilla); vistos.add(plantilla.toLowerCase()); }
    listas.forEach((l) => (l || []).forEach((t) => {
      const limpio = String(t).trim(); if (!limpio) return;
      const k = limpio.toLowerCase();
      if (plantilla === 'instructivo' && (k === 'instructivo' || k === 'instructivos')) return;
      if (plantilla === 'soluciones' && (k === 'soluciones' || k === 'solucion' || k === 'solución')) return;
      if (!vistos.has(k)) { vistos.add(k); out.push(limpio); }
    }));
    return out;
  }

  function interpretar(req) {
    const bruto = String(req.accion || req.mensaje || '').trim().toLowerCase();
    const mapa = {
      'si': 'enriquecer', 'sí': 'enriquecer', '1': 'enriquecer', 'enriquecer': 'enriquecer',
      'actualizar': 'actualizar', 'actualizo': 'actualizar',
      'no': 'descartar', '2': 'descartar', 'descartar': 'descartar', 'continuar': 'continuar',
      'confirmar_texto': 'confirmar_texto', 'confirmar texto': 'confirmar_texto',
      'quitar_recursos': 'quitar_recursos', 'quitar recursos': 'quitar_recursos',
      'seguir_con_recursos': 'seguir_con_recursos', 'seguir con recursos': 'seguir_con_recursos', 'continuar_con_recursos': 'seguir_con_recursos',
      'conforme': 'conforme', 'estoy conforme': 'conforme', 'aprobar': 'conforme', 'apruebo': 'conforme', 'confirmar': 'conforme', 'omitir': 'conforme',
      'copiar borrador': 'copiar_borrador', 'copiar_borrador': 'copiar_borrador', 'copiar': 'copiar_borrador',
      'rechazar': 'rechazar', 'rechazo': 'rechazar', 'cancelar': 'rechazar',
      'confirmar_rechazo': 'confirmar_rechazo', 'confirmar rechazo': 'confirmar_rechazo',
      'sanitizar': 'sanitizar', 'editar': 'editar', 'corregir': 'editar', 'seguir editando': 'editar', 'seguir_editando': 'editar',
      'reiniciar': 'reiniciar', 'cambiar tema': 'reiniciar',
      'volver': 'volver', 'atras': 'volver', 'atrás': 'volver', 'regresar': 'volver', 'anterior': 'volver',
      'ayuda': 'ayuda', 'opciones': 'ayuda', '?': 'ayuda',
      'instructivo': 'instructivo', 'instructivos': 'instructivo',
      'soluciones': 'soluciones', 'solucion': 'soluciones', 'solución': 'soluciones'
    };
    return mapa[bruto] || bruto;
  }

  const ETAPAS_FLUJO = [
    'Título y duplicados',
    'Contenido',
    'Plantilla y etiquetas',
    'Revisión',
    'Conformidad'
  ];

  const MAPA_ETAPAS = {
    ESPERANDO_TITULO: 1,
    DECISION_TITULO: 1,
    ESPERANDO_TEXTO: 2,
    DECISION_TEXTO: 2,
    ESPERANDO_PLANTILLA: 3,
    ESPERANDO_METADATOS: 3,
    REVISION_BORRADOR: 4,
    SUBSANANDO_BORRADOR: 4,
    CONFORMIDAD_USUARIO: 5,
    APROBADO: 5,
    RECHAZADO: 5
  };

  function resp(mensaje, opciones, aviso, avisoMeta) {
    const s = sesion;
    if (s.borrador) sincronizarBorrador(s.borrador);
    const actual = MAPA_ETAPAS[s.estado] || 1;
    const tagsAcum = s.borrador
      ? combinarTags(s.borrador.tipo_plantilla, s.borrador.tags, s.tags)
      : combinarTags(tipoPlantilla(s.tags), s.tags);
    const catsDisp = ((BACO.datos && BACO.datos.categorias) || []).map((c, idx) => ({
      id: typeof c.id === 'number' ? c.id : (idx + 1),
      nombre: c.nombre
    }));
    const tagsDisp = ((BACO.datos && BACO.datos.etiquetas) || []).map((e) => e.tag);
    const multiHab = multimediaHabilitadaActual();
    return {
      session_id: s.session_id,
      estado: s.estado,
      etapa: {
        actual: actual,
        total: ETAPAS_FLUJO.length,
        nombre: ETAPAS_FLUJO[actual - 1],
        etapas: ETAPAS_FLUJO.slice()
      },
      mensaje: mensaje,
      opciones: opciones || [],
      tags_acumulados: tagsAcum,
      categorias_disponibles: catsDisp,
      tags_disponibles: tagsDisp,
      coincidencias: (s.estado === 'DECISION_TITULO' || s.estado === 'DECISION_TEXTO') ? s.coincidencias : [],
      borrador: s.borrador ? JSON.parse(JSON.stringify(s.borrador)) : null,
      texto_limpio: s.borrador ? (s.borrador.texto_limpio != null ? s.borrador.texto_limpio : (s.borrador.texto || '')) : (s.texto_limpio || s.texto_en_edicion || s.texto || null),
      multimedia_habilitada: multiHab,
      skills_habilitadas: s.borrador ? s.borrador.skills_habilitadas : true,
      skills_motivo: s.borrador ? s.borrador.skills_motivo : null,
      validacion: s.validacion || null,
      aviso_privacidad: aviso || null,
      aviso_metadatos_heredados: avisoMeta || null
    };
  }

  /* Guarda un punto al que se pueda volver */
  function marcar() {
    sesion.historial.push(JSON.stringify({
      estado: sesion.estado, titulo: sesion.titulo, texto: sesion.texto,
      categoria_id: sesion.categoria_id, tags: sesion.tags,
      coincidencias: sesion.coincidencias, borrador: sesion.borrador
    }));
    if (sesion.historial.length > 12) sesion.historial.shift();
  }

  function volver() {
    if (!sesion.historial.length) {
      return resp('Ya estás en el primer paso, no hay nada atrás. Escribí el título del artículo.', []);
    }
    const prev = JSON.parse(sesion.historial.pop());
    Object.assign(sesion, prev);
    sesion.validacion = null;
    const guia = {
      ESPERANDO_TITULO: 'Volvimos al título. Escribí el título del artículo.',
      ESPERANDO_TEXTO: 'Volvimos al contenido. Ingresá el texto del artículo.',
      DECISION_TITULO: 'Volvimos a la decisión sobre el artículo parecido.',
      DECISION_TEXTO: 'Volvimos a la decisión sobre el contenido parecido.',
      ESPERANDO_PLANTILLA: 'Volvimos a la elección de plantilla.',
      ESPERANDO_METADATOS: 'Volvimos a las etiquetas.'
    }[sesion.estado] || 'Volvimos al paso anterior.';
    const ops = {
      DECISION_TITULO: OPS.ENRIQUECER_DESCARTAR,
      DECISION_TEXTO: OPS.ENRIQUECER_CONTINUAR,
      ESPERANDO_PLANTILLA: OPS.PLANTILLAS
    }[sesion.estado] || (sesion.historial.length ? ['volver'] : []);
    return resp(guia, ops);
  }

  function validarBorrador(prefijo) {
    const v = validar(sesion.borrador);
    sesion.validacion = v;
    sesion.estado = 'REVISION_BORRADOR';
    const detalle = v.findings.map((f) => '- [' + f.severity + '] ' + f.description + ' (' + f.action + ')').join('\n');
    if (!v.valido) {
      return { msg: (prefijo || '') + 'Encontré observaciones que frenan la publicación:\n' + detalle +
        '\nPodés editar el borrador acá mismo, o sanitizarlo si lo que sobra son datos sensibles.',
        ops: OPS.REVISION_BLOQUEANTE };
    }
    const obs = detalle ? '\nAdemás te dejo algunas sugerencias:\n' + detalle + '\n\n' : '\n\n';
    return { msg: (prefijo || '') + 'El borrador quedó validado (' + v.status + ').' + obs +
      'Revisá el borrador. Si estás conforme con el contenido, tocá Estoy conforme. Esto registra tu conformidad; no lo publica.', ops: OPS.REVISION_VALIDO };
  }

  function avanzar(prefijo, aviso) {
    const b = sesion.borrador;
    sincronizarBorrador(b);
    marcar();
    if (b.metadatos_anteriores && !b.metadatos_heredados_revisados) {
      const catNom = b.metadatos_anteriores.categoria_nombre || ('Categoría ' + b.metadatos_anteriores.categoria_id);
      const tagsStr = (b.metadatos_anteriores.tags || []).join(', ') || 'ninguna';
      const avisoMeta = 'El artículo en su versión anterior tenía asociada la categoría "' + catNom + '" y las etiquetas: [' + tagsStr + ']. ' +
        'Podés tocar "Aceptar" para conservar estos metadatos o "Rechazar" si preferís definirlos manualmente.';
      validarBorrador(prefijo);
      const ops = ['aceptar', 'rechazar'];
      return resp((prefijo || '') + 'Esperando confirmación o rechazo de los metadatos heredados en el panel izquierdo.', ops, aviso, avisoMeta);
    }

    const pl = b.tipo_plantilla || tipoPlantilla(b.tags);
    if (pl) { b.tipo_plantilla = pl; b.tags = combinarTags(pl, b.tags); }

    if (!b.tipo_plantilla) {
      sesion.estado = 'ESPERANDO_PLANTILLA';
      return resp((prefijo || '') + '¿Qué plantilla corresponde para este artículo: instructivo o soluciones?',
        OPS.PLANTILLAS, aviso);
    }
    const catValida = b.categoria_id != null && Number(b.categoria_id) > 1;
    if (b.tags.length < lim().MIN_TAGS || !catValida) {
      sesion.estado = 'ESPERANDO_METADATOS';
      return resp((prefijo || '') + 'Aplico la plantilla "' + b.tipo_plantilla + '". Ingresá al menos una etiqueta temática ' +
        'y seleccioná la categoría desde el menú desplegable en el formulario de la izquierda.',
        ['volver'], aviso);
    }
    const r = validarBorrador(prefijo);
    return resp(r.msg, r.ops, aviso);
  }

  function aplicarEdicionTextoEnBorrador(b, nuevoTexto) {
    const limpio = sanitizar(nuevoTexto, b.titulo);
    const txtSanit = limpio.cambios.length ? limpio.texto_sanitizado : String(nuevoTexto).trim();
    if (!Array.isArray(b.bloques_texto) || b.bloques_texto.length <= 1) {
      b.bloques_texto = [txtSanit];
    } else {
      // Si había múltiples bloques y la edición llega como texto plano único sin cambiar bloques,
      // mantenemos la cantidad de bloques o actualizamos si difiere
      const unidoActual = b.bloques_texto.map((x) => String(x || '').trim()).filter(Boolean).join('\n\n');
      if (txtSanit !== unidoActual) {
        const partes = txtSanit.split(/\n{2,}/);
        if (partes.length === b.bloques_texto.length) {
          b.bloques_texto = partes;
        } else {
          b.bloques_texto = [txtSanit];
        }
      }
    }
    sincronizarBorrador(b);
    return limpio;
  }

  /* =========================================================
     Endpoints
     ========================================================= */
  return {

    turno(req) {
      return responder(() => {
        req = req || {};
        if (!sesion) sesion = nuevaSesion();
        const opcion = interpretar(req);
        const L = lim();

        if (opcion === 'reiniciar') {
          sesion = nuevaSesion();
          return resp(BIENVENIDA, []);
        }
        if (opcion === 'volver') return volver();
        if (opcion === 'ayuda') {
          return resp('Estás en el paso "' + sesion.estado + '". Podés responder con texto, usar los botones, ' +
            'o escribir "volver" para retroceder y "reiniciar" para empezar de cero.', sesion.historial.length ? ['volver'] : []);
        }

        const entradaTitulo = String(req.titulo || req.mensaje || '').trim();
        if (sesion.estado === 'ESPERANDO_TITULO' && !entradaTitulo && !req.accion) {
          return resp(BIENVENIDA, []);
        }

        /* ---- ESPERANDO_TITULO ---- */
        if (sesion.estado === 'ESPERANDO_TITULO') {
          if (cpLen(entradaTitulo) < L.MIN_TITULO) {
            return resp('Necesito un título un poco más descriptivo: al menos ' + L.MIN_TITULO + ' caracteres.', []);
          }
          if (cpLen(entradaTitulo) > L.MAX_TITULO) {
            return resp('El título supera los ' + L.MAX_TITULO + ' caracteres. Resumilo.', []);
          }
          sesion.titulo = entradaTitulo;
          if (req.categoria_id != null) sesion.categoria_id = req.categoria_id;
          if (req.tags != null) sesion.tags = req.tags;

          const hit = buscar(entradaTitulo);
          if (hit) {
            marcar();
            sesion.coincidencias = [hit];
            sesion.estado = 'DECISION_TITULO';
            const esSerie = hit.tipo_coincidencia === 'serie';
            return resp('Encontré un artículo con título muy parecido: "' + hit.titulo + '" (' + hit.url + '). ' +
              (esSerie ? '¿Querés actualizarlo o es un tema distinto?' : '¿Querés enriquecer ese o seguís con uno nuevo?'),
              esSerie ? OPS.SERIE_DECISION : OPS.ENRIQUECER_DESCARTAR);
          }
          marcar();
          sesion.estado = 'ESPERANDO_TEXTO';
          return resp('No encontré nada parecido por título. Contame el contenido del artículo.', ['confirmar_texto', 'volver']);
        }

        /* ---- DECISION_TITULO ---- */
        if (sesion.estado === 'DECISION_TITULO') {
          if (opcion === 'enriquecer' || opcion === 'actualizar') {
            const el = sesion.coincidencias[0];
            const art = BACO.datos.baseConocimiento.find((a) => a.id_externo === el.id) || {};
            let textoBase = String(el.texto_original || art.extracto || '').trim();
            if (cpLen(textoBase) < L.MIN_TEXTO) {
              textoBase = 'Pasos para la configuración del artículo:\n1. Acceder al menú principal.\n2. Verificar parámetros del sistema.\n3. Guardar cambios y confirmar.';
            }
            const extraido = extraerBloquesYRecursosDeTextoExistente(textoBase);
            const textoEnviado = String(req.texto || '').trim();
            let avisoEnriq = null;
            let bloquesIni = extraido.bloques_texto.slice();
            if (textoEnviado) {
              const limpioEnv = sanitizar(textoEnviado, sesion.titulo);
              avisoEnriq = avisoPrivacidad(limpioEnv.cambios);
              bloquesIni = [limpioEnv.texto_sanitizado];
            }
            const tagsIni = req.tags != null ? req.tags : (art.etiquetas || sesion.tags);
            const esSerie = el.tipo_coincidencia === 'serie' || opcion === 'actualizar';
            const tituloFinal = (sesion.titulo || req.titulo || el.titulo).trim();
            const nomCat = art.categoria || 'Ventas';
            const metaAnt = { categoria_id: art.categoria_id || 5, categoria_nombre: nomCat, tags: tagsIni.slice() };
            sesion.borrador = {
              modo: 'enriquecimiento',
              articulo_original_id: el.id,
              articulo_original_url: el.url,
              titulo: tituloFinal,
              bloques_texto: bloquesIni,
              recursos: {},
              multimedia: extraido.recursos,
              orden_multimedia: [],
              posiciones: [],
              texto_original_aprobado: textoBase,
              tipo_plantilla: tipoPlantilla(tagsIni),
              categoria_id: req.categoria_id || sesion.categoria_id || 5,
              tags: tagsIni,
              metadatos_anteriores: metaAnt,
              metadatos_heredados_revisados: false,
              contenido_adicional: []
            };
            sincronizarBorrador(sesion.borrador);
            sesion.texto_en_edicion = sesion.borrador.texto_limpio;
            sesion.texto_limpio = sesion.borrador.texto_limpio;
            sesion.texto = sesion.borrador.texto_limpio;
            if (!textoEnviado) {
              marcar();
              sesion.estado = 'ESPERANDO_TEXTO';
              const msgCarga = esSerie
                ? 'Cargué el contenido de la última entrega de la serie (#' + el.id + ' - "' + el.titulo + '"). Tenés total libertad para trabajar sobre él: podés modificar lo que haya cambiado, eliminar lo que no aplique o adicionar novedades. Cuando esté listo, tocá "Confirmar texto".'
                : 'Cargué el texto del artículo #' + el.id + ' ("' + el.titulo + '"). Podés revisarlo, modificar explicaciones, eliminar secciones obsoletas o adicionar nuevos pasos. Cuando esté listo, tocá "Confirmar texto".';
              return resp(msgCarga, ['confirmar_texto', 'descartar', 'volver'], avisoEnriq);
            }
            return avanzar('Armé el borrador sobre #' + el.id + '. ', avisoEnriq);
          }
          if (opcion === 'descartar' || opcion === 'continuar') {
            marcar();
            sesion.articulos_descartados_ids = sesion.articulos_descartados_ids || [];
            (sesion.coincidencias || []).forEach((c) => {
              if (c.tipo_coincidencia === 'serie' || (c.titulo && c.titulo.toLowerCase().includes('serie'))) {
                sesion.descarto_serie = true;
              }
              if (c.id && !sesion.articulos_descartados_ids.includes(c.id)) {
                sesion.articulos_descartados_ids.push(c.id);
              }
            });
            const textoDisp = String(req.texto || sesion.texto || '').trim();
            if (textoDisp && cpLen(textoDisp) >= L.MIN_TEXTO) {
              const limpioDisp = sanitizar(textoDisp, sesion.titulo);
              const avisoDisp = avisoPrivacidad(limpioDisp.cambios);
              sesion.texto = limpioDisp.texto_sanitizado;
              sesion.texto_limpio = limpioDisp.texto_sanitizado;
              return avanzar('Listo, descartamos la coincidencia y seguimos con tu contenido propio. ', avisoDisp);
            }
            sesion.estado = 'ESPERANDO_TEXTO';
            return resp('Listo, lo tomamos como un tema distinto. Contame el contenido del artículo.', ['confirmar_texto', 'volver']);
          }
          const esSerie = sesion.coincidencias[0] && sesion.coincidencias[0].tipo_coincidencia === 'serie';
          return resp('Elegí una opción para seguir.', esSerie ? OPS.SERIE_DECISION : OPS.ENRIQUECER_DESCARTAR);
        }

        /* ---- ESPERANDO_TEXTO ---- */
        if (sesion.estado === 'ESPERANDO_TEXTO') {
          const opsTexto = (sesion.borrador && sesion.borrador.modo === 'enriquecimiento')
            ? ['confirmar_texto', 'descartar', 'volver']
            : ['confirmar_texto', 'volver'];

          const esConfirmacion = opcion === 'confirmar_texto' ||
            (req.accion && ['confirmar_texto', 'confirmar texto', 'confirmar'].includes(String(req.accion).trim().toLowerCase()));
          if (!esConfirmacion) {
            const frag = String(req.texto != null ? req.texto : (req.mensaje || '')).trim();
            if (!frag) return resp('Perfecto, ahora necesito que me pases el texto o los pasos del artículo para que podamos armarlo juntos.', opsTexto);
            const limpioFrag = sanitizar(frag, sesion.titulo);
            const fragSanit = limpioFrag.texto_sanitizado;
            const avisoFrag = avisoPrivacidad(limpioFrag.cambios);
            sesion.texto_en_edicion = req.texto != null ? fragSanit : ((sesion.texto_en_edicion ? sesion.texto_en_edicion + '\n\n' : '') + fragSanit);
            sesion.texto_limpio = sesion.texto_en_edicion;
            if (sesion.borrador) {
              if (req.texto == null && Array.isArray(sesion.borrador.bloques_texto) && sesion.borrador.bloques_texto.length) {
                const lastIdx = sesion.borrador.bloques_texto.length - 1;
                const prevLast = String(sesion.borrador.bloques_texto[lastIdx] || '').trim();
                sesion.borrador.bloques_texto[lastIdx] = prevLast ? (prevLast + '\n\n' + fragSanit) : fragSanit;
              } else {
                aplicarEdicionTextoEnBorrador(sesion.borrador, sesion.texto_en_edicion);
              }
              sincronizarBorrador(sesion.borrador);
              sesion.texto_en_edicion = sesion.borrador.texto_limpio;
              sesion.texto_limpio = sesion.borrador.texto_limpio;
            }
            if (cpLen(sesion.texto_en_edicion) > L.MAX_TEXTO_PERCENTIL_99) {
              return resp('El artículo supera los ' + L.MAX_TEXTO_PERCENTIL_99 + ' caracteres. Dividilo o resumilo.', opsTexto, avisoFrag);
            }
            return resp('Guardé tu texto en edición (' + cpLen(sesion.texto_en_edicion) + ' / ' + L.MAX_TEXTO_PERCENTIL_99 + ' caracteres). Podés seguir escribiendo o pegando más contenido, y cuando esté listo tocá "Confirmar texto".', opsTexto, avisoFrag);
          }

          const textoIn = String(req.texto != null ? req.texto : (sesion.texto_en_edicion || req.mensaje || '')).trim();
          if (!textoIn) return resp('Perfecto, ahora necesito que me pases el texto o los pasos del artículo para que podamos armarlo juntos. Pegalo o redactalo acá abajo cuando gustes.', ['volver']);
          if (cpLen(textoIn) < L.MIN_TEXTO) {
            return resp('El contenido es muy corto: necesito al menos ' + L.MIN_TEXTO + ' caracteres.', ['volver']);
          }
          if (cpLen(textoIn) > L.MAX_TEXTO_PERCENTIL_99) {
            return resp('El artículo supera los ' + L.MAX_TEXTO_PERCENTIL_99 + ' caracteres. Dividilo o resumilo.', ['descartar', 'reiniciar']);
          }
          sesion.texto_en_edicion = '';

          const limpio = sanitizar(textoIn, sesion.titulo);
          const aviso = avisoPrivacidad(limpio.cambios);
          sesion.texto = limpio.texto_sanitizado;
          sesion.texto_limpio = sesion.texto;
          if (req.categoria_id != null) sesion.categoria_id = req.categoria_id;
          if (req.tags != null) sesion.tags = req.tags;

          if (sesion.borrador && sesion.borrador.modo === 'enriquecimiento') {
            aplicarEdicionTextoEnBorrador(sesion.borrador, sesion.texto);
            // Nota: no se borran recursos al editar texto.
            if (req.categoria_id != null) sesion.borrador.categoria_id = req.categoria_id;
            if (req.tags != null) sesion.borrador.tags = req.tags;
            return avanzar('Sumé tu texto al borrador sobre #' + sesion.borrador.articulo_original_id + '. ', aviso);
          }

          const hit = (cpLen(sesion.texto) >= 400) ? buscar(sesion.texto + ' ' + sesion.titulo) : null;
          sesion.articulos_descartados_ids = sesion.articulos_descartados_ids || [];
          if (hit && !sesion.articulos_descartados_ids.includes(hit.id) && !(sesion.descarto_serie && hit.tipo_coincidencia === 'serie')) {
            marcar();
            sesion.coincidencias = [hit];
            sesion.estado = 'DECISION_TEXTO';
            return resp('El contenido se parece bastante a "' + hit.titulo + '" (' + hit.url + '). ' +
              '¿Querés enriquecer ese artículo o seguimos con tu texto?', OPS.ENRIQUECER_CONTINUAR, aviso);
          }

          sesion.borrador = {
            modo: 'nuevo',
            articulo_original_id: null,
            articulo_original_url: null,
            titulo: sesion.titulo,
            bloques_texto: [sesion.texto],
            texto: sesion.texto,
            texto_limpio: sesion.texto,
            recursos: {},
            multimedia: [],
            texto_original_aprobado: null,
            tipo_plantilla: tipoPlantilla(sesion.tags),
            categoria_id: sesion.categoria_id,
            tags: sesion.tags.slice()
          };
          sincronizarBorrador(sesion.borrador);
          return avanzar('No hay nada parecido publicado, seguimos con tu artículo. ', aviso);
        }

        /* ---- DECISION_TEXTO ---- */
        if (sesion.estado === 'DECISION_TEXTO') {
          if (req.categoria_id != null) sesion.categoria_id = req.categoria_id;
          if (req.tags != null) sesion.tags = req.tags;

          if (opcion === 'enriquecer' || opcion === 'actualizar') {
            const el = sesion.coincidencias[0];
            const art = BACO.datos.baseConocimiento.find((a) => a.id_externo === el.id) || {};
            const tagsIni = req.tags != null ? req.tags : (art.etiquetas || sesion.tags);
            const tituloFinal = (sesion.titulo || req.titulo || el.titulo).trim();
            const nomCat = art.categoria || 'Ventas';
            const metaAnt = { categoria_id: art.categoria_id || 5, categoria_nombre: nomCat, tags: tagsIni.slice() };
            const textoBase = String(el.texto_original || art.extracto || '').trim();
            const extraido = extraerBloquesYRecursosDeTextoExistente(textoBase);
            let avisoDecTxt = null;
            let aporte = String(req.texto || sesion.texto_limpio || sesion.texto || '').trim();
            if (aporte) {
              const limpioAp = sanitizar(aporte, tituloFinal);
              avisoDecTxt = avisoPrivacidad(limpioAp.cambios);
              aporte = limpioAp.texto_sanitizado;
            }
            const bloquesIni = extraido.bloques_texto.slice();
            if (aporte && !textoBase.includes(aporte)) {
              bloquesIni[bloquesIni.length - 1] = (bloquesIni[bloquesIni.length - 1] ? bloquesIni[bloquesIni.length - 1] + '\n\n' : '') + aporte;
            }
            sesion.borrador = {
              modo: 'enriquecimiento',
              articulo_original_id: el.id,
              articulo_original_url: el.url,
              titulo: tituloFinal,
              bloques_texto: bloquesIni,
              recursos: {},
              multimedia: extraido.recursos,
              orden_multimedia: [],
              posiciones: [],
              texto_original_aprobado: el.texto_original || null,
              tipo_plantilla: tipoPlantilla(tagsIni),
              categoria_id: req.categoria_id || sesion.categoria_id || 5,
              tags: tagsIni,
              metadatos_anteriores: metaAnt,
              metadatos_heredados_revisados: false,
              contenido_adicional: []
            };
            sincronizarBorrador(sesion.borrador);
            sesion.texto = sesion.borrador.texto_limpio;
            sesion.texto_limpio = sesion.borrador.texto_limpio;
            return avanzar('Armé el borrador de enriquecimiento sobre #' + el.id + '. ', avisoDecTxt);
          }
          if (opcion === 'continuar' || opcion === 'descartar') {
            sesion.articulos_descartados_ids = sesion.articulos_descartados_ids || [];
            (sesion.coincidencias || []).forEach((c) => {
              if (c.id && !sesion.articulos_descartados_ids.includes(c.id)) {
                sesion.articulos_descartados_ids.push(c.id);
              }
            });
            sesion.borrador = {
              modo: 'nuevo',
              articulo_original_id: null,
              articulo_original_url: null,
              titulo: sesion.titulo,
              bloques_texto: [sesion.texto],
              texto: sesion.texto,
              texto_limpio: sesion.texto,
              recursos: {},
              multimedia: [],
              texto_original_aprobado: null,
              tipo_plantilla: tipoPlantilla(sesion.tags),
              categoria_id: sesion.categoria_id,
              tags: sesion.tags.slice()
            };
            sincronizarBorrador(sesion.borrador);
            return avanzar('Dale, seguimos con tu propio texto. ');
          }
          return resp('Elegí una opción para seguir.', OPS.ENRIQUECER_CONTINUAR);
        }

        /* ---- ESPERANDO_PLANTILLA ---- */
        if (sesion.estado === 'ESPERANDO_PLANTILLA') {
          const b = sesion.borrador;
          if (req.texto != null && req.texto.trim()) {
            aplicarEdicionTextoEnBorrador(b, req.texto);
          }
          if (req.categoria_id != null) b.categoria_id = req.categoria_id;
          const pl = tipoPlantilla(req.tags || [], opcion);
          if (!pl) return resp('Elegí instructivo o soluciones para seguir.', OPS.PLANTILLAS);
          b.tipo_plantilla = pl;
          b.tags = combinarTags(pl, b.tags, req.tags || []);
          return avanzar('');
        }

        /* ---- ESPERANDO_METADATOS ---- */
        if (sesion.estado === 'ESPERANDO_METADATOS') {
          const b = sesion.borrador;
          if (req.categoria_id != null) b.categoria_id = req.categoria_id;
          let nuevos = (req.tags || []).slice();
          if (!nuevos.length && req.mensaje) {
            String(req.mensaje).split(',').forEach((frag) => {
              const item = frag.trim(); if (!item) return;
              if (/^\d+$/.test(item) && req.categoria_id == null) b.categoria_id = parseInt(item, 10);
              else nuevos.push(item);
            });
          }
          b.tags = combinarTags(b.tipo_plantilla, b.tags, nuevos);
          const tagsValidos = b.tags.length >= L.MIN_TAGS;
          const catValida = b.categoria_id != null && Number(b.categoria_id) > 1;

          if (!tagsValidos || !catValida) {
            if (!tagsValidos && !catValida) {
              return resp('Necesitamos al menos dos etiquetas temáticas y que selecciones la categoría desde el menú desplegable en el formulario de la izquierda.', ['volver']);
            }
            if (!catValida) {
              return resp('Por favor seleccioná la categoría del artículo desde el menú desplegable en el formulario de la izquierda.', ['volver']);
            }
            return resp('Todavía falta al menos un tag temático además de "' + b.tipo_plantilla + '".', ['volver']);
          }
          if (b.tags.length > L.MAX_TAGS) {
            return resp('Son demasiadas etiquetas: el máximo es ' + L.MAX_TAGS + ' y hay ' + b.tags.length + '. Quitá las menos relevantes.', ['volver']);
          }
          marcar();
          const r = validarBorrador('Anoté los metadatos. ');
          return resp(r.msg, r.ops);
        }

        /* ---- REVISION_BORRADOR ---- */
        if (sesion.estado === 'REVISION_BORRADOR') {
          const b = sesion.borrador;
          let textoEd = req.texto;
          if (textoEd == null && opcion === 'editar' && req.mensaje && req.mensaje.trim().toLowerCase() !== 'editar') {
            textoEd = req.mensaje;
          }
          const huboCambios = [req.titulo, textoEd, req.categoria_id, req.tags].some((v) => v != null);

          if (opcion === 'sanitizar') {
            const limpio = sanitizarBloques(b.bloques_texto || [b.texto_limpio || ''], req.titulo || b.titulo);
            b.titulo = limpio.titulo_sanitizado;
            b.bloques_texto = limpio.bloques_sanitizados;
            sincronizarBorrador(b);
            sesion.texto = b.texto_limpio;
            sesion.texto_limpio = b.texto_limpio;
            const r = validarBorrador(limpio.cambios.length ? 'Listo, limpié los datos sensibles. ' : 'Revisé el borrador y no encontré datos sensibles para limpiar. ');
            return resp(r.msg, r.ops, avisoPrivacidad(limpio.cambios));
          }

          if (huboCambios) {
            let aviso = null;
            if (req.titulo != null) b.titulo = String(req.titulo).trim();
            if (textoEd != null) {
              const limpio = aplicarEdicionTextoEnBorrador(b, textoEd);
              sesion.texto = b.texto_limpio;
              sesion.texto_limpio = b.texto_limpio;
              aviso = avisoPrivacidad(limpio.cambios);
            }
            if (req.categoria_id != null) b.categoria_id = req.categoria_id;
            if (req.tags != null) {
              const pl = tipoPlantilla(req.tags) || b.tipo_plantilla;
              b.tipo_plantilla = pl; b.tags = combinarTags(pl, req.tags);
            }
            const r = validarBorrador('Actualicé el borrador. ');
            return resp(r.msg, r.ops, aviso);
          }

          if (opcion === 'aceptar' || opcion === 'aceptar_metadatos') {
            b.metadatos_heredados_revisados = true;
            return avanzar('Se confirmaron los metadatos de la versión anterior. ');
          }

          if (opcion === 'rechazar_metadatos' || (opcion === 'rechazar' && b.metadatos_anteriores && !b.metadatos_heredados_revisados)) {
            b.metadatos_heredados_revisados = true;
            b.tipo_plantilla = null;
            b.categoria_id = null;
            b.tags = [];
            sesion.categoria_id = null;
            sesion.tags = [];
            return avanzar('Se descartaron los metadatos heredados. ');
          }

          if (opcion === 'editar') {
            const ops = (sesion.validacion && sesion.validacion.valido) ? OPS.REVISION_VALIDO : OPS.REVISION_BLOQUEANTE;
            return resp('Editá los campos que quieras en el panel de la izquierda y guardá los cambios: vuelvo a validar.', ops);
          }

          if (opcion === 'rechazar') {
            return resp('¿Seguro que querés descartar este borrador? Se pierde todo lo cargado.',
              ['confirmar_rechazo', 'volver']);
          }
          if (opcion === 'confirmar_rechazo') {
            sesion.estado = 'RECHAZADO';
            return resp('Descarté el borrador. Cuando quieras empezamos otro.', OPS.REINICIAR);
          }

          if (opcion === 'conforme' || opcion === 'aprobar') {
            if (!sesion.validacion || !sesion.validacion.valido) {
              const r = validarBorrador('Todavía no podemos avanzar, quedan observaciones bloqueantes. ');
              return resp(r.msg, r.ops);
            }
            const limpio = sanitizarBloques(b.bloques_texto || [b.texto_limpio || ''], b.titulo);
            b.titulo = limpio.titulo_sanitizado;
            b.bloques_texto = limpio.bloques_sanitizados;
            sincronizarBorrador(b);
            sesion.estado = 'CONFORMIDAD_USUARIO';
            return resp('✅ Registramos tu conformidad. Tu borrador pasó las validaciones mínimas y quedó listo. Todavía no está publicado: la aprobación y publicación final las hace un administrador. Podés copiar el borrador y cargarlo en la Base de Conocimiento.', ['copiar_borrador', 'reiniciar']);
          }

          const r = validarBorrador('');
          return resp(r.msg, r.ops);
        }

        return resp('Esta sesión ya terminó en estado ' + sesion.estado + '. Reiniciá para empezar otra carga.', OPS.REINICIAR);
      });
    },

    borradorConforme() {
      return responder(() => {
        if (!sesion || (sesion.estado !== 'CONFORMIDAD_USUARIO' && sesion.estado !== 'APROBADO') || !sesion.borrador) {
          throw err('HTTP_404', 'No hay un borrador en conformidad en esta sesión, o la sesión expiró.', 404);
        }
        sincronizarBorrador(sesion.borrador);
        return JSON.parse(JSON.stringify(sesion.borrador));
      }, 200);
    },

    borradorAprobado() {
      return this.borradorConforme();
    },

    aplicarPlantilla() {
      return responder(() => {
        if (!sesion || !sesion.borrador) throw err('SIN_SESION', 'No hay un borrador activo en la sesión.');
        sincronizarBorrador(sesion.borrador);
        if (sesion.borrador.skills_habilitadas === false) {
          throw err('VALIDACION', sesion.borrador.skills_motivo || 'Las skills de asistencia del agente están deshabilitadas para este borrador.', 422);
        }
        const tipo = sesion.borrador.tipo_plantilla || 'instructivo';
        const plantilla = BACO.datos.plantillas[tipo] || '';
        const textoResultante = '## Objetivo\nInstructivo para configurar el módulo.\n\n## Pasos a seguir\n1. Abrir menú.\n2. Guardar.';
        sesion.borrador.bloques_texto = [textoResultante];
        sincronizarBorrador(sesion.borrador);
        return {
          response: '## Borrador reestructurado con la plantilla "' + tipo + '"\n\n' + plantilla,
          texto_resultante: textoResultante,
          bloques_texto: sesion.borrador.bloques_texto.slice()
        };
      }, cfg().LATENCIA_AGENTE_MS);
    },

    auditarSemantica() {
      return responder(() => {
        if (!sesion || !sesion.borrador) throw err('SIN_SESION', 'No hay un borrador activo en la sesión.');
        sincronizarBorrador(sesion.borrador);
        if (sesion.borrador.skills_habilitadas === false) {
          throw err('VALIDACION', sesion.borrador.skills_motivo || 'Las skills de asistencia del agente están deshabilitadas para este borrador.', 422);
        }
        const v = validar(sesion.borrador);
        const lineas = v.findings.map((f) => '- **' + f.severity + '** (' + f.field + '): ' + f.description + ' → ' + f.action);
        const dictamen = '### Dictamen del validador\n\nEstado: **' + v.status + '**\n\n' +
          (lineas.length ? lineas.join('\n') : 'Sin observaciones.');
        const textoResultante = sesion.borrador.texto_limpio || dictamen;
        sesion.borrador.bloques_texto = [textoResultante];
        sincronizarBorrador(sesion.borrador);
        return {
          response: dictamen,
          texto_resultante: textoResultante,
          bloques_texto: sesion.borrador.bloques_texto.slice()
        };
      }, cfg().LATENCIA_AGENTE_MS);
    },

    agregarContenidoAdicional(contenido, tipo = 'texto') {
      return responder(() => {
        if (!sesion || !sesion.borrador) throw err('SIN_SESION', 'No hay un borrador activo en la sesión.');
        if (sesion.borrador.modo !== 'enriquecimiento' && !sesion.borrador.articulo_original_id) {
          throw err('ESTADO_INVALIDO', 'El contenido adicional solo está permitido en actualizar o enriquecer.');
        }
        sesion.borrador.contenido_adicional = sesion.borrador.contenido_adicional || [];
        const sanitItem = sanitizar(String(contenido || ''), sesion.borrador.titulo);
        const nuevo = {
          id: 'ca_' + Math.random().toString(36).substr(2, 8),
          tipo: tipo || 'texto',
          contenido: sanitItem.texto_sanitizado,
          posicion: sesion.borrador.contenido_adicional.length
        };
        sesion.borrador.contenido_adicional.push(nuevo);
        sincronizarBorrador(sesion.borrador);
        if (sesion.borrador.conforme) {
          sesion.borrador.conforme = false;
          sesion.borrador.conforme_en = null;
          sesion.borrador.conformidad_invalidada = true;
          if (sesion.estado === 'CONFORMIDAD_USUARIO') sesion.estado = 'REVISION_BORRADOR';
        }
        return nuevo;
      }, 100);
    },

    eliminarContenidoAdicional(itemId) {
      return responder(() => {
        if (!sesion || !sesion.borrador) throw err('SIN_SESION', 'No hay un borrador activo en la sesión.');
        const items = sesion.borrador.contenido_adicional || [];
        const originalLen = items.length;
        sesion.borrador.contenido_adicional = items.filter((it) => it.id !== itemId);
        if (sesion.borrador.contenido_adicional.length === originalLen) {
          throw err('NO_ENCONTRADO', 'No se encontró el ítem.');
        }
        sesion.borrador.contenido_adicional.forEach((it, idx) => { it.posicion = idx; });
        sincronizarBorrador(sesion.borrador);
        if (sesion.borrador.conforme) {
          sesion.borrador.conforme = false;
          sesion.borrador.conforme_en = null;
          sesion.borrador.conformidad_invalidada = true;
          if (sesion.estado === 'CONFORMIDAD_USUARIO') sesion.estado = 'REVISION_BORRADOR';
        }
        return { status: 'ok', eliminado: itemId };
      }, 100);
    },

    modificarContenidoAdicional(itemId, contenido, tipo = 'texto') {
      return responder(() => {
        if (!sesion || !sesion.borrador) throw err('SIN_SESION', 'No hay un borrador activo en la sesión.');
        const items = sesion.borrador.contenido_adicional || [];
        const item = items.find((it) => it.id === itemId);
        if (!item) throw err('NO_ENCONTRADO', 'No se encontró el ítem.');
        const sanitMod = sanitizar(String(contenido || ''), sesion.borrador.titulo);
        item.contenido = sanitMod.texto_sanitizado;
        if (tipo) item.tipo = tipo;
        sincronizarBorrador(sesion.borrador);
        if (sesion.borrador.conforme) {
          sesion.borrador.conforme = false;
          sesion.borrador.conforme_en = null;
          sesion.borrador.conformidad_invalidada = true;
          if (sesion.estado === 'CONFORMIDAD_USUARIO') sesion.estado = 'REVISION_BORRADOR';
        }
        return item;
      }, 100);
    },

    reordenarContenidoAdicional(ordenIds) {
      return responder(() => {
        if (!sesion || !sesion.borrador) throw err('SIN_SESION', 'No hay un borrador activo en la sesión.');
        const items = sesion.borrador.contenido_adicional || [];
        const mapa = {};
        items.forEach((it) => { mapa[it.id] = it; });
        const nuevos = [];
        (ordenIds || []).forEach((id) => {
          if (mapa[id]) { nuevos.push(mapa[id]); delete mapa[id]; }
        });
        Object.values(mapa).forEach((it) => nuevos.push(it));
        nuevos.forEach((it, idx) => { it.posicion = idx; });
        sesion.borrador.contenido_adicional = nuevos;
        sincronizarBorrador(sesion.borrador);
        if (sesion.borrador.conforme) {
          sesion.borrador.conforme = false;
          sesion.borrador.conforme_en = null;
          sesion.borrador.conformidad_invalidada = true;
          if (sesion.estado === 'CONFORMIDAD_USUARIO') sesion.estado = 'REVISION_BORRADOR';
        }
        return nuevos;
      }, 100);
    },

    obtenerContenidoAdicional() {
      return responder(() => {
        if (!sesion || !sesion.borrador) return [];
        return sesion.borrador.contenido_adicional || [];
      }, 100);
    },

    /* Gestión atómica de recursos multimedia con respuesta unificada EstadoRecursosResponse */
    obtenerRecursos() {
      return responder(() => construirEstadoRecursosMock(), 50);
    },

    eliminarRecurso(recursoId) {
      return responder(() => {
        if (!sesion || !sesion.borrador) throw err('SIN_SESION', 'No hay borrador activo.', 404);
        sincronizarBorrador(sesion.borrador);
        const b = sesion.borrador;
        const recs = b.recursos || {};
        let targetId = recursoId;
        if (typeof recursoId === 'number' || (/^\d+$/.test(recursoId) && !recs[recursoId])) {
          const sorted = b.multimedia || [];
          const idx = parseInt(recursoId, 10);
          if (idx >= 0 && idx < sorted.length) targetId = sorted[idx].id;
        }
        const eliminado = recs[targetId];
        if (!eliminado) throw err('NO_ENCONTRADO', 'Recurso no encontrado.', 404);
        const posEliminado = typeof eliminado.posicion === 'number' ? eliminado.posicion : 0;
        delete recs[targetId];

        const restantes = Object.values(recs);
        const quedaOtroEnPos = restantes.some((r) => r.posicion === posEliminado);

        // Fusión de bloques_texto[pos] y bloques_texto[pos + 1] SOLO si ningún otro recurso queda en esa posicion y pos >= 0
        if (!quedaOtroEnPos && posEliminado >= 0 && posEliminado < b.bloques_texto.length - 1) {
          const izq = String(b.bloques_texto[posEliminado] || '');
          const der = String(b.bloques_texto[posEliminado + 1] || '');
          let fusionado;
          if (!izq) fusionado = der;
          else if (!der) fusionado = izq;
          else if (izq.endsWith('\n') || der.startsWith('\n') || izq.endsWith(' ') || der.startsWith(' ')) fusionado = izq + der;
          else fusionado = izq + '\n\n' + der;

          b.bloques_texto.splice(posEliminado, 2, fusionado);
          restantes.forEach((r) => {
            if (r.posicion > posEliminado) r.posicion -= 1;
          });
        }

        b.multimedia = ordenarRecursosInvariante(restantes, b.bloques_texto.length);
        sincronizarBorrador(b);
        if (b.conforme) {
          b.conforme = false;
          b.conforme_en = null;
          b.conformidad_invalidada = true;
          if (sesion.estado === 'CONFORMIDAD_USUARIO') sesion.estado = 'REVISION_BORRADOR';
        }
        return construirEstadoRecursosMock();
      }, 50);
    },

    reordenarMultimedia(fromIndexOrPayload, toIndex) {
      return responder(() => {
        if (!sesion || !sesion.borrador) throw err('SIN_SESION', 'No hay borrador activo.', 404);
        sincronizarBorrador(sesion.borrador);
        const b = sesion.borrador;
        let items = b.multimedia.slice();
        const maxPos = Math.max(0, b.bloques_texto.length - 1);

        if (typeof fromIndexOrPayload === 'number' && typeof toIndex === 'number') {
          if (fromIndexOrPayload < 0 || fromIndexOrPayload >= items.length || toIndex < 0 || toIndex >= items.length) {
            throw err('VALIDACION', 'Índices fuera de rango.', 422);
          }
          const moved = items.splice(fromIndexOrPayload, 1)[0];
          const destItem = items[Math.min(toIndex, items.length - 1)];
          if (destItem && typeof destItem.posicion === 'number') {
            moved.posicion = destItem.posicion;
          }
          items.splice(toIndex, 0, moved);
          items.forEach((r, idx) => { r.orden = idx; });
        } else if (fromIndexOrPayload && typeof fromIndexOrPayload === 'object' && !Array.isArray(fromIndexOrPayload) && fromIndexOrPayload.id) {
          const target = items.find((r) => r.id === fromIndexOrPayload.id);
          if (!target) throw err('NO_ENCONTRADO', 'Recurso no encontrado.', 404);
          if (typeof fromIndexOrPayload.posicion === 'number') {
            if (fromIndexOrPayload.posicion < -1 || fromIndexOrPayload.posicion > maxPos) {
              throw err('VALIDACION', 'Posición fuera de rango.', 422);
            }
            target.posicion = fromIndexOrPayload.posicion;
          }
          const sinTarget = items.filter((r) => r.id !== target.id);
          const nuevoOrden = typeof fromIndexOrPayload.orden === 'number'
            ? Math.max(0, Math.min(sinTarget.length, fromIndexOrPayload.orden))
            : sinTarget.length;
          sinTarget.splice(nuevoOrden, 0, target);
          sinTarget.forEach((r, idx) => { r.orden = idx; });
          items = sinTarget;
        } else if (Array.isArray(fromIndexOrPayload)) {
          if (fromIndexOrPayload.length > 0 && typeof fromIndexOrPayload[0] === 'number') {
            const mapped = [];
            fromIndexOrPayload.forEach((idx) => { if (items[idx]) mapped.push(items[idx]); });
            items.forEach((r) => { if (!mapped.includes(r)) mapped.push(r); });
            items = mapped;
          } else {
            const map = {};
            items.forEach((r) => { map[r.id] = r; });
            const mapped = [];
            fromIndexOrPayload.forEach((id) => { if (map[id]) { mapped.push(map[id]); delete map[id]; } });
            Object.values(map).forEach((r) => mapped.push(r));
            items = mapped;
          }
          items.forEach((r, idx) => { r.orden = idx; });
        }

        b.multimedia = ordenarRecursosInvariante(items, b.bloques_texto.length);
        sincronizarBorrador(b);
        if (b.conforme) {
          b.conforme = false;
          b.conforme_en = null;
          b.conformidad_invalidada = true;
          if (sesion.estado === 'CONFORMIDAD_USUARIO') sesion.estado = 'REVISION_BORRADOR';
        }
        return construirEstadoRecursosMock();
      }, 50);
    },

    agregarRecursoMultimedia(recurso) {
      return responder(() => {
        if (!sesion || !sesion.borrador) throw err('SIN_SESION', 'No hay borrador activo.', 404);
        if (!multimediaHabilitadaActual()) {
          throw err('VALIDACION', 'Disponible al finalizar las validaciones', 422);
        }
        sincronizarBorrador(sesion.borrador);
        const b = sesion.borrador;
        let items = b.multimedia.slice();
        if (items.length >= MAX_RECURSOS) {
          throw err('VALIDACION', 'Se alcanzó el límite máximo de 20 recursos multimedia por artículo.', 422);
        }

        const numRec = items.length + 1;
        const maxPos = Math.max(0, b.bloques_texto.length - 1);
        const pos = typeof (recurso && recurso.posicion) === 'number'
          ? recurso.posicion
          : maxPos;
        if (pos < -1 || pos > maxPos) {
          throw err('VALIDACION', 'La posición del recurso está fuera del rango de bloques.', 422);
        }

        const rec = Object.assign({
          id: 'rec_' + numRec + '_' + Math.random().toString(36).substr(2, 4),
          tipo: 'imagen',
          nombre: 'recurso',
          referencia: '',
          origen: 'subido',
          tamano_bytes: 0
        }, recurso, {
          posicion: pos,
          orden: items.length
        });

        items.push(rec);
        b.multimedia = ordenarRecursosInvariante(items, b.bloques_texto.length);
        sincronizarBorrador(b);
        if (b.conforme) {
          b.conforme = false;
          b.conforme_en = null;
          b.conformidad_invalidada = true;
          if (sesion.estado === 'CONFORMIDAD_USUARIO') sesion.estado = 'REVISION_BORRADOR';
        }
        return construirEstadoRecursosMock();
      }, 50);
    },

    subirRecursoMultimedia(file, posicion, bloquesTexto) {
      return responder(() => {
        if (!sesion || !sesion.borrador) throw err('SIN_SESION', 'No hay borrador activo.', 404);
        if (!multimediaHabilitadaActual()) {
          throw err('VALIDACION', 'Disponible al finalizar las validaciones', 422);
        }
        sincronizarBorrador(sesion.borrador);
        const b = sesion.borrador;
        const nombre = (file && file.name) || 'archivo.png';
        const mime = (file && file.type) || 'image/png';
        const size = (file && typeof file.size === 'number') ? file.size : 1024;

        if (nombre.toLowerCase().endsWith('.svg') || mime.toLowerCase() === 'image/svg+xml') {
          throw err('VALIDACION', 'No se permiten archivos SVG por motivos de seguridad.', 422);
        }
        if (size > MAX_ARCHIVO_BYTES) {
          throw err('VALIDACION', 'El archivo supera el tamaño máximo permitido de 10 MB.', 422);
        }
        const bytesActuales = (b.multimedia || []).reduce((acc, r) => acc + (r.tamano_bytes || 0), 0);
        if (bytesActuales + size > MAX_SESION_BYTES) {
          throw err('VALIDACION', 'El tamaño acumulado de los recursos superaría el límite de 50 MB.', 422);
        }
        if ((b.multimedia || []).length >= MAX_RECURSOS) {
          throw err('VALIDACION', 'Se alcanzó el límite máximo de 20 recursos multimedia por artículo.', 422);
        }

        // Validación atómica de bloques_texto (si fue enviado)
        let nuevosBloques = b.bloques_texto.slice();
        if (bloquesTexto !== undefined && bloquesTexto !== null) {
          const listaBloques = typeof bloquesTexto === 'string' ? JSON.parse(bloquesTexto) : bloquesTexto;
          if (!Array.isArray(listaBloques) || !listaBloques.length || listaBloques.length > MAX_BLOQUES) {
            throw err('VALIDACION', 'La lista de bloques de texto es inválida o supera el máximo permitido (21).', 422);
          }
          const sanit = sanitizarBloques(listaBloques, b.titulo);
          const textoUnido = sanit.bloques_sanitizados.map((x) => String(x || '').trim()).filter(Boolean).join('\n\n');
          if (cpLen(textoUnido) > (lim().MAX_TEXTO_PERCENTIL_99 || 16777)) {
            throw err('VALIDACION', 'El texto unido de los bloques supera el límite máximo permitido.', 422);
          }
          nuevosBloques = sanit.bloques_sanitizados;
        }

        const maxPos = nuevosBloques.length - 1;
        const posFinal = (typeof posicion === 'number') ? posicion : maxPos;
        if (posFinal < -1 || posFinal > maxPos) {
          throw err('VALIDACION', 'La posición del recurso está fuera del rango de bloques.', 422);
        }

        // Todo validó: aplicamos de forma atómica bloques_texto + nuevo recurso
        b.bloques_texto = nuevosBloques;
        const nuevoId = 'rec_' + ((b.multimedia ? b.multimedia.length : 0) + 1) + '_' + Math.random().toString(36).substr(2, 4);
        const nuevoRec = {
          id: nuevoId,
          nombre: nombre,
          referencia: '/api/recursos-temp/' + sesion.session_id + '/' + encodeURIComponent(nombre),
          tipo: mime.startsWith('image/') ? 'imagen' : (mime.startsWith('video/') ? 'video' : 'documento'),
          origen: 'subido',
          tamano_bytes: size,
          mime_type: mime,
          posicion: posFinal,
          orden: (b.multimedia ? b.multimedia.length : 0)
        };
        const items = (b.multimedia || []).concat([nuevoRec]);
        b.multimedia = ordenarRecursosInvariante(items, b.bloques_texto.length);
        sincronizarBorrador(b);
        return construirEstadoRecursosMock();
      }, 50);
    },

    confirmarBloques(bloques) {
      return responder(() => {
        if (!sesion) throw err('SIN_SESION', 'No hay sesión activa.');
        const bloquesTexto = [];
        const recursosNuevos = [];
        let rCount = 1;
        const tiposConteo = {};

        (bloques || []).forEach((bl) => {
          if (bl.tipo === 'texto') {
            const cont = String(bl.contenido || '').trim();
            if (cont) {
              bloquesTexto.push(cont);
            }
          } else if (bl.tipo === 'recurso' && bl.recurso) {
            const pos = bloquesTexto.length - 1;
            const prevRecs = (sesion.borrador && sesion.borrador.multimedia) || [];
            const ref = bl.recurso.url || bl.recurso.referencia || '';
            const existente = bl.recurso.id
              ? prevRecs.find((x) => x.id === bl.recurso.id)
              : prevRecs.find((x) => ref && x.referencia === ref);
            if (bl.recurso.id && !existente) {
              throw err('VALIDACION', 'El recurso no existe en la sesión actual.');
            }
            const rid = (existente && existente.id) || bl.recurso.id || ('rec_' + rCount);
            const r = {
              id: rid,
              tipo: bl.recurso.tipo || (existente && existente.tipo) || 'imagen',
              nombre: bl.recurso.nombre || (existente && existente.nombre) || ('Recurso ' + rCount),
              referencia: (existente && existente.referencia) || ref || '',
              origen: (existente && existente.origen) || 'subido',
              tamano_bytes: (existente && existente.tamano_bytes) || bl.recurso.tamanio || 0,
              mime_type: (existente && existente.mime_type) || bl.recurso.mime || null,
              posicion: pos,
              orden: rCount - 1
            };
            recursosNuevos.push(r);
            tiposConteo[r.tipo] = (tiposConteo[r.tipo] || 0) + 1;
            rCount++;
          }
        });

        if (!bloquesTexto.length) bloquesTexto.push('');
        const sanit = sanitizarBloques(bloquesTexto, sesion.titulo || (sesion.borrador && sesion.borrador.titulo));
        let avisoPriv = null;
        if (sanit.cambios && sanit.cambios.length) {
          avisoPriv = 'Se detectaron y anonimizaron datos personales (' + sanit.cambios.join(', ') + ').';
        }

        if (!sesion.borrador) {
          sesion.borrador = {
            modo: 'nuevo',
            titulo: sesion.titulo || 'Artículo',
            bloques_texto: sanit.bloques_sanitizados,
            recursos: {},
            multimedia: recursosNuevos,
            tags: sesion.tags || [],
            categoria_id: sesion.categoria_id || 1
          };
        } else {
          sesion.borrador.bloques_texto = sanit.bloques_sanitizados;
          sesion.borrador.multimedia = recursosNuevos;
          sesion.borrador.conforme = false;
        }
        sincronizarBorrador(sesion.borrador);
        sesion.texto_limpio = sesion.borrador.texto_limpio;
        sesion.texto = sesion.borrador.texto_limpio;

        const avisoPartes = Object.entries(tiposConteo).map(([t, c]) => `${c} ${t}`);
        const avisoRecursos = avisoPartes.length ? `Se detectaron ${rCount - 1} recursos (${avisoPartes.join(', ')}).` : null;
        const avisoFinal = [avisoPriv, avisoRecursos].filter(Boolean).join('\n\n') || null;
        return {
          session_id: sesion.session_id,
          texto_limpio: sesion.borrador.texto_limpio,
          bloques_texto: sesion.borrador.bloques_texto.slice(),
          recursos: sesion.borrador.multimedia.slice(),
          multimedia_habilitada: multimediaHabilitadaActual(),
          skills_habilitadas: sesion.borrador.skills_habilitadas,
          skills_motivo: sesion.borrador.skills_motivo,
          aviso: avisoFinal,
          borrador: JSON.parse(JSON.stringify(sesion.borrador))
        };
      }, 50);
    },

    sesionActual() { return sesion ? sesion.session_id : null; },
    olvidarSesion() { sesion = null; }
  };
})();
