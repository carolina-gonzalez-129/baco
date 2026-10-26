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
    REVISION_VALIDO:      ['conforme', 'editar', 'rechazar'],
    REVISION_BLOQUEANTE:  ['editar', 'rechazar'],
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
  const RE_CUIT = /\b(?:20|23|24|27)-?\d{8}-?\d\b/;
  const RE_CUIL_CONTEXTO = /(?:\b(?:cuil|cuit)(?:\s+(?:nro|n[uú]mero))?[\s:=#]+)(?:20|23|24|27)[-.\s]?\d{8}[-.\s]?\d\b/i;
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
    if (RE_MAIL.test(t)) { t = t.replace(new RegExp(RE_MAIL.source, 'g'), 'usuario@ejemplo.com'); cambios.push('correo electrónico'); }
    let ti = String(titulo || '').replace(/^(c[oó]mo|como)\s+/i, '').trim();
    if (ti) ti = ti.charAt(0).toUpperCase() + ti.slice(1);
    return { texto_sanitizado: t, titulo_sanitizado: ti, cambios: cambios };
  }

  function avisoPrivacidad(cambios) {
    if (!cambios.length) return null;
    return 'Por seguridad, se detectaron y reemplazaron automáticamente datos personales (' + cambios.join(' y ') + ') por valores genéricos para preservarte. ' +
      'Revisá que el reemplazo no haya cambiado el sentido del texto.';
  }

  function validar(b) {
    b = b || {};
    const findings = [];
    let titulo = b.titulo || '', texto = b.texto || '', tags = b.tags || [];
    const L = lim();

    // Autosanitización inmediata
    const limpio = sanitizar(texto, titulo);
    if (limpio.cambios.length > 0) {
      b.texto = limpio.texto_sanitizado;
      b.titulo = limpio.titulo_sanitizado;
      texto = limpio.texto_sanitizado;
      titulo = limpio.titulo_sanitizado;
      findings.push({
        severity: 'Sugerencia',
        field: 'texto',
        description: 'Por seguridad, se detectaron y reemplazaron automáticamente datos personales (' + limpio.cambios.join(', ') + ') por marcadores genéricos para preservarte.',
        action: 'Revisar que el contenido conserve el sentido técnico tras el reemplazo automático.'
      });
    }

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
    if (!/ruta\s*[:>]/i.test(texto) && texto.length > 100) {
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
      texto_limpio: s.borrador ? (s.borrador.texto_limpio != null ? s.borrador.texto_limpio : (s.borrador.texto || '')) : (s.texto_limpio || s.texto_en_edicion || s.texto || null),
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
    marcar();
    if (b.metadatos_anteriores && !b.metadatos_heredados_revisados) {
      const catNom = b.metadatos_anteriores.categoria_nombre || ('Categoría ' + b.metadatos_anteriores.categoria_id);
      const tagsStr = (b.metadatos_anteriores.tags || []).join(', ') || 'ninguna';
      const avisoMeta = 'El artículo en su versión anterior tenía asociada la categoría "' + catNom + '" y las etiquetas: [' + tagsStr + ']. ' +
        'Podés tocar "Aceptar" para conservar estos metadatos o "Rechazar" si preferís definirlos manualmente.';
      const r = validarBorrador(prefijo);
      const ops = ['aceptar', 'rechazar'].concat(r.ops.filter((o) => o !== 'aceptar' && o !== 'rechazar'));
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
          return resp('No encontré nada parecido por título. Contame el contenido del artículo.', ['confirmar_texto', 'volver']);
        }

        /* ---- DECISION_TITULO ---- */
        if (sesion.estado === 'DECISION_TITULO') {
          if (opcion === 'enriquecer' || opcion === 'actualizar') {
            const el = sesion.coincidencias[0];
            const art = BACO.datos.baseConocimiento.find((a) => a.id_externo === el.id) || {};
            let textoBase = String(el.texto_original || art.extracto || '').trim();
            if (textoBase.length < L.MIN_TEXTO) {
              textoBase = 'Pasos para la configuración del artículo:\n1. Acceder al menú principal.\n2. Verificar parámetros del sistema.\n3. Guardar cambios y confirmar.';
            }
            const textoEnviado = String(req.texto || '').trim();
            let avisoEnriq = null;
            let textoIni = textoBase;
            if (textoEnviado) {
              const limpioEnv = sanitizar(textoEnviado, sesion.titulo);
              avisoEnriq = avisoPrivacidad(limpioEnv.cambios);
              textoIni = limpioEnv.texto_sanitizado;
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
              texto: textoIni,
              texto_limpio: textoIni,
              recursos: {},
              orden_multimedia: [],
              posiciones: [],
              multimedia: [],
              texto_original_aprobado: textoBase,
              tipo_plantilla: tipoPlantilla(tagsIni),
              categoria_id: req.categoria_id || sesion.categoria_id || 5,
              tags: tagsIni,
              metadatos_anteriores: metaAnt,
              metadatos_heredados_revisados: false,
              contenido_adicional: []
            };
            sesion.texto_en_edicion = textoIni;
            sesion.texto_limpio = textoIni;
            sesion.texto = textoIni;
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
            if (textoDisp && textoDisp.length >= L.MIN_TEXTO) {
              const limpioDisp = sanitizar(textoDisp, sesion.titulo);
              const avisoDisp = avisoPrivacidad(limpioDisp.cambios);
              sesion.texto = limpioDisp.texto_sanitizado;
              sesion.texto_limpio = limpioDisp.texto_sanitizado;
              const hitTxt = (sesion.texto.length >= 400) ? buscarSimilares(sesion.texto, 'texto') : null;
              if (hitTxt && !sesion.articulos_descartados_ids.includes(hitTxt.id) && !(sesion.descarto_serie && hitTxt.tipo_coincidencia === 'serie')) {
                sesion.coincidencias = [hitTxt];
                sesion.estado = 'DECISION_TEXTO';
                return resp('Encontré un artículo que explica prácticamente lo mismo en el contenido: "' +
                  hitTxt.titulo + '" (' + hitTxt.url + '). ¿Querés enriquecer ese artículo o seguimos con tu texto?',
                  OPS.ENRIQUECER_CONTINUAR, avisoDisp);
              }
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
              sesion.borrador.texto_en_edicion = sesion.texto_en_edicion;
              sesion.borrador.texto_limpio = sesion.texto_en_edicion;
              sesion.borrador.texto = sesion.texto_en_edicion;
            }
            if (sesion.texto_en_edicion.length > L.MAX_TEXTO) {
              return resp('El artículo supera los ' + L.MAX_TEXTO + ' caracteres. Dividilo o resumilo.', opsTexto, avisoFrag);
            }
            return resp('Guardé tu texto en edición (' + sesion.texto_en_edicion.length + ' / ' + L.MAX_TEXTO + ' caracteres). Podés seguir escribiendo o pegando más contenido, y cuando esté listo tocá "Confirmar texto".', opsTexto, avisoFrag);
          }

          const textoIn = String(req.texto != null ? req.texto : (sesion.texto_en_edicion || req.mensaje || '')).trim();
          if (!textoIn) return resp('Perfecto, ahora necesito que me pases el texto o los pasos del artículo para que podamos armarlo juntos. Pegalo o redactalo acá abajo cuando gustes.', ['volver']);
          if (textoIn.length < L.MIN_TEXTO) {
            return resp('El contenido es muy corto: necesito al menos ' + L.MIN_TEXTO + ' caracteres.', ['volver']);
          }
          if (textoIn.length > L.MAX_TEXTO) {
            return resp('El artículo supera los ' + L.MAX_TEXTO + ' caracteres. Dividilo o resumilo.', ['descartar', 'reiniciar']);
          }
          sesion.texto_en_edicion = '';

          const limpio = sanitizar(textoIn, sesion.titulo);
          const aviso = avisoPrivacidad(limpio.cambios);
          sesion.texto = limpio.texto_sanitizado;
          sesion.texto_limpio = sesion.texto;
          if (req.categoria_id != null) sesion.categoria_id = req.categoria_id;
          if (req.tags != null) sesion.tags = req.tags;

          if (sesion.borrador && sesion.borrador.modo === 'enriquecimiento') {
            sesion.borrador.texto = sesion.texto;
            sesion.borrador.texto_limpio = sesion.texto;
            if (sesion.borrador.recursos) {
              const marcadores = new Set((sesion.texto.match(/\[\[recurso:([^\]]+)\]\]/g) || []).map(m => m.slice(10, -2)));
              const recsFilt = {};
              Object.entries(sesion.borrador.recursos).forEach(([k, r]) => {
                if (marcadores.has(k) || (r.referencia && sesion.texto.includes(r.referencia)) || (r.url && sesion.texto.includes(r.url))) {
                  recsFilt[k] = r;
                }
              });
              sesion.borrador.recursos = recsFilt;
              sesion.borrador.multimedia = Object.values(recsFilt);
            }
            if (req.categoria_id != null) sesion.borrador.categoria_id = req.categoria_id;
            if (req.tags != null) sesion.borrador.tags = req.tags;
            return avanzar('Sumé tu texto al borrador sobre #' + sesion.borrador.articulo_original_id + '. ', aviso);
          }

          const hit = (sesion.texto.length >= 400) ? buscar(sesion.texto + ' ' + sesion.titulo) : null;
          sesion.articulos_descartados_ids = sesion.articulos_descartados_ids || [];
          if (hit && !sesion.articulos_descartados_ids.includes(hit.id) && !(sesion.descarto_serie && hit.tipo_coincidencia === 'serie')) {
            marcar();
            sesion.coincidencias = [hit];
            sesion.estado = 'DECISION_TEXTO';
            return resp('El contenido se parece bastante a "' + hit.titulo + '" (' + hit.url + '). ' +
              '¿Querés enriquecer ese artículo o seguimos con tu texto?', OPS.ENRIQUECER_CONTINUAR, aviso);
          }

          sesion.borrador = { modo: 'nuevo', articulo_original_id: null, articulo_original_url: null,
            titulo: sesion.titulo, texto: sesion.texto, texto_limpio: sesion.texto, texto_original_aprobado: null,
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
            const nomCat = art.categoria || 'Ventas';
            const metaAnt = { categoria_id: art.categoria_id || 5, categoria_nombre: nomCat, tags: tagsIni.slice() };
            const textoBase = String(el.texto_original || art.extracto || '').trim();
            let avisoDecTxt = null;
            let aporte = String(req.texto || sesion.texto_limpio || sesion.texto || '').trim();
            if (aporte) {
              const limpioAp = sanitizar(aporte, tituloFinal);
              avisoDecTxt = avisoPrivacidad(limpioAp.cambios);
              aporte = limpioAp.texto_sanitizado;
            }
            const textoIni = (textoBase && aporte && !aporte.includes(textoBase) && aporte.length < Math.min(textoBase.length * 0.4, 250))
              ? (textoBase + '\n\n' + aporte)
              : (aporte || textoBase);
            sesion.borrador = { modo: 'enriquecimiento', articulo_original_id: el.id, articulo_original_url: el.url,
              titulo: tituloFinal, texto: textoIni, texto_limpio: textoIni,
              recursos: {}, orden_multimedia: [], posiciones: [], multimedia: [],
              texto_original_aprobado: el.texto_original || null,
              tipo_plantilla: tipoPlantilla(tagsIni), categoria_id: req.categoria_id || sesion.categoria_id || 5, tags: tagsIni,
              metadatos_anteriores: metaAnt, metadatos_heredados_revisados: false,
              contenido_adicional: [] };
            sesion.texto = textoIni;
            sesion.texto_limpio = textoIni;
            return avanzar('Armé el borrador de enriquecimiento sobre #' + el.id + '. ', avisoDecTxt);
          }
          if (opcion === 'continuar' || opcion === 'descartar') {
            sesion.articulos_descartados_ids = sesion.articulos_descartados_ids || [];
            (sesion.coincidencias || []).forEach((c) => {
              if (c.id && !sesion.articulos_descartados_ids.includes(c.id)) {
                sesion.articulos_descartados_ids.push(c.id);
              }
            });
            sesion.borrador = { modo: 'nuevo', articulo_original_id: null, articulo_original_url: null,
              titulo: sesion.titulo, texto: sesion.texto, texto_limpio: sesion.texto, texto_original_aprobado: null,
              tipo_plantilla: tipoPlantilla(sesion.tags),
              categoria_id: sesion.categoria_id, tags: sesion.tags.slice() };
            return avanzar('Dale, seguimos con tu propio texto. ');
          }
          return resp('Elegí una opción para seguir.', OPS.ENRIQUECER_CONTINUAR);
        }

        /* ---- ESPERANDO_PLANTILLA ---- */
        if (sesion.estado === 'ESPERANDO_PLANTILLA') {
          const b = sesion.borrador;
          if (req.texto != null && req.texto.trim()) {
            b.texto = req.texto;
            b.texto_limpio = req.texto;
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
            const limpio = sanitizar(req.texto || b.texto, req.titulo || b.titulo);
            b.titulo = limpio.titulo_sanitizado;
            b.texto = limpio.texto_sanitizado;
            b.texto_limpio = limpio.texto_sanitizado;
            sesion.texto = b.texto;
            sesion.texto_limpio = b.texto_limpio;
            const r = validarBorrador(limpio.cambios.length ? 'Listo, limpié los datos sensibles. ' : 'Revisé el borrador y no encontré datos sensibles para limpiar. ');
            return resp(r.msg, r.ops, avisoPrivacidad(limpio.cambios));
          }

          if (huboCambios) {
            let aviso = null;
            if (req.titulo != null) b.titulo = String(req.titulo).trim();
            if (textoEd != null) {
              const limpio = sanitizar(textoEd, b.titulo);
              b.texto = limpio.cambios.length ? limpio.texto_sanitizado : String(textoEd).trim();
              b.texto_limpio = b.texto;
              sesion.texto = b.texto;
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
            const limpio = sanitizar(b.texto, b.titulo);
            b.titulo = limpio.titulo_sanitizado;
            b.texto = limpio.texto_sanitizado;
            b.texto_limpio = limpio.texto_sanitizado;
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
          throw err('HTTP_404', 'No hay un borrador en conformidad en esta sesión, o la sesión expiró.');
        }
        return JSON.parse(JSON.stringify(sesion.borrador));
      }, 200);
    },

    borradorAprobado() {
      return this.borradorConforme();
    },

    aplicarPlantilla() {
      return responder(() => {
        if (!sesion || !sesion.borrador) throw err('SIN_SESION', 'No hay un borrador activo en la sesión.');
        if (sesion.borrador.skills_habilitadas === false) {
          const e = err('VALIDACION', sesion.borrador.skills_motivo || 'Las skills de asistencia del agente están deshabilitadas para este borrador.');
          e.http = 422;
          throw e;
        }
        const tipo = sesion.borrador.tipo_plantilla || 'instructivo';
        const plantilla = BACO.datos.plantillas[tipo] || '';
        const textoResultante = '## Objetivo\nInstructivo para configurar el módulo.\n\n## Pasos a seguir\n1. Abrir menú.\n2. Guardar.';
        sesion.borrador.texto_limpio = textoResultante;
        return { response: '## Borrador reestructurado con la plantilla "' + tipo + '"\n\n' + plantilla, texto_resultante: textoResultante };
      }, cfg().LATENCIA_AGENTE_MS);
    },

    auditarSemantica() {
      return responder(() => {
        if (!sesion || !sesion.borrador) throw err('SIN_SESION', 'No hay un borrador activo en la sesión.');
        if (sesion.borrador.skills_habilitadas === false) {
          const e = err('VALIDACION', sesion.borrador.skills_motivo || 'Las skills de asistencia del agente están deshabilitadas para este borrador.');
          e.http = 422;
          throw e;
        }
        const v = validar(sesion.borrador);
        const lineas = v.findings.map((f) => '- **' + f.severity + '** (' + f.field + '): ' + f.description + ' → ' + f.action);
        const dictamen = '### Dictamen del validador\n\nEstado: **' + v.status + '**\n\n' +
          (lineas.length ? lineas.join('\n') : 'Sin observaciones.');
        return { response: dictamen, texto_resultante: sesion.borrador.texto_limpio || sesion.borrador.texto || dictamen };
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

    /* Gestión atómica de recursos multimedia (independiente de flujos) */
    obtenerRecursos() {
      return responder(() => {
        if (!sesion || !sesion.borrador) return [];
        const recs = sesion.borrador.recursos || {};
        return Object.values(recs).sort((a, b) => (a.orden || 0) - (b.orden || 0));
      }, 50);
    },

    eliminarRecurso(recursoId) {
      return responder(() => {
        if (!sesion || !sesion.borrador) throw err('SIN_SESION', 'No hay borrador activo.');
        const recs = sesion.borrador.recursos || {};
        let targetId = recursoId;
        if (typeof recursoId === 'number' || (/^\d+$/.test(recursoId) && !recs[recursoId])) {
          const sorted = Object.values(recs).sort((a, b) => (a.orden || 0) - (b.orden || 0));
          const idx = parseInt(recursoId, 10);
          if (idx >= 0 && idx < sorted.length) targetId = sorted[idx].id;
        }
        if (!recs[targetId]) throw err('NO_ENCONTRADO', 'Recurso no encontrado.');
        delete recs[targetId];
        const items = Object.values(recs).sort((a, b) => (a.orden || 0) - (b.orden || 0));
        items.forEach((r, i) => { r.orden = i; });
        sesion.borrador.orden_multimedia = items.map((_, i) => i);
        sesion.borrador.posiciones = items.map((_, i) => i);
        if (sesion.borrador.conforme) {
          sesion.borrador.conforme = false;
          sesion.borrador.conforme_en = null;
          sesion.borrador.conformidad_invalidada = true;
          if (sesion.estado === 'CONFORMIDAD_USUARIO') sesion.estado = 'REVISION_BORRADOR';
        }
        return { status: 'ok', eliminado: targetId };
      }, 50);
    },

    reordenarMultimedia(fromIndexOrVector, toIndex) {
      return responder(() => {
        if (!sesion || !sesion.borrador) throw err('SIN_SESION', 'No hay borrador activo.');
        const recs = sesion.borrador.recursos || {};
        let items = Object.values(recs).sort((a, b) => (a.orden || 0) - (b.orden || 0));
        if (typeof fromIndexOrVector === 'number' && typeof toIndex === 'number') {
          if (fromIndexOrVector < 0 || fromIndexOrVector >= items.length || toIndex < 0 || toIndex >= items.length) {
            throw err('VALIDACION', 'Índices fuera de rango.');
          }
          const moved = items.splice(fromIndexOrVector, 1)[0];
          items.splice(toIndex, 0, moved);
        } else if (Array.isArray(fromIndexOrVector)) {
          if (fromIndexOrVector.length > 0 && typeof fromIndexOrVector[0] === 'number') {
            const mapped = [];
            fromIndexOrVector.forEach(idx => { if (items[idx]) mapped.push(items[idx]); });
            items.forEach(r => { if (!mapped.includes(r)) mapped.push(r); });
            items = mapped;
          } else {
            const map = {};
            items.forEach(r => { map[r.id] = r; });
            const mapped = [];
            fromIndexOrVector.forEach(id => { if (map[id]) { mapped.push(map[id]); delete map[id]; } });
            Object.values(map).forEach(r => mapped.push(r));
            items = mapped;
          }
        }
        items.forEach((r, i) => { r.orden = i; });
        const newRecs = {};
        items.forEach(r => { newRecs[r.id] = r; });
        sesion.borrador.recursos = newRecs;
        sesion.borrador.orden_multimedia = items.map((_, i) => i);
        sesion.borrador.posiciones = items.map((_, i) => i);
        if (sesion.borrador.conforme) {
          sesion.borrador.conforme = false;
          sesion.borrador.conforme_en = null;
          sesion.borrador.conformidad_invalidada = true;
          if (sesion.estado === 'CONFORMIDAD_USUARIO') sesion.estado = 'REVISION_BORRADOR';
        }
        return items;
      }, 50);
    },

    agregarRecursoMultimedia(recurso) {
      return responder(() => {
        if (!sesion || !sesion.borrador) throw err('SIN_SESION', 'No hay borrador activo.');
        sesion.borrador.recursos = sesion.borrador.recursos || {};
        const recs = sesion.borrador.recursos;
        let items = Object.values(recs).sort((a, b) => (a.orden || 0) - (b.orden || 0));
        const rec = Object.assign({
          id: 'rec_' + Math.random().toString(36).substr(2, 8),
          tipo: 'imagen',
          nombre: 'recurso',
          referencia: '',
          tamano_bytes: 0
        }, recurso);
        const pos = typeof recurso.posicion === 'number' ? recurso.posicion : null;
        if (pos === null || pos < 0 || pos >= items.length) {
          items.push(rec);
        } else {
          items.splice(pos, 0, rec);
        }
        items.forEach((r, i) => { r.orden = i; });
        const newRecs = {};
        items.forEach(r => { newRecs[r.id] = r; });
        sesion.borrador.recursos = newRecs;
        sesion.borrador.orden_multimedia = items.map((_, i) => i);
        sesion.borrador.posiciones = items.map((_, i) => i);
        if (sesion.borrador.conforme) {
          sesion.borrador.conforme = false;
          sesion.borrador.conforme_en = null;
          sesion.borrador.conformidad_invalidada = true;
          if (sesion.estado === 'CONFORMIDAD_USUARIO') sesion.estado = 'REVISION_BORRADOR';
        }
        return rec;
      }, 50);
    },

    subirRecursoMultimedia(file, posicion) {
      return this.agregarRecursoMultimedia({
        nombre: (file && file.name) || 'archivo_adjunto',
        referencia: 'https://bc-dev.finneg.com/uploads/default/original/mock/' + ((file && file.name) || 'archivo.png'),
        tipo: (file && file.type && file.type.startsWith('image/')) ? 'imagen' : 'documento',
        origen: 'subido',
        tamano_bytes: (file && file.size) || 1024,
        posicion: posicion
      });
    },

    confirmarBloques(bloques) {
      return responder(() => {
        if (!sesion) throw err('SIN_SESION', 'No hay sesión activa.');
        const recs = {};
        const partes = [];
        let rCount = 1;
        const tiposConteo = {};
        (bloques || []).forEach((b) => {
          if (b.tipo === 'texto' && b.contenido) {
            partes.push(b.contenido.trim());
          } else if (b.tipo === 'recurso' && b.recurso) {
            const rid = 'rec_' + rCount;
            const r = {
              id: rid,
              tipo: b.recurso.tipo || 'otro',
              nombre: b.recurso.nombre || 'Recurso ' + rCount,
              referencia: b.recurso.url || '',
              orden: rCount - 1
            };
            recs[rid] = r;
            partes.push('[[R' + rCount + ']]');
            tiposConteo[r.tipo] = (tiposConteo[r.tipo] || 0) + 1;
            rCount++;
          }
        });
        const textoLimpio = partes.join('\n\n').trim();
        const sanit = sanitizar(textoLimpio, sesion.titulo || (sesion.borrador && sesion.borrador.titulo));
        const textoFinal = sanit.texto_sanitizado;
        let avisoPriv = null;
        if (sanit.cambios && sanit.cambios.length) {
          avisoPriv = 'Se detectaron y anonimizaron datos personales (' + sanit.cambios.join(', ') + ').';
        }
        if (!sesion.borrador) {
          sesion.borrador = {
            titulo: sesion.titulo || 'Artículo',
            texto_limpio: textoFinal,
            texto: textoFinal,
            recursos: recs,
            multimedia: Object.values(recs)
          };
        } else {
          sesion.borrador.texto_limpio = textoFinal;
          sesion.borrador.recursos = recs;
          sesion.borrador.multimedia = Object.values(recs);
          sesion.borrador.conforme = false;
        }
        sesion.texto_limpio = textoFinal;
        sesion.texto = textoFinal;
        sesion.recursos = recs;
        const avisoPartes = Object.entries(tiposConteo).map(([t, c]) => `${c} ${t}`);
        const avisoRecursos = avisoPartes.length ? `Se detectaron ${rCount - 1} recursos (${avisoPartes.join(', ')}).` : null;
        const avisoFinal = [avisoPriv, avisoRecursos].filter(Boolean).join('\n\n') || null;
        return {
          session_id: sesion.session_id,
          texto_limpio: textoFinal,
          recursos: Object.values(recs),
          aviso: avisoFinal,
          borrador: sesion.borrador
        };
      }, 50);
    },

    sesionActual() { return sesion ? sesion.session_id : null; },
    olvidarSesion() { sesion = null; }
  };
})();
