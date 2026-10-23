/* =============================================================
   Implementación SIMULADA
   -------------------------------------------------------------
   Emula el orquestador de Caro al commit 237dcfb:
     · se puede VOLVER en cada etapa (ya no es unidireccional)
     · rechazar pide confirmación
     · avisa cuando sanitiza datos sensibles (aviso_privacidad)
     · las coincidencias traen score y tipo de coincidencia
     · endpoints separados para las dos skills

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
    REVISION_VALIDO:      ['aprobar', 'editar', 'sanitizar', 'rechazar', 'volver', 'reiniciar'],
    REVISION_BLOQUEANTE:  ['editar', 'sanitizar', 'rechazar', 'volver', 'reiniciar'],
    REINICIAR:            ['reiniciar']
  };

  function err(codigo, mensaje) { const e = new Error(mensaje); e.codigo = codigo; return e; }

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
     Búsqueda de duplicados simulada, con tipo y score
     --------------------------------------------------------- */
  function normalizar(t) {
    return String(t || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
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
  const RE_CUIT = /\b\d{2}-?\d{8}-?\d\b/;
  const RE_MAIL = /\b[\w.+-]+@[\w-]+\.[\w.]+\b/;

  function sanitizar(texto, titulo) {
    let t = String(texto || ''), cambios = [];
    if (RE_CUIT.test(t)) { t = t.replace(new RegExp(RE_CUIT.source, 'g'), '20-12345678-9'); cambios.push('CUIT'); }
    if (RE_MAIL.test(t)) { t = t.replace(new RegExp(RE_MAIL.source, 'g'), 'ejemplo@empresa.com'); cambios.push('correo electrónico'); }
    let ti = String(titulo || '').replace(/^(c[oó]mo|como)\s+/i, '').trim();
    if (ti) ti = ti.charAt(0).toUpperCase() + ti.slice(1);
    return { texto_sanitizado: t, titulo_sanitizado: ti, cambios: cambios };
  }

  function avisoPrivacidad(cambios) {
    if (!cambios.length) return null;
    return 'Detecté ' + cambios.join(' y ') + ' en el contenido y lo reemplacé por datos de ejemplo. ' +
      'Revisá que el reemplazo no haya cambiado el sentido del texto.';
  }

  function validar(b) {
    const findings = [];
    const titulo = b.titulo || '', texto = b.texto || '', tags = b.tags || [];
    const L = lim();

    if (titulo.length < L.MIN_TITULO || titulo.length > L.MAX_TITULO) {
      findings.push({ severity: 'Bloqueante', field: 'titulo',
        description: 'El título debe tener entre ' + L.MIN_TITULO + ' y ' + L.MAX_TITULO + ' caracteres (actual: ' + titulo.length + ').',
        action: 'Ajustar la longitud del título.' });
    }
    if (texto.length < L.MIN_TEXTO) {
      findings.push({ severity: 'Bloqueante', field: 'texto',
        description: 'El texto debe tener al menos ' + L.MIN_TEXTO + ' caracteres (actual: ' + texto.length + ').',
        action: 'Ampliar el contenido del artículo.' });
    }
    if (texto.length > L.MAX_TEXTO) {
      findings.push({ severity: 'Bloqueante', field: 'texto',
        description: 'El texto supera los ' + L.MAX_TEXTO + ' caracteres (actual: ' + texto.length + ').',
        action: 'Dividir el artículo o resumirlo.' });
    }
    if (RE_CUIT.test(texto) || RE_MAIL.test(texto)) {
      findings.push({ severity: 'Bloqueante', field: 'texto',
        description: 'Se detectaron datos sensibles reales en el cuerpo.',
        action: 'Sanitizar el borrador para reemplazarlos por ejemplos genéricos.' });
    }
    if (/\[Indicar[^\]]*\]/i.test(texto)) {
      findings.push({ severity: 'Bloqueante', field: 'texto',
        description: 'Quedaron marcadores pendientes del tipo [Indicar...] sin completar.',
        action: 'Completar o quitar los marcadores a mano antes de aprobar.' });
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
    if (!/ruta\s*[:>]/i.test(texto) && texto.length > 100) {
      findings.push({ severity: 'Sugerencia', field: 'texto',
        description: 'No se indicó la ruta de acceso con el símbolo >.',
        action: 'Agregar «Ruta> Menú > ...» para orientar al lector.' });
    }
    if (tags.length < L.MIN_TAGS) {
      findings.push({ severity: 'Ajuste', field: 'tags',
        description: 'El artículo tiene menos de ' + L.MIN_TAGS + ' etiquetas.',
        action: 'Agregar al menos un tag temático adicional.' });
    }

    const bloqueantes = findings.filter((f) => f.severity === 'Bloqueante').length;
    const limpio = sanitizar(texto, titulo);
    return {
      valido: bloqueantes === 0,
      fase: 'fase_2_texto_y_estructura',
      status: bloqueantes === 0 ? 'Listo' : 'Pendiente',
      titulo_sanitizado: limpio.titulo_sanitizado,
      texto_sanitizado: limpio.texto_sanitizado,
      findings: findings,
      resumen: { longitud_texto: texto.length, tags_count: tags.length }
    };
  }

  /* ---------------------------------------------------------
     Helpers
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
      'aprobar': 'aprobar', 'apruebo': 'aprobar', 'confirmar': 'aprobar', 'omitir': 'aprobar',
      'rechazar': 'rechazar', 'rechazo': 'rechazar', 'cancelar': 'rechazar',
      'confirmar_rechazo': 'confirmar_rechazo', 'confirmar rechazo': 'confirmar_rechazo',
      'sanitizar': 'sanitizar', 'editar': 'editar', 'corregir': 'editar',
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
    'Aprobación'
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
    APROBADO: 5,
    RECHAZADO: 5
  };

  function resp(mensaje, opciones, aviso) {
    const s = sesion;
    const actual = MAPA_ETAPAS[s.estado] || 1;
    const tagsAcum = s.borrador
      ? combinarTags(s.borrador.tipo_plantilla, s.borrador.tags, s.tags)
      : combinarTags(tipoPlantilla(s.tags), s.tags);
    const catsDisp = ((BACO.datos && BACO.datos.categorias) || []).map((c, idx) => ({
      id: typeof c.id === 'number' ? c.id : (idx + 1),
      nombre: c.nombre
    }));
    const tagsDisp = ((BACO.datos && BACO.datos.etiquetas) || []).map((e) => e.tag);
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
      validacion: s.validacion || null,
      aviso_privacidad: aviso || null
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
    const obs = detalle ? '\nAdemás te dejo algunas sugerencias:\n' + detalle + '\n' : ' ';
    return { msg: (prefijo || '') + 'El borrador quedó validado (' + v.status + ').' + obs +
      '¿Lo aprobamos para publicación?', ops: OPS.REVISION_VALIDO };
  }

  function avanzar(prefijo, aviso) {
    const b = sesion.borrador;
    const pl = b.tipo_plantilla || tipoPlantilla(b.tags);
    if (pl) { b.tipo_plantilla = pl; b.tags = combinarTags(pl, b.tags); }

    if (!b.tipo_plantilla) {
      marcar();
      sesion.estado = 'ESPERANDO_PLANTILLA';
      return resp((prefijo || '') + '¿Qué plantilla corresponde para este artículo: instructivo o soluciones?',
        OPS.PLANTILLAS, aviso);
    }
    if (b.tags.length < lim().MIN_TAGS) {
      marcar();
      sesion.estado = 'ESPERANDO_METADATOS';
      return resp((prefijo || '') + 'Aplico la plantilla "' + b.tipo_plantilla + '". Agregá al menos un tag temático ' +
        '(por ejemplo "ventas" o "facturacion"; si son varios, separalos con coma) y, si querés, el ID de categoría.',
        ['volver'], aviso);
    }
    marcar();
    const r = validarBorrador(prefijo);
    return resp(r.msg, r.ops, aviso);
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
          if (entradaTitulo.length < L.MIN_TITULO) {
            return resp('Necesito un título un poco más descriptivo: al menos ' + L.MIN_TITULO + ' caracteres.', []);
          }
          if (entradaTitulo.length > L.MAX_TITULO) {
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
          return resp('No encontré nada parecido por título. Contame el contenido del artículo.', ['volver']);
        }

        /* ---- DECISION_TITULO ---- */
        if (sesion.estado === 'DECISION_TITULO') {
          if (opcion === 'enriquecer' || opcion === 'actualizar') {
            const el = sesion.coincidencias[0];
            const art = BACO.datos.baseConocimiento.find((a) => a.id_externo === el.id) || {};
            const textoIni = String(req.texto || el.texto_original || sesion.texto || '').trim();
            const tagsIni = req.tags != null ? req.tags : (art.etiquetas || sesion.tags);
            const esSerie = el.tipo_coincidencia === 'serie' || opcion === 'actualizar';
            const tituloFinal = (sesion.titulo || req.titulo || el.titulo).trim();
            sesion.borrador = { modo: 'enriquecimiento', articulo_original_id: el.id, articulo_original_url: el.url,
              titulo: tituloFinal, texto: textoIni, texto_original_aprobado: el.texto_original || null,
              tipo_plantilla: tipoPlantilla(tagsIni),
              categoria_id: req.categoria_id || sesion.categoria_id, tags: tagsIni };
            if (!textoIni || textoIni.length < L.MIN_TEXTO) {
              marcar();
              sesion.estado = 'ESPERANDO_TEXTO';
              return resp('Vamos a enriquecer el artículo #' + el.id + '. Escribí el texto que querés sumarle (mínimo ' + L.MIN_TEXTO + ' caracteres).', ['volver']);
            }
            return avanzar('Armé el borrador sobre #' + el.id + '. ');
          }
          if (opcion === 'descartar' || opcion === 'continuar') {
            marcar();
            sesion.articulos_descartados_ids = sesion.articulos_descartados_ids || [];
            (sesion.coincidencias || []).forEach((c) => {
              if (c.id && !sesion.articulos_descartados_ids.includes(c.id)) {
                sesion.articulos_descartados_ids.push(c.id);
              }
            });
            const textoDisp = String(req.texto || sesion.texto || '').trim();
            if (textoDisp && textoDisp.length >= L.MIN_TEXTO) {
              const hitTxt = buscarSimilares(textoDisp, 'texto');
              if (hitTxt && !sesion.articulos_descartados_ids.includes(hitTxt.id)) {
                sesion.coincidencias = [hitTxt];
                sesion.estado = 'DECISION_TEXTO';
                return resp('Encontré un artículo que explica prácticamente lo mismo en el contenido: "' +
                  hitTxt.titulo + '" (' + hitTxt.url + '). ¿Querés enriquecer ese artículo o seguimos con tu texto?',
                  OPS.ENRIQUECER_CONTINUAR);
              }
              return avanzar('Listo, descartamos la coincidencia y seguimos con tu contenido propio. ');
            }
            sesion.estado = 'ESPERANDO_TEXTO';
            return resp('Listo, lo tomamos como un tema distinto. Contame el contenido del artículo.', ['volver']);
          }
          const esSerie = sesion.coincidencias[0] && sesion.coincidencias[0].tipo_coincidencia === 'serie';
          return resp('Elegí una opción para seguir.', esSerie ? OPS.SERIE_DECISION : OPS.ENRIQUECER_DESCARTAR);
        }

        /* ---- ESPERANDO_TEXTO ---- */
        if (sesion.estado === 'ESPERANDO_TEXTO') {
          const textoIn = String(req.texto || req.mensaje || '').trim();
          if (!textoIn) return resp('Me falta el contenido del artículo para seguir.', ['volver']);
          if (textoIn.length < L.MIN_TEXTO) {
            return resp('El contenido es muy corto: necesito al menos ' + L.MIN_TEXTO + ' caracteres.', ['volver']);
          }
          if (textoIn.length > L.MAX_TEXTO) {
            return resp('El artículo supera los ' + L.MAX_TEXTO + ' caracteres. Dividilo o resumilo.', ['descartar', 'reiniciar']);
          }

          const limpio = sanitizar(textoIn, sesion.titulo);
          const aviso = avisoPrivacidad(limpio.cambios);
          sesion.texto = limpio.cambios.length ? limpio.texto_sanitizado : textoIn;
          if (req.categoria_id != null) sesion.categoria_id = req.categoria_id;
          if (req.tags != null) sesion.tags = req.tags;

          if (sesion.borrador && sesion.borrador.modo === 'enriquecimiento') {
            sesion.borrador.texto = sesion.texto;
            if (req.categoria_id != null) sesion.borrador.categoria_id = req.categoria_id;
            if (req.tags != null) sesion.borrador.tags = req.tags;
            return avanzar('Sumé tu texto al borrador sobre #' + sesion.borrador.articulo_original_id + '. ', aviso);
          }

          const hit = buscar(sesion.texto + ' ' + sesion.titulo);
          sesion.articulos_descartados_ids = sesion.articulos_descartados_ids || [];
          if (hit && !sesion.articulos_descartados_ids.includes(hit.id)) {
            marcar();
            sesion.coincidencias = [hit];
            sesion.estado = 'DECISION_TEXTO';
            return resp('El contenido se parece bastante a "' + hit.titulo + '" (' + hit.url + '). ' +
              '¿Querés enriquecer ese artículo o seguimos con tu texto?', OPS.ENRIQUECER_CONTINUAR, aviso);
          }

          sesion.borrador = { modo: 'nuevo', articulo_original_id: null, articulo_original_url: null,
            titulo: sesion.titulo, texto: sesion.texto, texto_original_aprobado: null,
            tipo_plantilla: tipoPlantilla(sesion.tags),
            categoria_id: sesion.categoria_id, tags: sesion.tags.slice() };
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
            sesion.borrador = { modo: 'enriquecimiento', articulo_original_id: el.id, articulo_original_url: el.url,
              titulo: tituloFinal, texto: String(req.texto || sesion.texto || '').trim(),
              texto_original_aprobado: el.texto_original || null,
              tipo_plantilla: tipoPlantilla(tagsIni), categoria_id: req.categoria_id || sesion.categoria_id, tags: tagsIni };
            return avanzar('Armé el borrador de enriquecimiento sobre #' + el.id + '. ');
          }
          if (opcion === 'continuar' || opcion === 'descartar') {
            sesion.articulos_descartados_ids = sesion.articulos_descartados_ids || [];
            (sesion.coincidencias || []).forEach((c) => {
              if (c.id && !sesion.articulos_descartados_ids.includes(c.id)) {
                sesion.articulos_descartados_ids.push(c.id);
              }
            });
            sesion.borrador = { modo: 'nuevo', articulo_original_id: null, articulo_original_url: null,
              titulo: sesion.titulo, texto: sesion.texto, texto_original_aprobado: null,
              tipo_plantilla: tipoPlantilla(sesion.tags),
              categoria_id: sesion.categoria_id, tags: sesion.tags.slice() };
            return avanzar('Dale, seguimos con tu propio texto. ');
          }
          return resp('Elegí una opción para seguir.', OPS.ENRIQUECER_CONTINUAR);
        }

        /* ---- ESPERANDO_PLANTILLA ---- */
        if (sesion.estado === 'ESPERANDO_PLANTILLA') {
          const b = sesion.borrador;
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
          if (b.tags.length < L.MIN_TAGS) {
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
            const limpio = sanitizar(req.texto || b.texto, req.titulo || b.titulo);
            b.titulo = limpio.titulo_sanitizado; b.texto = limpio.texto_sanitizado;
            const r = validarBorrador(limpio.cambios.length ? 'Listo, limpié los datos sensibles. ' : 'Revisé el borrador y no encontré datos sensibles para limpiar. ');
            return resp(r.msg, r.ops, avisoPrivacidad(limpio.cambios));
          }

          if (huboCambios) {
            let aviso = null;
            if (req.titulo != null) b.titulo = String(req.titulo).trim();
            if (textoEd != null) {
              const limpio = sanitizar(textoEd, b.titulo);
              b.texto = limpio.cambios.length ? limpio.texto_sanitizado : String(textoEd).trim();
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

          if (opcion === 'aprobar') {
            if (!sesion.validacion || !sesion.validacion.valido) {
              const r = validarBorrador('Todavía no puedo aprobarlo, quedan observaciones bloqueantes. ');
              return resp(r.msg, r.ops);
            }
            const limpio = sanitizar(b.texto, b.titulo);
            b.titulo = limpio.titulo_sanitizado; b.texto = limpio.texto_sanitizado;
            sesion.estado = 'APROBADO';
            return resp('Listo: "' + b.titulo + '" quedó aprobado para publicación.', OPS.REINICIAR);
          }

          const r = validarBorrador('');
          return resp(r.msg, r.ops);
        }

        return resp('Esta sesión ya terminó en estado ' + sesion.estado + '. Reiniciá para empezar otra carga.', OPS.REINICIAR);
      });
    },

    borradorAprobado() {
      return responder(() => {
        if (!sesion || sesion.estado !== 'APROBADO' || !sesion.borrador) {
          throw err('HTTP_404', 'No hay un borrador aprobado en esta sesión, o la sesión expiró.');
        }
        return JSON.parse(JSON.stringify(sesion.borrador));
      }, 200);
    },

    aplicarPlantilla() {
      return responder(() => {
        if (!sesion || !sesion.borrador) throw err('SIN_SESION', 'No hay un borrador activo en la sesión.');
        const tipo = sesion.borrador.tipo_plantilla || 'instructivo';
        const plantilla = BACO.datos.plantillas[tipo] || '';
        return { response: '## Borrador reestructurado con la plantilla "' + tipo + '"\n\n' + plantilla };
      }, cfg().LATENCIA_AGENTE_MS);
    },

    auditarSemantica() {
      return responder(() => {
        if (!sesion || !sesion.borrador) throw err('SIN_SESION', 'No hay un borrador activo en la sesión.');
        const v = validar(sesion.borrador);
        const lineas = v.findings.map((f) => '- **' + f.severity + '** (' + f.field + '): ' + f.description + ' → ' + f.action);
        return { response: '### Dictamen del validador\n\nEstado: **' + v.status + '**\n\n' +
          (lineas.length ? lineas.join('\n') : 'Sin observaciones.') };
      }, cfg().LATENCIA_AGENTE_MS);
    },

    sesionActual() { return sesion ? sesion.session_id : null; },
    olvidarSesion() { sesion = null; }
  };
})();
