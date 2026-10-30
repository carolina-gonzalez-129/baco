/* =============================================================
   BACO — Interfaz
   -------------------------------------------------------------
   El backend conduce el flujo: cada turno devuelve `estado`,
   `etapa`, `tags_acumulados`, `categorias_disponibles` y
   `opciones`, y el panel se acomoda a eso.

   · Derecha (chat) = el hilo de la conversación y los botones
     que el backend habilita en cada paso.
   · Izquierda (formulario) = espejo editable del borrador con
     barra de herramientas estilo Discourse y secuencia intercalada
     de bloques Texto / Recurso / Texto.

   Esta capa no sabe si detrás hay mock o backend real.
   ============================================================= */
(function () {
  'use strict';

  const api = BACO.api;
  const store = BACO.store;
  const cfg = BACO.config || {};
  if (!cfg.MAX_TEXTO_PERCENTIL_99) {
    cfg.MAX_TEXTO_PERCENTIL_99 = 16777;
  }

  const $ = (s) => document.querySelector(s);
  const el = (t, c, h) => { const n = document.createElement(t); if (c) n.className = c; if (h != null) n.innerHTML = h; return n; };
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const hora = () => new Date().toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });

  /* Longitud en code points Unicode (alineada con len() de Python) */
  function lenCodePoints(s) {
    return Array.from(String(s == null ? '' : s)).length;
  }
  BACO.lenCodePoints = lenCodePoints;

  function clasificarRecurso(url, altOrText, isExplicitImg, isAttachment) {
    const u = String(url || '').toLowerCase();
    const t = String(altOrText || '').toLowerCase();

    if (isExplicitImg || /\.(png|jpe?g|gif|webp|svg)(\?.*)?$/i.test(u) || u.startsWith('/api/recursos-temp/')) {
      return {
        tipo: 'imagen',
        etiqueta: 'Imagen',
        icono: '🖼️',
        claseBadge: 'eib-badge-img',
        url: url,
        titulo: altOrText || 'Imagen'
      };
    }

    if (
      u.includes('docs.google.com/presentation') ||
      /\.(ppt|pptx|odp)(\?.*)?$/i.test(u) ||
      u.includes('slideshare') ||
      t.includes('diapositiva') ||
      t.includes('presentación') ||
      t.includes('presentacion') ||
      t.includes('slides')
    ) {
      return {
        tipo: 'slides',
        etiqueta: 'Diapositivas',
        icono: '📊',
        claseBadge: 'eib-badge-slides',
        url: url,
        titulo: altOrText || 'Presentación / Diapositivas'
      };
    }

    if (
      u.includes('docs.google.com/document') ||
      /\.(pdf|doc|docx|odt)(\?.*)?$/i.test(u) ||
      t.includes('documento') ||
      t.includes('docs') ||
      t.includes('guía') ||
      t.includes('guia') ||
      t.includes('manual')
    ) {
      return {
        tipo: 'doc',
        etiqueta: u.includes('docs.google.com') ? 'Google Docs' : 'Documento',
        icono: '📄',
        claseBadge: 'eib-badge-doc',
        url: url,
        titulo: altOrText || 'Documento'
      };
    }

    if (
      u.includes('youtube.com') ||
      u.includes('youtu.be') ||
      u.includes('vimeo.com') ||
      u.includes('loom.com') ||
      /\.(mp4|webm|mov|avi)(\?.*)?$/i.test(u) ||
      t.includes('video') ||
      t.includes('tutorial')
    ) {
      return {
        tipo: 'video',
        etiqueta: 'Video',
        icono: '🎬',
        claseBadge: 'eib-badge-video',
        url: url,
        titulo: altOrText || 'Video tutorial'
      };
    }

    if (isAttachment || u.includes('/uploads/')) {
      return {
        tipo: 'adjunto',
        etiqueta: 'Adjunto',
        icono: '📎',
        claseBadge: 'eib-badge-adjunto',
        url: url,
        titulo: altOrText || 'Archivo adjunto'
      };
    }

    return {
      tipo: 'enlace',
      etiqueta: 'Enlace',
      icono: '🔗',
      claseBadge: 'eib-badge-link',
      url: url,
      titulo: altOrText || url
    };
  }

  const nl2br = (s) => {
    let txt = esc(s);
    txt = txt.replace(/!\[([^\]]*)\]\(((?:https?:\/\/|\/api\/recursos-temp\/)[^\s\)]+)\)/g, '<div class="preview-img-box"><img src="$2" alt="$1" class="preview-img" loading="lazy" referrerpolicy="no-referrer" /><span class="caption">$1</span></div>');
    txt = txt.replace(/\[([^\]]+)\|attachment\]\(((?:https?:\/\/|\/api\/recursos-temp\/)[^\s\)]+)\)/g, '<a class="preview-adjunto" href="$2" target="_blank" rel="noopener">📎 $1</a>');
    txt = txt.replace(/\[([^\]]+)\]\((https?:\/\/[^\s\)]+)\)/g, (match, title, url) => {
      const rec = clasificarRecurso(url, title, false, false);
      return '<a class="chat-link" href="' + url + '" target="_blank" rel="noopener">' + rec.icono + ' ' + title + ' ↗</a>';
    });
    txt = txt.replace(/\*\*([\s\S]+?)\*\*/g, '<b>$1</b>');
    txt = txt.replace(/(^|[^\*])\*([^\*]+)\*([^\*]|$)/g, '$1<em>$2</em>$3');
    txt = txt.replace(/`([^`]+)`/g, '<code>$1</code>');
    return txt.replace(/\n/g, '<br>');
  };
  let tToast = null;
  let ultimoFallo = null;   // para poder reintentar la llamada que falló

  /* =========================================================
     Editor de Bloques Intercalados + Barra estilo Discourse
     ========================================================= */
  const MAX_ARCHIVO_BYTES = 10 * 1024 * 1024; // 10 MB
  const MAX_TOTAL_RECURSOS_BYTES = 50 * 1024 * 1024; // 50 MB
  const MAX_RECURSOS_CANTIDAD = 20;
  const MAX_BLOQUES_TEXTO = 21;
  const EMOJIS_DISCOURSE = ['😀', '👍', '✅', '⚠️', '📌', '💡', '🔧', '📄', '🚀', '🔍', '❓', '✨'];

  let bloqueSeq = 1;
  const genId = () => 'b_' + Date.now() + '_' + (bloqueSeq++);

  const estadoEditor = {
    bloques_texto: [''],
    recursos: [],
    bloques: [
      { id: genId(), tipo: 'texto', bloqueIdx: 0, contenido: '' }
    ],
    modo: 'edicion',
    enviando: false,
    menuAbiertoPos: null
  };

  const estadoVistaPrevia = {
    bloques_texto: [''],
    recursos: []
  };

  let sesionCargadaId = null;
  let ultimoTextareaActivo = null;
  let ultimoCursorCapturado = null;
  const textareasMap = new Map();
  let consultandoDocExistentePorTitulo = false;
  let tituloOriginalIngresado = '';
  let descartoDocExistentePorTitulo = false;
  let consultandoDocExistentePorTexto = false;
  let textoOriginalIngresado = '';
  let bloquesOriginalesIngresados = [''];
  let descartoDocExistentePorTexto = false;

  /* Función única que lee multimedia_habilitada de la respuesta del servidor */
  function actualizarDisponibilidadRecursos(resp) {
    if (store && typeof store.actualizarDisponibilidadRecursos === 'function') {
      return store.actualizarDisponibilidadRecursos(resp);
    }
    return Boolean(resp && resp.multimedia_habilitada === true);
  }
  BACO.actualizarDisponibilidadRecursos = actualizarDisponibilidadRecursos;

  function formatearBytes(bytes) {
    if (bytes == null || isNaN(bytes)) return '';
    if (bytes < 1024) return bytes + ' B';
    const kb = bytes / 1024;
    if (kb < 1024) return kb.toFixed(1) + ' KB';
    const mb = kb / 1024;
    return mb.toFixed(1) + ' MB';
  }

  function ordenarRecursosPorPosicionYOrden(recs) {
    return (recs || []).slice().sort((a, b) => {
      const pa = typeof a.posicion === 'number' ? a.posicion : 0;
      const pb = typeof b.posicion === 'number' ? b.posicion : 0;
      if (pa !== pb) return pa - pb;
      return (a.orden || 0) - (b.orden || 0);
    });
  }

  function calcularTamanioTotalRecursos(recursosLista) {
    const lista = Array.isArray(recursosLista) ? recursosLista : estadoEditor.recursos;
    return (lista || []).reduce((acc, r) => {
      const bytes = typeof r.tamano_bytes === 'number'
        ? r.tamano_bytes
        : (typeof r.tamanio === 'number' ? r.tamanio : 0);
      return acc + bytes;
    }, 0);
  }

  /* Validación cliente reutilizable: 10 MB/archivo, 50 MB/sesión, máx. 20 recursos, máx. 21 bloques, sin .svg */
  function validarArchivoCliente(file, recursosActuales, cantidadBloquesResultante) {
    if (!file) return { valido: false, error: 'No se seleccionó ningún archivo.' };
    const nombre = String(file.name || '').toLowerCase();
    const mime = String(file.type || '').toLowerCase();

    if (nombre.endsWith('.svg') || mime === 'image/svg+xml') {
      return { valido: false, error: 'No se permiten archivos SVG por motivos de seguridad.' };
    }
    if (file.size > MAX_ARCHIVO_BYTES) {
      return { valido: false, error: 'El archivo supera el tamaño máximo permitido de 10 MB.' };
    }
    const listaRecs = Array.isArray(recursosActuales) ? recursosActuales : estadoEditor.recursos;
    if (listaRecs.length >= MAX_RECURSOS_CANTIDAD) {
      return { valido: false, error: 'Se alcanzó el límite máximo de 20 recursos multimedia por artículo.' };
    }
    if (typeof cantidadBloquesResultante === 'number' && cantidadBloquesResultante > MAX_BLOQUES_TEXTO) {
      return { valido: false, error: 'Se alcanzó el límite máximo de 21 bloques de texto.' };
    }
    const totalActual = calcularTamanioTotalRecursos(listaRecs);
    if (totalActual + (file.size || 0) > MAX_TOTAL_RECURSOS_BYTES) {
      return { valido: false, error: 'El tamaño acumulado de los recursos superaría el límite de 50 MB.' };
    }
    return { valido: true, error: null };
  }
  BACO.validarArchivoCliente = validarArchivoCliente;

  /* Parte el bloque de texto en la posición del cursor para intercalar un recurso en el medio.
     Si no hay foco en un bloque válido, no parte y devuelve posicion = bloques.length - 1 (al final). */
  function partirBloqueEnCursor(bloquesTexto, bloqueIdxConFoco, selectionStart, selectionEnd) {
    const base = Array.isArray(bloquesTexto) && bloquesTexto.length
      ? bloquesTexto.map((t) => String(t == null ? '' : t))
      : [''];

    if (
      typeof bloqueIdxConFoco !== 'number' ||
      bloqueIdxConFoco < 0 ||
      bloqueIdxConFoco >= base.length ||
      typeof selectionStart !== 'number'
    ) {
      return {
        bloques_texto: base.slice(),
        posicion: base.length - 1,
        partido: false
      };
    }

    const textoBloque = base[bloqueIdxConFoco];
    const start = Math.max(0, Math.min(textoBloque.length, selectionStart));
    const end = typeof selectionEnd === 'number'
      ? Math.max(start, Math.min(textoBloque.length, selectionEnd))
      : start;

    const anterior = textoBloque.slice(0, start);
    const posterior = textoBloque.slice(end);
    const nuevosBloques = base.slice(0, bloqueIdxConFoco)
      .concat([anterior, posterior])
      .concat(base.slice(bloqueIdxConFoco + 1));

    return {
      bloques_texto: nuevosBloques,
      posicion: bloqueIdxConFoco,
      partido: true
    };
  }
  BACO.partirBloqueEnCursor = partirBloqueEnCursor;

  /* Inserta o envuelve la selección con sintaxis Markdown en el textarea dado */
  function insertarFormatoMarkdown(textarea, tipo) {
    if (!textarea || textarea.disabled) return '';
    const val = String(textarea.value || '');
    const start = typeof textarea.selectionStart === 'number' ? textarea.selectionStart : val.length;
    const end = typeof textarea.selectionEnd === 'number' ? textarea.selectionEnd : start;
    const sel = val.slice(start, end);
    const antes = val.slice(0, start);
    const despues = val.slice(end);

    let reemplazo = '';
    let nuevoCursorIni = start;
    let nuevoCursorFin = end;

    if (tipo === 'bold') {
      const inner = sel || 'texto en negrita';
      reemplazo = '**' + inner + '**';
      nuevoCursorIni = start + 2;
      nuevoCursorFin = nuevoCursorIni + inner.length;
    } else if (tipo === 'italic') {
      const inner = sel || 'texto en cursiva';
      reemplazo = '*' + inner + '*';
      nuevoCursorIni = start + 1;
      nuevoCursorFin = nuevoCursorIni + inner.length;
    } else if (tipo === 'heading') {
      const prefijoLinea = (antes.length > 0 && !antes.endsWith('\n')) ? '\n' : '';
      const inner = sel || 'Título de sección';
      reemplazo = prefijoLinea + '### ' + inner;
      nuevoCursorIni = start + prefijoLinea.length + 4;
      nuevoCursorFin = nuevoCursorIni + inner.length;
    } else if (tipo === 'link') {
      const inner = sel || 'texto del enlace';
      const sufijoUrl = '(https://)';
      reemplazo = '[' + inner + ']' + sufijoUrl;
      nuevoCursorIni = start + 1;
      nuevoCursorFin = nuevoCursorIni + inner.length;
    } else if (tipo === 'quote') {
      const prefijoLinea = (antes.length > 0 && !antes.endsWith('\n')) ? '\n' : '';
      const inner = sel || 'Cita';
      const citado = inner.split('\n').map((l) => '> ' + l).join('\n');
      reemplazo = prefijoLinea + citado;
      nuevoCursorIni = start + prefijoLinea.length + 2;
      nuevoCursorFin = start + reemplazo.length;
    } else if (tipo === 'code') {
      const inner = sel || 'código';
      if (inner.includes('\n')) {
        const prefijoLinea = (antes.length > 0 && !antes.endsWith('\n')) ? '\n' : '';
        reemplazo = prefijoLinea + '```\n' + inner + '\n```';
        nuevoCursorIni = start + prefijoLinea.length + 4;
        nuevoCursorFin = nuevoCursorIni + inner.length;
      } else {
        reemplazo = '`' + inner + '`';
        nuevoCursorIni = start + 1;
        nuevoCursorFin = nuevoCursorIni + inner.length;
      }
    } else if (tipo === 'list') {
      const prefijoLinea = (antes.length > 0 && !antes.endsWith('\n')) ? '\n' : '';
      const inner = sel || 'Elemento de lista';
      const listado = inner.split('\n').map((l) => '- ' + l).join('\n');
      reemplazo = prefijoLinea + listado;
      nuevoCursorIni = start + prefijoLinea.length + 2;
      nuevoCursorFin = start + reemplazo.length;
    } else {
      return val;
    }

    textarea.value = antes + reemplazo + despues;
    if (typeof textarea.focus === 'function') textarea.focus();
    if (typeof textarea.setSelectionRange === 'function') {
      try { textarea.setSelectionRange(nuevoCursorIni, nuevoCursorFin); } catch (_) {}
    }
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    return textarea.value;
  }
  BACO.insertarFormatoMarkdown = insertarFormatoMarkdown;

  function obtenerTextareaObjetivo() {
    if (
      document.activeElement &&
      document.activeElement.classList &&
      document.activeElement.classList.contains('bloque-textarea') &&
      !document.activeElement.disabled
    ) {
      return document.activeElement;
    }
    if (ultimoTextareaActivo && document.body.contains(ultimoTextareaActivo) && !ultimoTextareaActivo.disabled) {
      return ultimoTextareaActivo;
    }
    const primero = $('.bloque-textarea:not(:disabled)');
    return primero || null;
  }

  /* Arma la lista visual intercalada en estadoEditor.bloques a partir de
     estadoEditor.bloques_texto y estadoEditor.recursos (ordenados por (posicion, orden)) */
  function sincronizarSecuenciaVisual() {
    const bloquesTxt = Array.isArray(estadoEditor.bloques_texto) && estadoEditor.bloques_texto.length
      ? estadoEditor.bloques_texto
      : [''];
    const recsOrd = ordenarRecursosPorPosicionYOrden(estadoEditor.recursos || []);
    const secuencia = [];

    // Recursos con posicion === -1 van antes del primer bloque de texto
    recsOrd.filter((r) => r.posicion === -1).forEach((r) => {
      secuencia.push({
        id: 'rec_item_' + r.id,
        tipo: 'recurso',
        cargando: Boolean(r.cargando),
        recurso: r
      });
    });

    for (let i = 0; i < bloquesTxt.length; i++) {
      secuencia.push({
        id: 'txt_block_' + i,
        tipo: 'texto',
        bloqueIdx: i,
        contenido: String(bloquesTxt[i] == null ? '' : bloquesTxt[i])
      });

      recsOrd
        .filter((r) => (typeof r.posicion === 'number' ? r.posicion : 0) === i)
        .forEach((r) => {
          secuencia.push({
            id: 'rec_item_' + r.id,
            tipo: 'recurso',
            cargando: Boolean(r.cargando),
            recurso: r
          });
        });
    }

    // Fallback defensivo si algún recurso tuviera posicion >= bloquesTxt.length
    recsOrd
      .filter((r) => typeof r.posicion === 'number' && r.posicion >= bloquesTxt.length)
      .forEach((r) => {
        secuencia.push({
          id: 'rec_item_' + r.id,
          tipo: 'recurso',
          cargando: Boolean(r.cargando),
          recurso: r
        });
      });

    estadoEditor.bloques = secuencia;
  }

  /* Une solo los bloques de texto (nunca incluye sintaxis Markdown de imágenes ni [[recurso:...]]) */
  function componerTextoDesdeBloques() {
    return (estadoEditor.bloques_texto || [''])
      .map((t) => String(t == null ? '' : t).trim())
      .filter(Boolean)
      .join('\n\n');
  }

  function sincronizarTextoConStore() {
    const limpio = componerTextoDesdeBloques();
    store.setForm({ texto: limpio });
    const fc = $('#fCuerpo');
    if (fc) fc.value = limpio;
  }

  function crearDivisor(pos, deshabilitado) {
    const div = document.createElement('div');
    div.className = 'bloque-divider';
    div.hidden = true;
    const line = document.createElement('div');
    line.className = 'bloque-divider-line';
    div.appendChild(line);
    return div;
  }

  function crearItemTexto(b, deshabilitado) {
    const item = document.createElement('div');
    item.className = 'bloque-texto-item';
    item.setAttribute('data-id', b.id);
    item.setAttribute('data-bloque-idx', String(b.bloqueIdx));

    let textarea = textareasMap.get(b.id);
    if (!textarea) {
      textarea = document.createElement('textarea');
      textarea.className = 'bloque-textarea';
      textarea.setAttribute('data-id', b.id);
      textarea.setAttribute('data-bloque-idx', String(b.bloqueIdx));
      textarea.placeholder = b.bloqueIdx === 0
        ? 'Escribí el texto acá en formato Markdown...'
        : 'Continuá escribiendo el bloque de texto...';
      textareasMap.set(b.id, textarea);
    }
    textarea.setAttribute('data-bloque-idx', String(b.bloqueIdx));
    textarea.disabled = deshabilitado;
    if (document.activeElement !== textarea && textarea.value !== (b.contenido || '')) {
      textarea.value = b.contenido || '';
    }

    item.appendChild(textarea);
    return item;
  }

  function puedeSubirRecurso(r) {
    const recs = ordenarRecursosPorPosicionYOrden(estadoEditor.recursos);
    const idx = recs.findIndex((x) => x.id === r.id);
    if (idx === -1) return false;
    const pos = typeof r.posicion === 'number' ? r.posicion : 0;
    if (idx > 0 && recs[idx - 1].posicion === pos) return true;
    return pos > -1;
  }

  function puedeBajarRecurso(r) {
    const recs = ordenarRecursosPorPosicionYOrden(estadoEditor.recursos);
    const idx = recs.findIndex((x) => x.id === r.id);
    if (idx === -1) return false;
    const pos = typeof r.posicion === 'number' ? r.posicion : 0;
    if (idx < recs.length - 1 && recs[idx + 1].posicion === pos) return true;
    const maxPos = Math.max(0, (estadoEditor.bloques_texto || ['']).length - 1);
    return pos < maxPos;
  }

  function crearItemRecurso(b, idx, total, deshabilitado) {
    const r = b.recurso || {};
    const recId = r.id || b.id;
    const item = document.createElement('div');
    item.className = 'bloque-recurso-item' + (b.cargando ? ' cargando' : '');
    item.setAttribute('data-id', recId);
    item.setAttribute('data-recurso-id', recId);
    item.setAttribute('data-posicion', String(typeof r.posicion === 'number' ? r.posicion : 0));
    item.setAttribute('data-orden', String(typeof r.orden === 'number' ? r.orden : 0));
    item.setAttribute('draggable', (b.cargando || deshabilitado) ? 'false' : 'true');

    // 1. Botón 'x' pequeña a la izquierda para eliminar
    const btnX = document.createElement('button');
    btnX.type = 'button';
    btnX.className = 'bloque-eliminar-btn';
    btnX.textContent = '×';
    btnX.setAttribute('data-accion', 'eliminar-bloque');
    btnX.setAttribute('data-id', recId);
    btnX.title = 'Eliminar recurso';
    btnX.setAttribute('aria-label', 'Eliminar recurso ' + (r.nombre || recId));
    if (b.cargando || deshabilitado) btnX.disabled = true;
    item.appendChild(btnX);

    // Asa de arrastre
    const asa = document.createElement('span');
    asa.className = 'bloque-recurso-asa';
    asa.textContent = '⠿';
    asa.title = 'Arrastrar para reordenar';
    asa.setAttribute('aria-hidden', 'true');
    item.appendChild(asa);

    // 2. Icono o miniatura
    const tipo = r.tipo || 'imagen';
    const url = b.previewUrl || r.referencia || r.url || '';

    if (tipo === 'imagen' && url) {
      const img = document.createElement('img');
      img.className = 'bloque-recurso-mini';
      img.src = url;
      img.alt = r.nombre || 'Imagen';
      img.loading = 'lazy';
      item.appendChild(img);
    } else {
      const ico = document.createElement('span');
      ico.className = 'bloque-recurso-icono';
      ico.textContent = tipo === 'video' ? '🎬' : (tipo === 'documento' || tipo === 'archivo' ? '📄' : '🖼️');
      item.appendChild(ico);
    }

    // 3. Info del recurso
    const info = document.createElement('div');
    info.className = 'bloque-recurso-info';

    const nom = document.createElement('span');
    nom.className = 'bloque-recurso-nombre';
    nom.textContent = r.nombre || 'Recurso sin nombre';
    info.appendChild(nom);

    const meta = document.createElement('span');
    meta.className = 'bloque-recurso-meta';
    if (b.cargando) {
      meta.textContent = 'Subiendo recurso…';
    } else {
      const tipoLabel = tipo === 'imagen' ? 'Imagen' : (tipo === 'video' ? 'Video' : 'Archivo');
      const bytes = typeof r.tamano_bytes === 'number' ? r.tamano_bytes : r.tamanio;
      const tamLabel = bytes ? ' · ' + formatearBytes(bytes) : '';
      meta.textContent = tipoLabel + tamLabel;
    }
    info.appendChild(meta);
    item.appendChild(info);

    // 4. Botones subir / bajar
    const mover = document.createElement('div');
    mover.className = 'bloque-recurso-mover';

    const btnSubir = document.createElement('button');
    btnSubir.type = 'button';
    btnSubir.className = 'bloque-btn-mover';
    btnSubir.textContent = '↑';
    btnSubir.setAttribute('data-accion', 'subir-bloque');
    btnSubir.setAttribute('data-id', recId);
    btnSubir.title = 'Subir recurso';
    btnSubir.setAttribute('aria-label', 'Subir recurso');
    if (!puedeSubirRecurso(r) || b.cargando || deshabilitado) btnSubir.disabled = true;
    mover.appendChild(btnSubir);

    const btnBajar = document.createElement('button');
    btnBajar.type = 'button';
    btnBajar.className = 'bloque-btn-mover';
    btnBajar.textContent = '↓';
    btnBajar.setAttribute('data-accion', 'bajar-bloque');
    btnBajar.setAttribute('data-id', recId);
    btnBajar.title = 'Bajar recurso';
    btnBajar.setAttribute('aria-label', 'Bajar recurso');
    if (!puedeBajarRecurso(r) || b.cargando || deshabilitado) btnBajar.disabled = true;
    mover.appendChild(btnBajar);

    item.appendChild(mover);

    return item;
  }

  function renderBloques() {
    const cont = $('#contenedorBloques');
    if (!cont) return;

    const s = store.get();
    const act = (BACO.CAMPOS_ACTIVOS && BACO.CAMPOS_ACTIVOS[s.flujo]) || {};
    const deshabilitado = !act.texto || s.enviando || estadoEditor.enviando;

    const wrapper = $('#editorBloquesWrapper');
    if (wrapper) {
      wrapper.classList.toggle('cargando', Boolean(estadoEditor.enviando));
    }

    sincronizarSecuenciaVisual();

    const frag = document.createDocumentFragment();
    const total = estadoEditor.bloques.length;

    const idsValidos = new Set(estadoEditor.bloques.map((b) => b.id));
    for (const id of textareasMap.keys()) {
      if (!idsValidos.has(id)) textareasMap.delete(id);
    }

    // Único divisor superior (oculto visualmente, preservado por contrato de layout)
    frag.appendChild(crearDivisor(0, deshabilitado));

    estadoEditor.bloques.forEach((b, idx) => {
      if (b.tipo === 'texto') {
        frag.appendChild(crearItemTexto(b, deshabilitado));
      } else if (b.tipo === 'recurso') {
        frag.appendChild(crearItemRecurso(b, idx, total, deshabilitado));
      }
    });

    cont.replaceChildren(frag);

    const btnConfirmar = $('#btnConfirmarBloques');
    if (btnConfirmar) {
      btnConfirmar.disabled = deshabilitado;
      btnConfirmar.textContent = estadoEditor.enviando ? 'Confirmando…' : 'Confirmar';
    }
  }

  /* Aplica el estado unificado devuelto por el servidor (bloques_texto + recursos con posicion y orden)
     sin calcular fusiones ni invariantes por cuenta del front. */
  function aplicarEstadoRecursosServidor(res) {
    if (!res) return;
    const st = store.get();
    const esEnriquecer = Boolean(st && st.borrador && st.borrador.modo === 'enriquecimiento');

    if (Array.isArray(res.recursos)) {
      estadoVistaPrevia.recursos = ordenarRecursosPorPosicionYOrden(res.recursos);
    }
    if (Array.isArray(res.bloques_texto)) {
      estadoVistaPrevia.bloques_texto = res.bloques_texto.map((t) => String(t == null ? '' : t));
    }

    if (!esEnriquecer) {
      textareasMap.clear();
      if (Array.isArray(res.bloques_texto) && res.bloques_texto.length) {
        estadoEditor.bloques_texto = res.bloques_texto.map((t) => String(t == null ? '' : t));
      }
      if (Array.isArray(res.recursos)) {
        estadoEditor.recursos = ordenarRecursosPorPosicionYOrden(res.recursos);
      }
      renderBloques();
      const fc = $('#fCuerpo');
      if (fc && typeof res.texto_limpio === 'string') {
        fc.value = res.texto_limpio;
      }
    }
    store.actualizarRecursos(res);
    renderVistaPreviaEditable();
  }

  /* Reconstruye estadoEditor desde el borrador / respuesta del servidor */
  function reconstruirBloques(textoOBloques, recs, borradorOpcional) {
    textareasMap.clear();
    const recsArray = Array.isArray(recs) ? recs : Object.values(recs || {});
    estadoEditor.recursos = ordenarRecursosPorPosicionYOrden(recsArray);

    if (Array.isArray(textoOBloques) && textoOBloques.length) {
      estadoEditor.bloques_texto = textoOBloques.map((t) => String(t == null ? '' : t));
    } else if (borradorOpcional && Array.isArray(borradorOpcional.bloques_texto) && borradorOpcional.bloques_texto.length) {
      estadoEditor.bloques_texto = borradorOpcional.bloques_texto.map((t) => String(t == null ? '' : t));
    } else if (typeof textoOBloques === 'string') {
      estadoEditor.bloques_texto = [textoOBloques];
    } else {
      estadoEditor.bloques_texto = [''];
    }

    sincronizarSecuenciaVisual();
  }

  /* Elimina un recurso llamando a DELETE /chat/recursos/{id} y renderiza la respuesta del servidor */
  async function eliminarBloque(recId) {
    if (!recId || estadoEditor.enviando) return;
    estadoEditor.enviando = true;
    renderBloques();
    try {
      const res = await api.eliminarRecurso(recId);
      estadoEditor.enviando = false;
      if (res && (Array.isArray(res.bloques_texto) || Array.isArray(res.recursos))) {
        aplicarEstadoRecursosServidor(res);
      } else {
        const estadoRecs = await api.obtenerRecursos();
        aplicarEstadoRecursosServidor(estadoRecs);
      }
      toast('Recurso eliminado');
    } catch (err) {
      estadoEditor.enviando = false;
      renderBloques();
      toast('Error al eliminar recurso: ' + (err.message || 'Error'));
    }
  }

  /* Reordena un recurso llamando a PUT /chat/recursos/reordenar y renderiza la respuesta del servidor */
  async function moverBloque(recId, direccion) {
    if (!recId || estadoEditor.enviando) return;
    const recs = ordenarRecursosPorPosicionYOrden(estadoEditor.recursos);
    const idx = recs.findIndex((r) => r.id === recId);
    if (idx === -1) return;

    const actual = recs[idx];
    const posActual = typeof actual.posicion === 'number' ? actual.posicion : 0;
    const maxPos = Math.max(0, (estadoEditor.bloques_texto || ['']).length - 1);

    let payload = null;
    if (direccion === 'subir') {
      if (idx > 0 && recs[idx - 1].posicion === posActual) {
        payload = { id: recId, posicion: posActual, orden: Math.max(0, idx - 1) };
      } else if (posActual > -1) {
        payload = { id: recId, posicion: posActual - 1, orden: idx };
      }
    } else if (direccion === 'bajar') {
      if (idx < recs.length - 1 && recs[idx + 1].posicion === posActual) {
        payload = { id: recId, posicion: posActual, orden: idx + 1 };
      } else if (posActual < maxPos) {
        payload = { id: recId, posicion: posActual + 1, orden: idx };
      }
    }
    if (!payload) return;

    estadoEditor.enviando = true;
    renderBloques();
    try {
      const res = await api.reordenarMultimedia(payload);
      estadoEditor.enviando = false;
      if (res && (Array.isArray(res.bloques_texto) || Array.isArray(res.recursos))) {
        aplicarEstadoRecursosServidor(res);
      } else {
        const estadoRecs = await api.obtenerRecursos();
        aplicarEstadoRecursosServidor(estadoRecs);
      }
    } catch (err) {
      estadoEditor.enviando = false;
      renderBloques();
      toast('Error al reordenar recurso: ' + (err.message || 'Error'));
    }
  }

  async function reordenarRecursoHaciaDestino(recId, nuevaPosicion, nuevoOrden) {
    if (!recId || estadoEditor.enviando) return;
    estadoEditor.enviando = true;
    renderBloques();
    try {
      const res = await api.reordenarMultimedia({
        id: recId,
        posicion: nuevaPosicion,
        orden: typeof nuevoOrden === 'number' ? nuevoOrden : estadoEditor.recursos.length
      });
      estadoEditor.enviando = false;
      if (res && (Array.isArray(res.bloques_texto) || Array.isArray(res.recursos))) {
        aplicarEstadoRecursosServidor(res);
      } else {
        const estadoRecs = await api.obtenerRecursos();
        aplicarEstadoRecursosServidor(estadoRecs);
      }
    } catch (err) {
      estadoEditor.enviando = false;
      renderBloques();
      toast('Error al reordenar recurso: ' + (err.message || 'Error'));
    }
  }

  function capturarCursorActualParaImagen() {
    const activo = document.activeElement;
    if (activo && activo.classList && activo.classList.contains('bloque-textarea') && !activo.disabled) {
      const idx = parseInt(activo.getAttribute('data-bloque-idx'), 10);
      return {
        tieneFoco: !isNaN(idx),
        bloqueIdx: isNaN(idx) ? null : idx,
        selectionStart: typeof activo.selectionStart === 'number' ? activo.selectionStart : activo.value.length,
        selectionEnd: typeof activo.selectionEnd === 'number' ? activo.selectionEnd : activo.value.length
      };
    }
    return { tieneFoco: false, bloqueIdx: null, selectionStart: null, selectionEnd: null };
  }

  function abrirSelectorImagenToolbar() {
    const s = store.get();
    if (!s || s.multimedia_habilitada !== true) {
      toast('Disponible al finalizar las validaciones');
      return;
    }
    const input = $('#inputSelectorBloque');
    if (!input) return;
    input.accept = 'image/png,image/jpeg,image/webp,image/gif';
    input.value = '';
    input.click();
  }

  async function validarYSubirArchivoIntercalado(file, cursorInfo) {
    if (!file) return;
    const s = store.get();
    if (!s || s.multimedia_habilitada !== true) {
      toast('Disponible al finalizar las validaciones');
      return;
    }

    const particion = (cursorInfo && cursorInfo.tieneFoco)
      ? partirBloqueEnCursor(
          estadoEditor.bloques_texto,
          cursorInfo.bloqueIdx,
          cursorInfo.selectionStart,
          cursorInfo.selectionEnd
        )
      : partirBloqueEnCursor(estadoEditor.bloques_texto, null, null, null);

    const check = validarArchivoCliente(file, estadoEditor.recursos, particion.bloques_texto.length);
    if (!check.valido) {
      toast(check.error);
      return;
    }

    estadoEditor.enviando = true;
    renderBloques();

    try {
      const res = await api.subirRecursoMultimedia(file, particion.posicion, particion.bloques_texto);
      estadoEditor.enviando = false;
      if (res && (Array.isArray(res.bloques_texto) || Array.isArray(res.recursos))) {
        aplicarEstadoRecursosServidor(res);
      } else {
        const estadoRecs = await api.obtenerRecursos();
        aplicarEstadoRecursosServidor(estadoRecs);
      }
      toast('Imagen agregada correctamente');
    } catch (err) {
      estadoEditor.enviando = false;
      renderBloques();
      toast('Error al subir imagen: ' + (err.message || 'Error'));
    }
  }

  async function confirmarBloques() {
    if (estadoEditor.enviando) return;
    const s = store.get();
    if (s.enviando) return;

    const payloadBloques = [];
    sincronizarSecuenciaVisual();
    estadoEditor.bloques.forEach((b) => {
      if (b.tipo === 'texto') {
        payloadBloques.push({
          tipo: 'texto',
          contenido: b.contenido || ''
        });
      } else if (b.tipo === 'recurso' && b.recurso) {
        const recObj = {
          nombre: b.recurso.nombre || '',
          tipo: b.recurso.tipo || 'imagen'
        };
        if (b.recurso.id) {
          recObj.id = b.recurso.id;
        }
        if (b.recurso.referencia || b.recurso.url) {
          recObj.url = b.recurso.referencia || b.recurso.url;
        }
        payloadBloques.push({
          tipo: 'recurso',
          recurso: recObj
        });
      }
    });

    estadoEditor.enviando = true;
    renderBloques();

    try {
      const res = await api.confirmarBloques(payloadBloques);
      estadoEditor.enviando = false;

      if (res) {
        const recs = res.recursos || (res.borrador && (Array.isArray(res.borrador.multimedia) ? res.borrador.multimedia : Object.values(res.borrador.recursos || {}))) || [];
        const bloquesSrv = res.bloques_texto || (res.borrador && res.borrador.bloques_texto) || [res.texto_limpio || ''];
        reconstruirBloques(bloquesSrv, recs, res.borrador);
        const fc = $('#fCuerpo');
        if (fc && res.texto_limpio != null) fc.value = res.texto_limpio;
        if (res.texto_limpio != null) store.setForm({ texto: res.texto_limpio });
        if (res.borrador) {
          store.set({ borrador: res.borrador });
        } else {
          store.actualizarRecursos(res);
        }
        toast(res.aviso || 'Bloques confirmados correctamente');
      }
      renderBloques();
    } catch (err) {
      estadoEditor.enviando = false;
      renderBloques();
      toast('Error al confirmar bloques: ' + (err.message || 'Error'));
    }
  }

  function sincronizarBloquesDesdeStore(s) {
    if (!s) return;
    const sesionCambio = s.session_id !== sesionCargadaId;
    const b = s.borrador;
    const bloquesStore = (b && Array.isArray(b.bloques_texto) && b.bloques_texto.length)
      ? b.bloques_texto
      : [(s.form && s.form.texto) || (b && b.texto_limpio) || ''];
    const recs = (b && (Array.isArray(b.multimedia) ? b.multimedia : Object.values(b.recursos || {}))) || [];
    const editandoEnBloque = document.activeElement && document.activeElement.classList && document.activeElement.classList.contains('bloque-textarea');

    if (sesionCambio) {
      sesionCargadaId = s.session_id;
      if (b && b.modo === 'enriquecimiento') {
        const textoUsuario = (typeof b.texto_editor === 'string') ? b.texto_editor : '';
        reconstruirBloques([textoUsuario], [], b);
        estadoVistaPrevia.bloques_texto = Array.isArray(b.bloques_texto) ? b.bloques_texto.map((t) => String(t == null ? '' : t)) : [''];
        estadoVistaPrevia.recursos = ordenarRecursosPorPosicionYOrden(Array.isArray(b.multimedia) ? b.multimedia : Object.values(b.recursos || {}));
      } else {
        reconstruirBloques(bloquesStore, recs, b);
      }
      renderBloques();
    } else if (!estadoEditor.bloques_texto || !estadoEditor.bloques_texto.length) {
      if (b && b.modo === 'enriquecimiento') {
        const textoUsuario = (typeof b.texto_editor === 'string') ? b.texto_editor : '';
        reconstruirBloques([textoUsuario], [], b);
        estadoVistaPrevia.bloques_texto = Array.isArray(b.bloques_texto) ? b.bloques_texto.map((t) => String(t == null ? '' : t)) : [''];
        estadoVistaPrevia.recursos = ordenarRecursosPorPosicionYOrden(Array.isArray(b.multimedia) ? b.multimedia : Object.values(b.recursos || {}));
      } else {
        reconstruirBloques(bloquesStore, recs, b);
      }
      renderBloques();
    }
  }

  /* =========================================================
     Arranque
     ========================================================= */
  async function iniciar() {
    $('#modo').innerHTML = api.esMock
      ? '<span class="dot amarillo"></span> simulado'
      : '<span class="dot verde"></span> backend';
    $('#pie').textContent = api.esMock ? 'modo mock' : cfg.BASE_URL;

    inicializarEmojiPicker();
    conectarEventos();
    conectarEventosMultimedia();
    store.suscribir(pintar);
    await enviarTurno({});     // primer turno: trae la bienvenida
  }

  /* =========================================================
     Un turno contra el backend
     ========================================================= */
    function anonimizarTextoFront(str) {
    if (!str || typeof str !== 'string') return str;
    let t = str;
    t = t.replace(/\b\d{22}\b/g, '[CBU_OCULTO]');
    t = t.replace(/\b(?:\d[ -]*?){13,19}\b/g, (m) => {
      const d = m.replace(/[\s-]/g, '');
      return (d.length >= 13 && d.length <= 19) ? '[TARJETA_CREDITO]' : m;
    });
    t = t.replace(/\b(?:20|23|24|27)-?\d{8}-?\d\b/g, '[CUIT]');
    t = t.replace(/(?:DNI|documento|doc\.?)\s*(?:N[°ºo]\s*)?[:\s]*([0-9]{1,2}(?:\.[0-9]{3}){2}|[0-9]{7,8})\b/gi, (m) => {
      const idx = m.search(/([0-9]{1,2}(?:\.[0-9]{3}){2}|[0-9]{7,8})/);
      return (idx !== -1 ? m.slice(0, idx) : '') + '[DOCUMENTO_OCULTO]';
    });
    t = t.replace(/(?:cvv|cvc|código\s+de\s+seguridad)\s*[:=]?\s*\d{3,4}\b/gi, '[CVV_OCULTO]');
    t = t.replace(/(?:token|api[_-]?key|secret|password|contrase[ñn]a)\s*[:=]?\s*['"]?[^\s'",;]{8,}['"]?/gi, '[TOKEN_OCULTO]');
    t = t.replace(/\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b/g, (m, loc, dom) => {
      const d = dom.toLowerCase();
      if (d === 'ejemplo.com' || d.endsWith('.ejemplo.com') || d === 'example.com') return m;
      return 'usuario@ejemplo.com';
    });
    return t;
  }

  async function enviarTurno(payload, etiquetaUsuario) {
    const cuerpo = Object.assign({}, payload);
    if (cuerpo && cuerpo.titulo) {
      tituloOriginalIngresado = cuerpo.titulo;
    }

    let msgNodoUsuario = null;
    if (etiquetaUsuario) msgNodoUsuario = burbuja('me', esc(anonimizarTextoFront(etiquetaUsuario)));
    const htmlEspera = (cuerpo && cuerpo.accion === 'confirmar_texto')
      ? '<div class="typing-wrap"><div class="typing"><i></i><i></i><i></i></div><span class="typing-lbl">Baco está buscando…</span></div>'
      : '<div class="typing"><i></i><i></i><i></i></div>';
    const esperando = burbuja('bot', htmlEspera);
    store.set({ enviando: true, error: null });

    try {
      const r = await api.turno(cuerpo);
      esperando.remove();
      ultimoFallo = null;
      if (r && (r.borrador || typeof r.texto_limpio === 'string')) {
        const b = r.borrador;
        if (b && b.modo === 'enriquecimiento') {
          const textoUsuario = (typeof b.texto_editor === 'string') ? b.texto_editor : '';
          reconstruirBloques([textoUsuario], [], b);
          if (Array.isArray(b.bloques_texto)) {
            estadoVistaPrevia.bloques_texto = b.bloques_texto.map((t) => String(t == null ? '' : t));
          }
          if (Array.isArray(b.multimedia) || b.recursos) {
            estadoVistaPrevia.recursos = ordenarRecursosPorPosicionYOrden(Array.isArray(b.multimedia) ? b.multimedia : Object.values(b.recursos || {}));
          }
        } else {
          const bloquesAutorizados = (b && Array.isArray(b.bloques_texto) && b.bloques_texto.length)
            ? b.bloques_texto
            : [b ? (b.texto_limpio != null ? b.texto_limpio : (b.texto || '')) : r.texto_limpio];
          const recsAutorizados = b
            ? (Array.isArray(b.multimedia) ? b.multimedia : Object.values(b.recursos || {}))
            : [];
          reconstruirBloques(bloquesAutorizados, recsAutorizados, b);
        }
        renderBloques();
      } else if (r && !r.borrador && !r.texto_limpio && r.estado === 'ESPERANDO_TEXTO') {
        const bloquesAUsar = (descartoDocExistentePorTexto && textoOriginalIngresado) ? [textoOriginalIngresado] : [''];
        reconstruirBloques(bloquesAUsar, [], null);
        renderBloques();
      }
      store.aplicarTurno(r);
      if (msgNodoUsuario && (r.aviso_privacidad || r.titulo || (r.borrador && r.borrador.titulo) || r.texto_limpio || (r.borrador && r.borrador.texto_limpio))) {
        const bubbleEl = msgNodoUsuario.querySelector('.bubble');
        if (bubbleEl) {
          const titSanit = (r.borrador && r.borrador.titulo) || r.titulo;
          const txtSanit = (r.borrador && r.borrador.texto_limpio) || r.texto_limpio;
          let textoOficial = null;
          if (cuerpo.texto && txtSanit) textoOficial = txtSanit;
          else if (cuerpo.titulo && titSanit) textoOficial = titSanit;
          if (textoOficial) {
            bubbleEl.innerHTML = esc(textoOficial) + '<div class="stamp">' + hora() + '</div>';
          }
        }
      }
      store.set({ enviando: false });

      if (r.aviso_privacidad) mostrarAviso(r.aviso_privacidad);

      const opcionesTurno = Array.isArray(r.opciones) ? r.opciones.slice() : [];
      if (r.estado === 'CONFORMIDAD_USUARIO' || r.estado === 'APROBADO' || (r.borrador && r.borrador.conforme)) {
        if (!opcionesTurno.includes('ver_articulo_final')) {
          opcionesTurno.unshift('ver_articulo_final');
        }
      }
      decir(nl2br(r.mensaje), opcionesTurno);

      if (r.estado === 'CONFORMIDAD_USUARIO' || r.estado === 'APROBADO') mostrarConforme();
    } catch (e) {
      esperando.remove();
      store.set({ enviando: false });
      ultimoFallo = { tipo: 'turno', payload: payload };
      mostrarError(e);
      decir('No pude completar el paso: ' + esc(e.message));
    }
  }

  function nombreCategoria(s, catId) {
    const idNum = Number(catId);
    if (!idNum || idNum <= 1) return 'Sin categoría';
    if (s && s.borrador && s.borrador.categoria_nombre && (!idNum || Number(s.borrador.categoria_id) === idNum)) {
      return s.borrador.categoria_nombre;
    }
    const lista = s.categorias_disponibles || [];
    const enc = lista.find((c) => Number(c.id) === idNum);
    return enc ? enc.nombre : ('Categoría ' + esc(catId));
  }

  /* =========================================================
     Render
     ========================================================= */
  function pintar(s) {
    const info = BACO.ESTADOS[s.flujo] || BACO.ESTADOS.ESPERANDO_TITULO;
    const etapaActual = (s.etapa && s.etapa.actual) || info.paso || 1;
    const etapaTotal = (s.etapa && s.etapa.total) || 5;

    const pill = $('#pillEstado');
    if (pill) {
      pill.textContent = info.etiqueta;
      pill.className = 'pill ' + info.tono;
    }
    const ayuda = $('#ayudaEstado');
    if (ayuda) ayuda.textContent = info.ayuda;

    const pct = BACO.avance(s);
    if ($('#meterFill')) {
      $('#meterFill').style.width = pct + '%';
      $('#meterFill').classList.toggle('full', s.flujo === 'CONFORMIDAD_USUARIO' || s.flujo === 'APROBADO');
    }
    if ($('#meterPct')) $('#meterPct').textContent = 'Etapa ' + etapaActual + ' de ' + etapaTotal;

    if ($('#sesion')) $('#sesion').textContent = s.session_id ? 'sesión ' + s.session_id.slice(0, 8) : '';

    pintarStepper(s, etapaActual);
    pintarTagsAcumuladosRail(s);

    const act = BACO.CAMPOS_ACTIVOS[s.flujo] || {};
    const fTit = $('#fTitulo');
    const fCue = $('#fCuerpo');
    const tInp = $('#tagInput');
    const tSel = $('#fTagsSelect');
    const fCat = $('#fCategoria');
    const txtDeshab = !act.texto || s.enviando || Boolean(estadoEditor.enviando);
    if (fTit) fTit.disabled = !act.titulo || s.enviando;
    if (fCue) fCue.disabled = txtDeshab;
    textareasMap.forEach((ta) => {
      ta.disabled = txtDeshab;
    });
    const contBloques = $('#contenedorBloques');
    if (contBloques) {
      contBloques.querySelectorAll('.bloque-textarea').forEach((ta) => {
        ta.disabled = txtDeshab;
      });
    }
    if (tInp) tInp.disabled = !act.tags || s.enviando;
    if (tSel) tSel.disabled = !act.tags || s.enviando;
    if (fCat) fCat.disabled = !act.categoria || s.enviando;
    if ($('#campoTitulo')) $('#campoTitulo').classList.toggle('activo', !!act.titulo);
    if ($('#campoTexto')) $('#campoTexto').classList.toggle('activo', !!act.texto);

    // Habilitar/deshabilitar herramientas de edición Markdown y emoji según si el texto es editable
    const toolsDeshab = !act.texto || s.enviando || estadoEditor.modo === 'preview';
    ['#btnMdBold', '#btnMdItalic', '#btnMdHeading', '#btnMdLink', '#btnMdQuote', '#btnMdCode', '#btnMdList', '#btnEmojiToolbar', '#btnSubir'].forEach((sel) => {
      const btnTool = $(sel);
      if (btnTool) btnTool.disabled = toolsDeshab;
    });

    // Disponibilidad del botón de imagen decidida exclusivamente por actualizarDisponibilidadRecursos
    actualizarDisponibilidadRecursos(s);

    const b = s.borrador;
    const esEnriquecerOActualizar = b && (b.modo === 'enriquecimiento' || b.modo === 'actualizar' || b.articulo_original_id != null);
    const tagsValidos = (s.form.tags || []).length >= cfg.MIN_TAGS;
    const catValida = Number(s.form.categoria_id) > 1;
    const etapaPostTexto = s.flujo !== 'ESPERANDO_TITULO' && s.flujo !== 'DECISION_TITULO' && s.flujo !== 'ESPERANDO_TEXTO' && s.flujo !== 'DECISION_TEXTO';

    let mostrarCampoTags = false;
    if (etapaPostTexto) {
      if (s.flujo === 'ESPERANDO_METADATOS') {
        mostrarCampoTags = true;
      } else if (esEnriquecerOActualizar) {
        mostrarCampoTags = !catValida || !tagsValidos;
      } else {
        mostrarCampoTags = true;
      }
    }

    const campoTags = $('#campoTags');
    if (campoTags) {
      campoTags.hidden = !mostrarCampoTags;
      campoTags.classList.toggle('activo', mostrarCampoTags && !!act.tags);
    }
    if ($('#tagBox')) $('#tagBox').classList.toggle('off', !act.tags);

    if (fTit && fTit.value !== s.form.titulo) {
      fTit.value = s.form.titulo;
    }
    if (fCue && fCue.value !== s.form.texto) {
      fCue.value = s.form.texto;
    }

    /* Contadores con code points (Array.from(s).length) */
    const lenTit = Array.from(s.form.titulo || '').length;
    const lenTxt = Array.from(s.form.texto || '').length;
    if ($('#contTitulo')) contador($('#contTitulo'), lenTit, cfg.MIN_TITULO, 'caracteres', cfg.MAX_TITULO);
    if ($('#contTexto')) contadorTexto($('#contTexto'), $('#avisoMaxTexto'), lenTxt, cfg.MIN_TEXTO, cfg.MAX_TEXTO_PERCENTIL_99);
    if ($('#contTags')) contador($('#contTags'), s.form.tags.length, cfg.MIN_TAGS, 'etiquetas', cfg.MAX_TAGS);

    const compMeta = $('#chatComposerMeta');
    const chatIn = $('#chatInput');
    if (compMeta) {
      compMeta.hidden = true;
    }
    if (chatIn) {
      chatIn.placeholder = 'Respondé acá o preguntale algo a BACO…';
    }

    /* Botón principal */
    const acc = BACO.ACCION_PRINCIPAL[s.flujo];
    const btn = $('#btnPrincipal');
    if (btn) {
      if (acc) {
        btn.hidden = false;
        btn.disabled = s.enviando || !listoParaEnviar(s, acc.campo);
        btn.textContent = (acc.campo === 'todo' && !hayCambios(s))
          ? 'Sin cambios para guardar'
          : acc.label;
        const textoCorto = Array.from((s.form.texto || '').trim()).length < cfg.MIN_TEXTO;
        const textoLargo = Array.from(s.form.texto || '').length > cfg.MAX_TEXTO_PERCENTIL_99;
        const tagsFaltan = (s.form.tags || []).length < cfg.MIN_TAGS;
        const catFalta = !s.form.categoria_id || Number(s.form.categoria_id) <= 1;
        btn.title = btn.disabled && acc.campo === 'todo'
          ? 'Editá algún campo para habilitar el guardado'
          : (btn.disabled && acc.campo === 'texto'
              ? (textoCorto
                  ? 'El texto debe tener al menos ' + cfg.MIN_TEXTO + ' caracteres'
                  : (textoLargo ? 'El texto supera el máximo de ' + cfg.MAX_TEXTO_PERCENTIL_99 + ' caracteres' : ''))
              : (btn.disabled && acc.campo === 'tags'
                  ? ((tagsFaltan ? 'Se requieren al menos ' + cfg.MIN_TAGS + ' etiquetas. ' : '') + (catFalta ? 'Debe seleccionarse una categoría del desplegable.' : ''))
                  : ''));
      } else {
        btn.hidden = true;
      }
    }

    sincronizarBloquesDesdeStore(s);

    pintarTags(s);
    pintarCategorias(s, !!act.categoria && !s.enviando);
    pintarResumenFinal(s);
    pintarBorrador(s);
    pintarAvisoMetadatosHeredados(s);
    pintarCoincidencias(s);
    pintarValidacion(s);
    pintarOpciones(s);
    pintarImagenesDetectadas(s);
    pintarEstadoSkills(s);

    const wrapper = $('#editorBloquesWrapper');
    const fc = $('#fCuerpo');
    const prev = $('#preview');
    if (estadoEditor.modo === 'preview') {
      if (wrapper) wrapper.hidden = true;
      if (fc) fc.hidden = true;
      if (prev) {
        prev.hidden = false;
        renderVistaPreviaEditable(s);
        conectarEventosVistaPrevia();
        if (false) prev.innerHTML = renderMd(textoVistaPrevia(s));
      }
    } else {
      if (wrapper) wrapper.hidden = false;
      if (fc) fc.hidden = true;
      if (prev) prev.hidden = true;
    }
  }

  function pintarEstadoSkills(s) {
    const b = s.borrador;
    const btnPl = $('#btnPlantilla');
    const btnAud = $('#btnAuditar');
    const railAviso = $('#avisoSkillsRail');
    const bannerSkills = $('#bannerSkills');

    const tieneRecursos = Boolean(
      b && (
        (Array.isArray(b.multimedia) && b.multimedia.length > 0) ||
        (b.recursos && Object.keys(b.recursos).length > 0)
      )
    ) || (Array.isArray(estadoEditor.recursos) && estadoEditor.recursos.length > 0);

    const deshabilitadas = Boolean((b && b.skills_habilitadas === false) || tieneRecursos);
    const motivoBase = (b && b.skills_motivo) ||
      (tieneRecursos
        ? 'El artículo contiene recursos multimedia cargados. Quitá los recursos si querés aplicar la plantilla o el validador automático.'
        : 'Las skills de asistencia del agente están deshabilitadas para este borrador.');
    const motivo = (tieneRecursos && !/quit[aá]/i.test(motivoBase))
      ? (motivoBase + ' Quitá los recursos cargados para poder aplicar las skills.')
      : motivoBase;

    if (btnPl) {
      btnPl.disabled = deshabilitadas;
      btnPl.classList.toggle('disabled', deshabilitadas);
      btnPl.title = deshabilitadas ? motivo : 'Aplica la plantilla seleccionada al borrador';
    }
    if (btnAud) {
      btnAud.disabled = deshabilitadas;
      btnAud.classList.toggle('disabled', deshabilitadas);
      btnAud.title = deshabilitadas ? motivo : 'Audita coherencia semántica y estilo con el validador';
    }

    if (railAviso) {
      railAviso.hidden = true;
      railAviso.innerHTML = '';
    }

    if (bannerSkills) {
      bannerSkills.hidden = true;
      bannerSkills.innerHTML = '';
    }
  }

  /* Vista previa reactiva que respeta el orden exacto (posicion, orden) intercalado con bloques_texto */
  function textoVistaPrevia(s) {
    const cuerpo = (s && s.form && typeof s.form.texto === 'string')
      ? s.form.texto
      : componerTextoDesdeBloques();
    const listaRecs = (estadoEditor.recursos && estadoEditor.recursos.length)
      ? estadoEditor.recursos
      : (window.BACO && window.BACO.panelMultimedia && window.BACO.panelMultimedia.lista ? window.BACO.panelMultimedia.lista(s) : []);
    const contexto = Object.assign({}, s || {}, {
      bloques_texto: (estadoEditor.bloques_texto && estadoEditor.bloques_texto.length)
        ? estadoEditor.bloques_texto
        : (s && s.borrador && s.borrador.bloques_texto)
    });
    if (window.BACO && window.BACO.panelMultimedia && typeof window.BACO.panelMultimedia.componerVistaPrevia === 'function') {
      return window.BACO.panelMultimedia.componerVistaPrevia(cuerpo, listaRecs, contexto);
    }
    return cuerpo;
  }

  /* Extrae texto en formato Markdown desde un elemento editable de la vista previa */
  function extraerMarkdownDeBloque(el) {
    if (!el) return '';
    const lineas = [];

    function extraerInline(nodo) {
      if (!nodo) return '';
      if (nodo.nodeType === 3) {
        return nodo.nodeValue || '';
      }
      if (nodo.nodeType === 1) {
        const tag = nodo.tagName.toLowerCase();
        if (tag === 'strong' || tag === 'b') {
          const t = Array.from(nodo.childNodes).map(extraerInline).join('');
          return t ? ('**' + t + '**') : '';
        }
        if (tag === 'em' || tag === 'i') {
          const t = Array.from(nodo.childNodes).map(extraerInline).join('');
          return t ? ('*' + t + '*') : '';
        }
        if (tag === 'code') {
          const t = Array.from(nodo.childNodes).map(extraerInline).join('');
          return t ? ('`' + t + '`') : '';
        }
        if (tag === 'a') {
          const href = nodo.getAttribute('href') || '';
          let t = Array.from(nodo.childNodes).map(extraerInline).join('');
          t = t.replace(/\s*↗\s*$/, '').trim();
          if (href && t) return '[' + t + '](' + href + ')';
          return t;
        }
        if (tag === 'br') {
          return '\n';
        }
        return Array.from(nodo.childNodes).map(extraerInline).join('');
      }
      return '';
    }

    Array.from(el.childNodes).forEach((child) => {
      if (child.nodeType === 3) {
        const txt = (child.nodeValue || '').trim();
        if (txt) lineas.push(txt);
        return;
      }
      if (child.nodeType === 1) {
        const tag = child.tagName.toLowerCase();
        if (tag === 'h1' || tag === 'h2' || tag === 'h3' || tag === 'h4') {
          const t = extraerInline(child).trim();
          if (t) lineas.push('#### ' + t);
          return;
        }
        if (tag === 'blockquote') {
          const t = extraerInline(child).trim();
          if (t) lineas.push('> ' + t);
          return;
        }
        if (tag === 'ol') {
          const lis = Array.from(child.children).filter((c) => c.tagName.toLowerCase() === 'li');
          lis.forEach((li, idx) => {
            const t = extraerInline(li).trim();
            if (t) lineas.push((idx + 1) + '. ' + t);
          });
          return;
        }
        if (tag === 'ul') {
          const lis = Array.from(child.children).filter((c) => c.tagName.toLowerCase() === 'li');
          lis.forEach((li) => {
            const t = extraerInline(li).trim();
            if (t) lineas.push('- ' + t);
          });
          return;
        }
        if (tag === 'p' || tag === 'div') {
          const t = extraerInline(child).trim();
          if (t) lineas.push(t);
          return;
        }
        const t = extraerInline(child).trim();
        if (t) lineas.push(t);
      }
    });

    return lineas.join('\n\n').trim();
  }

  /* Renderiza la vista previa interactiva/editable preservando formato y multimedia */
  function renderVistaPreviaEditable(s) {
    let pr = $('#preview');
    if (!pr && $('#campoTexto')) {
      pr = el('div', 'preview');
      pr.id = 'preview';
      $('#campoTexto').appendChild(pr);
    }
    if (!pr) return;

    if (document.activeElement && document.activeElement.closest && document.activeElement.closest('.preview-bloque-editable')) {
      return;
    }

    const st = s || store.get();
    const b = st && st.borrador;
    const esEnriquecer = Boolean(b && b.modo === 'enriquecimiento');

    const bloquesTxt = esEnriquecer
      ? (Array.isArray(estadoVistaPrevia.bloques_texto) && estadoVistaPrevia.bloques_texto.length
          ? estadoVistaPrevia.bloques_texto
          : (b && Array.isArray(b.bloques_texto) && b.bloques_texto.length ? b.bloques_texto : ['']))
      : (Array.isArray(estadoEditor.bloques_texto) && estadoEditor.bloques_texto.length
          ? estadoEditor.bloques_texto
          : [(st && st.form && st.form.texto) || '']);

    const recsOrd = ordenarRecursosPorPosicionYOrden(
      esEnriquecer
        ? (estadoVistaPrevia.recursos && estadoVistaPrevia.recursos.length
            ? estadoVistaPrevia.recursos
            : ((b && (Array.isArray(b.multimedia) ? b.multimedia : Object.values(b.recursos || {}))) || []))
        : ((estadoEditor.recursos && estadoEditor.recursos.length)
            ? estadoEditor.recursos
            : ((b && (Array.isArray(b.multimedia) ? b.multimedia : Object.values(b.recursos || {}))) || []))
    );

    const fnMd = (window.BACO && window.BACO.panelMultimedia && window.BACO.panelMultimedia.aMarkdown) || function(r) {
      const n = r.nombre || '';
      const ref = r.referencia || r.url || '';
      if (r.tipo === 'imagen') return '![' + n + '](' + ref + ')';
      if (r.tipo === 'documento' && (/\/uploads\//.test(ref) || /\/api\/recursos-temp\//.test(ref) || /\.(pdf|zip|docx)$/i.test(ref))) {
        return '[' + n + '|attachment](' + ref + ')';
      }
      return '[' + n + '](' + ref + ')';
    };

    const frag = document.createDocumentFragment();

    function crearMediaElement(r) {
      const mediaEl = document.createElement('div');
      mediaEl.className = 'preview-media-container';
      mediaEl.setAttribute('contenteditable', 'false');

      const btnQuitar = document.createElement('button');
      btnQuitar.type = 'button';
      btnQuitar.className = 'preview-media-quitar';
      btnQuitar.setAttribute('data-id', r.id);
      btnQuitar.setAttribute('data-accion', 'quitar-recurso-preview');
      btnQuitar.setAttribute('aria-label', 'Eliminar ' + (r.nombre || r.referencia || r.id));
      btnQuitar.title = 'Eliminar recurso';
      btnQuitar.textContent = '×';
      mediaEl.appendChild(btnQuitar);

      const contentEl = document.createElement('div');
      contentEl.className = 'preview-media-content';
      contentEl.innerHTML = renderMd(fnMd(r));
      mediaEl.appendChild(contentEl);

      return mediaEl;
    }

    recsOrd.filter((r) => r.posicion === -1).forEach((r) => {
      frag.appendChild(crearMediaElement(r));
    });

    for (let i = 0; i < bloquesTxt.length; i++) {
      const bDiv = document.createElement('div');
      bDiv.className = 'preview-bloque-editable';
      bDiv.setAttribute('contenteditable', 'true');
      bDiv.setAttribute('data-bloque-idx', String(i));
      bDiv.setAttribute('spellcheck', 'true');
      bDiv.setAttribute('data-placeholder', i === 0 ? 'Escribí el texto acá en formato Markdown...' : 'Continuá escribiendo...');

      const txt = String(bloquesTxt[i] == null ? '' : bloquesTxt[i]).trim();
      if (txt) {
        bDiv.innerHTML = renderMd(txt);
      } else {
        bDiv.innerHTML = '<p><br></p>';
      }
      frag.appendChild(bDiv);

      recsOrd
        .filter((r) => (typeof r.posicion === 'number' ? r.posicion : 0) === i)
        .forEach((r) => {
          frag.appendChild(crearMediaElement(r));
        });
    }

    recsOrd
      .filter((r) => typeof r.posicion === 'number' && r.posicion >= bloquesTxt.length)
      .forEach((r) => {
        frag.appendChild(crearMediaElement(r));
      });

    pr.replaceChildren(frag);
  }

  function esVistaPreviaActiva() {
    const pr = $('#preview');
    if (pr && !pr.hidden) return true;
    if (estadoEditor && estadoEditor.modo === 'preview') return true;
    const btnPr = $('#btnPreview');
    return Boolean(btnPr && btnPr.classList.contains('sel'));
  }
  BACO.esVistaPreviaActiva = esVistaPreviaActiva;

  function conectarEventosVistaPrevia() {
    const pr = $('#preview');
    if (!pr || pr._eventosConectados) return;
    pr._eventosConectados = true;

    pr.addEventListener('mousedown', (e) => {
      const btn = e.target.closest('.preview-media-quitar');
      if (btn) {
        e.preventDefault(); // no perder la selección dentro del contenteditable
      }
    });

    pr.addEventListener('click', async (e) => {
      const btn = e.target.closest('.preview-media-quitar');
      if (!btn || btn.disabled) return;
      const recId = btn.getAttribute('data-id');
      if (!recId) return;

      e.preventDefault();
      e.stopPropagation();

      btn.disabled = true;
      try {
        const res = await api.eliminarRecurso(recId);
        aplicarEstadoRecursosServidor(res);
        toast('Recurso eliminado');
      } catch (err) {
        btn.disabled = false;
        toast('Error al eliminar recurso: ' + (err.message || 'Error'));
      }
    });

    pr.addEventListener('input', (e) => {
      const bDiv = e.target.closest('.preview-bloque-editable');
      if (!bDiv) return;
      const idx = parseInt(bDiv.getAttribute('data-bloque-idx'), 10);
      if (isNaN(idx) || idx < 0) return;

      const nuevoMd = extraerMarkdownDeBloque(bDiv);
      const st = store.get();
      const esEnriquecer = Boolean(st && st.borrador && st.borrador.modo === 'enriquecimiento');

      if (esEnriquecer) {
        if (!Array.isArray(estadoVistaPrevia.bloques_texto) || !estadoVistaPrevia.bloques_texto.length) {
          estadoVistaPrevia.bloques_texto = (st.borrador && Array.isArray(st.borrador.bloques_texto))
            ? st.borrador.bloques_texto.slice()
            : [''];
        }
        if (idx < estadoVistaPrevia.bloques_texto.length) {
          estadoVistaPrevia.bloques_texto[idx] = nuevoMd;
        }
        if (st && st.borrador) {
          st.borrador.bloques_texto = estadoVistaPrevia.bloques_texto.slice();
          st.borrador.texto_limpio = estadoVistaPrevia.bloques_texto.join('\n\n').trim();
        }
        store.setForm({ texto: st.borrador ? st.borrador.texto_limpio : '' });
      } else {
        if (idx < estadoEditor.bloques_texto.length) {
          estadoEditor.bloques_texto[idx] = nuevoMd;
        }
        const blk = estadoEditor.bloques.find((x) => x.tipo === 'texto' && x.bloqueIdx === idx);
        if (blk) blk.contenido = nuevoMd;

        const ta = textareasMap.get('txt_block_' + idx);
        if (ta && ta.value !== nuevoMd) {
          ta.value = nuevoMd;
        }
        sincronizarTextoConStore();
      }
    });

    pr.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        if ($('#btnPrincipal') && !$('#btnPrincipal').disabled) enviarPrincipal();
      }
    });
  }

  function sincronizarTextoDesdePreview() {
    const pr = $('#preview');
    if (!pr || pr.hidden) return;
    const bloquesEditables = pr.querySelectorAll('.preview-bloque-editable');
    if (!bloquesEditables.length) return;

    const st = store.get();
    const esEnriquecer = Boolean(st && st.borrador && st.borrador.modo === 'enriquecimiento');

    if (esEnriquecer) {
      if (!Array.isArray(estadoVistaPrevia.bloques_texto) || !estadoVistaPrevia.bloques_texto.length) {
        estadoVistaPrevia.bloques_texto = (st.borrador && Array.isArray(st.borrador.bloques_texto))
          ? st.borrador.bloques_texto.slice()
          : [''];
      }
      bloquesEditables.forEach((bDiv) => {
        const idx = parseInt(bDiv.getAttribute('data-bloque-idx'), 10);
        if (isNaN(idx) || idx < 0) return;
        const nuevoMd = extraerMarkdownDeBloque(bDiv);
        if (idx < estadoVistaPrevia.bloques_texto.length) {
          estadoVistaPrevia.bloques_texto[idx] = nuevoMd;
        }
      });
      if (st && st.borrador) {
        st.borrador.bloques_texto = estadoVistaPrevia.bloques_texto.slice();
        st.borrador.texto_limpio = estadoVistaPrevia.bloques_texto.join('\n\n').trim();
      }
      store.setForm({ texto: st.borrador ? st.borrador.texto_limpio : '' });
    } else {
      bloquesEditables.forEach((bDiv) => {
        const idx = parseInt(bDiv.getAttribute('data-bloque-idx'), 10);
        if (isNaN(idx) || idx < 0) return;
        const nuevoMd = extraerMarkdownDeBloque(bDiv);
        if (idx < estadoEditor.bloques_texto.length) {
          estadoEditor.bloques_texto[idx] = nuevoMd;
        }
        const b = estadoEditor.bloques.find((x) => x.tipo === 'texto' && x.bloqueIdx === idx);
        if (b) b.contenido = nuevoMd;
        const ta = textareasMap.get('txt_block_' + idx);
        if (ta && ta.value !== nuevoMd) {
          ta.value = nuevoMd;
        }
      });
      sincronizarTextoConStore();
    }
  }

  BACO.sincronizarTextoDesdePreview = sincronizarTextoDesdePreview;

  function pintarStepper(s, etapaActual) {
    const cont = $('#pasos');
    if (!cont) return;
    const nombres = (s.etapa && Array.isArray(s.etapa.etapas) && s.etapa.etapas.length)
      ? s.etapa.etapas
      : ['Título y duplicados', 'Contenido', 'Plantilla y etiquetas', 'Revisión', 'Conformidad'];

    if (cont.children.length !== nombres.length) {
      cont.innerHTML = '';
      nombres.forEach((nom, idx) => {
        cont.appendChild(el('div', 'paso', '<span class="pn">' + (idx + 1) + '</span> ' + esc(nom)));
      });
    }

    Array.prototype.forEach.call(cont.querySelectorAll('.paso'), (nodo, i) => {
      const n = i + 1;
      const completado = (s.flujo === 'CONFORMIDAD_USUARIO' || s.flujo === 'APROBADO') ? true : (n < etapaActual);
      const activo = (s.flujo !== 'CONFORMIDAD_USUARIO' && s.flujo !== 'APROBADO') && (n === etapaActual);
      nodo.classList.toggle('on', activo);
      nodo.classList.toggle('hecho', completado);
    });
  }

  function pintarTagsAcumuladosRail(s) {
    const rail = $('#railTags');
    if (!rail) return;
    const lista = (s.tags_acumulados && s.tags_acumulados.length)
      ? s.tags_acumulados
      : (s.form.tags || []);
    if (!lista.length) {
      rail.innerHTML = '<span class="vacio-rail">Sin etiquetas aún</span>';
      return;
    }
    const plantilla = s.borrador && s.borrador.tipo_plantilla;
    rail.innerHTML = lista.map((t) => {
      const esTipo = (t === plantilla || t === 'instructivo' || t === 'soluciones');
      return '<span class="railtag' + (esTipo ? ' tipo' : '') + '">' + esc(t) + '</span>';
    }).join('');
  }

  function pintarCategorias(s, habilitado) {
    const sel = $('#fCategoria');
    const chipsRow = $('#catChipsRow');
    if (!sel || !chipsRow) return;

    const cats = (s.categorias_disponibles && s.categorias_disponibles.length)
      ? s.categorias_disponibles
      : [];

    const actualId = (s.form.categoria_id && Number(s.form.categoria_id) > 1) ? Number(s.form.categoria_id) : null;

    let selHtml = '';
    if (!actualId) {
      selHtml += '<option value="" selected disabled>Seleccionar categoría del desplegable...</option>';
    }

    const catsOrdenadas = [...cats].sort((a, b) =>
      (a.nombre || '').localeCompare(b.nombre || '', 'es', { sensitivity: 'base' })
    );

    const catsFiltradas = catsOrdenadas.filter((c) => {
      if (!c.nombre) return false;
      return !/^categor[íi]a\s+\d+$/i.test(c.nombre.trim());
    });

    catsFiltradas.forEach((c) => {
      const selected = actualId && Number(c.id) === actualId;
      selHtml += '<option value="' + esc(c.id) + '"' + (selected ? ' selected' : '') + '>' + esc(c.nombre) + '</option>';
    });
    sel.innerHTML = selHtml;
    sel.value = actualId ? String(actualId) : '';
    sel.disabled = !habilitado;
    actualizarColorCategoria(sel);
    const btnFlechaCat = $('#btnFlechaCat');
    if (btnFlechaCat) btnFlechaCat.disabled = !habilitado;

    chipsRow.innerHTML = '';
    if (!catsFiltradas.length) return;

    const IDS_CHIPS_FRECUENTES = new Set([
      20, 21, 24, 22, 23, 19, 37, 39, 25, 26, 28, 29, 33, 40, 48, 62, 63, 65, 81, 82, 83
    ]);
    const catsChips = catsFiltradas.length > 25
      ? catsFiltradas.filter((c) => IDS_CHIPS_FRECUENTES.has(Number(c.id)))
      : catsFiltradas;

    if (catsChips.length) {
      chipsRow.appendChild(el('span', 'cap', 'Sugeridas'));
      catsChips.forEach((c) => {
        const activo = actualId && Number(c.id) === actualId;
        const chip = el('button', 'sugg cat-chip' + (activo ? ' on' : ''), esc(c.nombre));
        chip.type = 'button';
        chip.disabled = !habilitado;
        chip.onclick = () => {
          store.setForm({ categoria_id: Number(c.id) });
        };
        chipsRow.appendChild(chip);
      });
    }
  }

  function actualizarColorCategoria(sel) {
    if (!sel) return;

    // Limpiar primero todo color previo (data-modulo, clases y estilos)
    if (sel.dataset) delete sel.dataset.modulo;
    if (typeof sel.removeAttribute === 'function') sel.removeAttribute('data-modulo');
    const wrap = sel.closest ? sel.closest('.selector-cat-wrap') : (sel.parentElement || null);
    if (wrap) {
      if (wrap.dataset) delete wrap.dataset.modulo;
      if (typeof wrap.removeAttribute === 'function') wrap.removeAttribute('data-modulo');
    }

    if (!sel.value || sel.selectedIndex < 0) return;

    const opt = sel.options ? sel.options[sel.selectedIndex] : null;
    const texto = (opt && opt.value)
      ? (opt.text || '').trim().normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
      : '';
    const MAPA_MODULOS = {
      'agro': 'agro',
      'erp': 'erp',
      'gestion comercial': 'gestion-comercial',
      'comercializadoras': 'gestion-comercial',
      'constructoras': 'constructoras',
      'hcm': 'hcm',
      'manufacturas': 'manufacturas'
    };
    const mod = MAPA_MODULOS[texto] || null;
    if (mod) {
      if (sel.dataset) sel.dataset.modulo = mod;
      if (typeof sel.setAttribute === 'function') sel.setAttribute('data-modulo', mod);
      if (wrap) {
        if (wrap.dataset) wrap.dataset.modulo = mod;
        if (typeof wrap.setAttribute === 'function') wrap.setAttribute('data-modulo', mod);
      }
    }
  }

  function pintarAvisoMetadatosHeredados(s) {
    const bannerMeta = $('#bannerMetadatosHeredados');
    if (!bannerMeta) return;
    const b = s.borrador;
    const metaAnt = b && b.metadatos_anteriores;
    const etapaPostTexto = s.flujo !== 'ESPERANDO_TITULO' && s.flujo !== 'DECISION_TITULO' && s.flujo !== 'ESPERANDO_TEXTO' && s.flujo !== 'DECISION_TEXTO';
    const pendiente = (etapaPostTexto || !!s.aviso_metadatos_heredados) && metaAnt && !b.metadatos_heredados_revisados;

    if (pendiente) {
      if (bannerMeta.querySelector('.banner-meta-ant') && bannerMeta.querySelector('#btnAcepMetaHeredados')) {
        return;
      }
      const nomCat = metaAnt.categoria_nombre || nombreCategoria(s, metaAnt.categoria_id);
      const tagsStr = (metaAnt.tags || []).join(', ') || 'sin etiquetas';
      bannerMeta.innerHTML =
        '<div class="banner aviso banner-meta-ant" style="display:flex; align-items:flex-start; gap:10px; margin-bottom:12px;">' +
          '<svg width="18" height="18" viewBox="0 0 16 16" fill="none" style="flex-shrink:0; margin-top:2px;"><circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.3"/><path d="M8 4.5v4M8 11.5h.01" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>' +
          '<div style="flex:1">' +
            '<div><b>Metadatos heredados de la versión anterior (#' + esc(b.articulo_original_id) + '):</b></div>' +
            '<div style="margin:4px 0 8px 0; font-size:12.5px;">Categoría: <b>' + esc(nomCat) + '</b> · Etiquetas: <b>' + esc(tagsStr) + '</b></div>' +
            '<div style="display:flex; gap:8px;">' +
              '<button type="button" class="btn btn-sm btn-primary" id="btnAcepMetaHeredados">Aceptar</button>' +
              '<button type="button" class="btn btn-sm btn-secondary" id="btnRechMetaHeredados">Rechazar</button>' +
            '</div>' +
          '</div>' +
        '</div>';

      const btnAcep = $('#btnAcepMetaHeredados');
      if (btnAcep) {
        btnAcep.onclick = () => {
          const sAct = store.get();
          const payload = { accion: 'aceptar_metadatos' };
          if (hayCambios(sAct) && sAct.form && sAct.form.texto) {
            payload.texto = sAct.form.texto;
          }
          enviarTurno(payload, 'Aceptar metadatos heredados');
        };
      }
      const btnRech = $('#btnRechMetaHeredados');
      if (btnRech) {
        btnRech.onclick = () => {
          const sAct = store.get();
          const payload = { accion: 'rechazar_metadatos' };
          if (hayCambios(sAct) && sAct.form && sAct.form.texto) {
            payload.texto = sAct.form.texto;
          }
          store.setForm({ categoria_id: null, tags: [] });
          enviarTurno(payload, 'Rechazar metadatos heredados');
        };
      }
    } else {
      bannerMeta.innerHTML = '';
    }
  }

  function pintarResumenFinal(s) {
    const slot = $('#slotResumenFinal');
    if (!slot) return;
    if ((s.flujo !== 'CONFORMIDAD_USUARIO' && s.flujo !== 'APROBADO') || !s.borrador) {
      slot.innerHTML = '';
      return;
    }
    const b = s.borrador;
    const tags = (s.tags_acumulados && s.tags_acumulados.length) ? s.tags_acumulados : (b.tags || []);
    const etapaTxt = (s.etapa ? (s.etapa.actual + ' de ' + s.etapa.total + ' (' + s.etapa.nombre + ')') : '5 de 5 (Conformidad)');
    slot.innerHTML =
      '<div class="resumen-final">' +
        '<h3><svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3.8 8.2l2.6 2.6 5.4-5.6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>' +
        'Resumen final de la carga</h3>' +
        '<div class="rf-grid">' +
          '<div><span class="rf-k">Progreso</span><span class="rf-v">Etapa ' + esc(etapaTxt) + '</span></div>' +
          '<div><span class="rf-k">Modo</span><span class="rf-v">' + esc(b.modo) + '</span></div>' +
          '<div><span class="rf-k">Plantilla</span><span class="rf-v">' + esc(b.tipo_plantilla || '—') + '</span></div>' +
          '<div><span class="rf-k">Categoría</span><span class="rf-v">' + esc(nombreCategoria(s, b.categoria_id)) + '</span></div>' +
          '<div><span class="rf-k">Tags acumulados</span><span class="rf-v">' + (tags.map(esc).join(' · ') || '—') + '</span></div>' +
        '</div>' +
      '</div>';
  }

  function contador(nodo, actual, minimo, unidad, maximo) {
    if (actual === 0) {
      nodo.textContent = minimo + ' ' + unidad + ' mín.';
      nodo.className = 'cont';
      return;
    }
    if (actual < minimo) {
      nodo.textContent = actual + ' / ' + minimo + ' mín.';
      nodo.className = 'cont falta';
      return;
    }
    if (maximo && actual > maximo) {
      nodo.textContent = actual + ' / ' + maximo + ' máx.';
      nodo.className = 'cont falta';
      return;
    }
    nodo.textContent = actual + (maximo && actual > maximo * 0.9 ? ' / ' + maximo : '');
    nodo.className = 'cont ok';
  }

  function contadorTexto(nodo, nodoAviso, actual, minimo, maximo) {
    const max = maximo || cfg.MAX_TEXTO_PERCENTIL_99 || 16777;
    const min = minimo || cfg.MIN_TEXTO || 20;
    if (nodo) {
      nodo.textContent = actual + ' caracteres';
      if (actual > max) {
        nodo.className = 'cont exceso';
      } else if (actual > 0 && actual < min) {
        nodo.className = 'cont falta';
      } else if (actual >= min) {
        nodo.className = 'cont ok';
      } else {
        nodo.className = 'cont';
      }
    }
    if (nodoAviso) {
      if (actual > max) {
        const sobran = actual - max;
        nodoAviso.hidden = false;
        nodoAviso.textContent = 'El texto supera el límite máximo permitido de ' + max + ' caracteres (excede por ' + sobran + '). Acortalo o dividilo para poder confirmar.';
      } else {
        nodoAviso.hidden = true;
        nodoAviso.textContent = '';
      }
    }
  }

  function listoParaEnviar(s, campo) {
    const lenTitTrim = Array.from((s.form.titulo || '').trim()).length;
    const lenTxtTrim = Array.from((s.form.texto || '').trim()).length;
    const lenTxt = Array.from(s.form.texto || '').length;
    if (campo === 'titulo') return lenTitTrim >= cfg.MIN_TITULO;
    if (campo === 'texto')  return lenTxtTrim >= cfg.MIN_TEXTO && lenTxt <= cfg.MAX_TEXTO_PERCENTIL_99;
    if (campo === 'tags')   return s.form.tags.length >= cfg.MIN_TAGS && Number(s.form.categoria_id) > 1;
    if (campo === 'todo')   return hayCambios(s) && lenTxt <= cfg.MAX_TEXTO_PERCENTIL_99;
    return true;
  }

  function hayCambios(s) {
    const b = s.borrador;
    if (!b) return true;
    const mismosTags = (b.tags || []).length === s.form.tags.length &&
      (b.tags || []).every((t, i) => t === s.form.tags[i]);
    return s.form.titulo !== b.titulo ||
           s.form.texto !== (b.texto_limpio || '') ||   // el editor solo tiene texto_limpio
           Number(s.form.categoria_id) !== Number(b.categoria_id) ||
           !mismosTags;
  }

  /* ---------------- etiquetas ---------------- */
  function pintarTags(s) {
    const box = $('#tagBox'), input = $('#tagInput');
    if (!box || !input) return;
    box.querySelectorAll('.tag').forEach((n) => n.remove());
    const plantilla = s.borrador && s.borrador.tipo_plantilla;

    s.form.tags.forEach((t) => {
      const esTipo = (t === plantilla);
      const chip = el('span', 'tag' + (esTipo ? ' tipo' : ''), esc(t));
      if (!input.disabled) {
        const x = el('button', 'x', '<svg width="9" height="9" viewBox="0 0 10 10"><path d="M1 1l8 8M9 1l-8 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>');
        x.onclick = () => { store.setForm({ tags: s.form.tags.filter((v) => v !== t) }); };
        chip.appendChild(x);
      }
      box.insertBefore(chip, input);
    });

    const selTags = $('#fTagsSelect');
    if (selTags) {
      const tagsDisp = (s.tags_disponibles && s.tags_disponibles.length)
        ? s.tags_disponibles
        : ((BACO.datos && BACO.datos.etiquetas) ? BACO.datos.etiquetas.map((e) => e.tag) : []);

      const tagsOrdenados = [...new Set(tagsDisp)]
        .filter((t) => t && typeof t === 'string' && t.trim() && s.form.tags.indexOf(t) === -1)
        .sort((a, b) => a.localeCompare(b, 'es', { sensitivity: 'base' }));

      const hayTags = (s.form.tags || []).length > 0;
      let selHtml = hayTags
        ? '<option value="" selected disabled style="display:none;"></option>'
        : '<option value="" selected disabled>selecciona al menos 2 etiquetas…</option>';
      tagsOrdenados.forEach((t) => {
        selHtml += '<option value="' + esc(t) + '">' + esc(t) + '</option>';
      });
      selTags.innerHTML = selHtml;
      selTags.value = '';
      selTags.disabled = input.disabled;
      const btnFlechaTags = $('#btnFlechaTags');
      if (btnFlechaTags) btnFlechaTags.disabled = !!input.disabled;
    }

    const row = $('#suggRow');
    if (!row) return;
    row.innerHTML = '';
    if (input.disabled) return;

    let cands = [];
    if (s.tags_disponibles && s.tags_disponibles.length) {
      cands = s.tags_disponibles
        .filter((t) => t !== 'instructivo' && t !== 'soluciones' && s.form.tags.indexOf(t) === -1)
        .slice(0, 8);
    } else if (BACO.datos && BACO.datos.etiquetas) {
      cands = BACO.datos.etiquetas
        .filter((e) => !e.es_tipo_documentacion && s.form.tags.indexOf(e.tag) === -1)
        .sort((a, b) => b.usos - a.usos)
        .slice(0, 5)
        .map((e) => e.tag);
    }

    if (!cands.length) return;
    row.appendChild(el('span', 'cap', 'Sugeridas'));
    cands.forEach((tagStr) => {
      const b = el('button', 'sugg', '+ ' + esc(tagStr));
      b.type = 'button';
      b.onclick = () => {
        if (s.form.tags.length >= cfg.MAX_TAGS) { toast('Máximo ' + cfg.MAX_TAGS + ' etiquetas'); return; }
        store.setForm({ tags: s.form.tags.concat([tagStr]) });
      };
      row.appendChild(b);
    });
  }

  /* ---------------- cabecera del borrador ---------------- */
  function pintarBorrador(s) {
    const slot = $('#slotBorrador');
    if (!slot) return;
    if (!s.borrador) { slot.innerHTML = ''; return; }
    const b = s.borrador;
    const enriq = b.modo === 'enriquecimiento';
    slot.innerHTML =
      '<div class="borrador ' + (enriq ? 'enriq' : 'nuevo') + '">' +
        '<span class="bmodo">' + (enriq ? 'Enriqueciendo' : 'Entrada nueva') + '</span>' +
        (enriq
          ? '<span class="bdet">sobre <a href="' + esc(b.articulo_original_url) + '" target="_blank" rel="noopener">#' + b.articulo_original_id + '</a></span>'
          : '<span class="bdet">sin artículo de origen</span>') +
        (b.tipo_plantilla ? '<span class="bchip">' + esc(b.tipo_plantilla) + '</span>' : '') +
        '<span class="bdet">' + esc(nombreCategoria(s, b.categoria_id)) + '</span>' +
      '</div>';
  }

  /* ---------------- coincidencias ---------------- */
  function pintarCoincidencias() {
    const slot = $('#slotCoincidencias');
    if (slot) slot.innerHTML = '';
  }

  /* ---------------- validación ---------------- */
  function pintarValidacion(s) {
    const slot = $('#slotValidacion');
    if (!slot) return;
    const flujosConValidacion = ['REVISION_BORRADOR', 'SUBSANANDO_BORRADOR', 'CONFORMIDAD_USUARIO', 'APROBADO'];
    if (!s || !flujosConValidacion.includes(s.flujo)) {
      slot.innerHTML = '';
      return;
    }
    const v = s.validacion;
    if (!v) { slot.innerHTML = ''; return; }

    const cuenta = { Bloqueante: 0, Ajuste: 0, Sugerencia: 0 };
    (v.findings || []).forEach((f) => {
      const sev = f.severity === 'Requiere ajuste' ? 'Ajuste' : f.severity;
      if (cuenta[sev] != null) cuenta[sev]++;
    });

    let h = '<div class="card"><div class="tally3">' +
      '<div><div class="n ' + (cuenta.Bloqueante ? 'stop' : 'ok') + '">' + cuenta.Bloqueante + '</div><div class="l">Bloqueantes</div></div>' +
      '<div><div class="n ' + (cuenta.Ajuste ? 'warn' : 'ok') + '">' + cuenta.Ajuste + '</div><div class="l">Ajustes</div></div>' +
      '<div><div class="n ok">' + cuenta.Sugerencia + '</div><div class="l">Sugerencias</div></div>' +
      '</div><div class="resumen"><b>' + esc(v.status) + '</b> · ' +
      v.resumen.longitud_texto + ' caracteres · ' + v.resumen.tags_count + ' etiquetas</div>';

    const ics = {
      stop: '<svg width="15" height="15" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6.4" stroke="currentColor" stroke-width="1.4"/><path d="M8 4.8v3.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="8" cy="11.2" r=".9" fill="currentColor"/></svg>',
      warn: '<svg width="15" height="15" viewBox="0 0 16 16" fill="none"><path d="M8 2.4l6 11H2l6-11z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M8 6.8v2.6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="8" cy="11.3" r=".8" fill="currentColor"/></svg>',
      info: '<svg width="15" height="15" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6.4" stroke="currentColor" stroke-width="1.4"/><path d="M8 7.4v3.8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="8" cy="5" r=".9" fill="currentColor"/></svg>',
      ok:   '<svg width="15" height="15" viewBox="0 0 16 16" fill="none"><path d="M3.8 8.2l2.6 2.6 5.4-5.6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    };

    if (v.findings && v.findings.length) {
      const orden = v.findings.slice().sort((a, b) =>
        ((BACO.SEVERIDAD[a.severity] || {}).orden || 9) - ((BACO.SEVERIDAD[b.severity] || {}).orden || 9));
      h += '<div class="checks">';
      orden.forEach((f) => {
        const cl = (BACO.SEVERIDAD[f.severity] || { clase: 'info' }).clase;
        const irA = { texto: 'fCuerpo', titulo: 'fTitulo', tags: 'tagInput', categoria_id: 'fCategoria' }[f.field];
        h += '<div class="check ' + cl + (irA ? ' clickable' : '') + '"' +
          (irA ? ' data-ir="' + irA + '" title="Ir al campo"' : '') + '>' +
          '<span class="ic">' + ics[cl] + '</span>' +
          '<b>' + esc(f.description) + '<span class="lv">' + esc(f.severity) + '</span></b>' +
          (f.action ? '<p>' + esc(f.action) + (irA ? '<span class="ir">Ir al campo →</span>' : '') + '</p>' : '') +
          '</div>';
      });
      h += '</div>';
    } else {
      h += '<div class="checks"><div class="check ok"><span class="ic">' + ics.ok + '</span>' +
        '<b>Sin observaciones del validador</b></div></div>';
    }
    slot.innerHTML = h + '</div>';

    slot.querySelectorAll('.check.clickable').forEach((nodo) => {
      nodo.onclick = () => {
        let campo = $('#' + nodo.dataset.ir);
        if ((!campo || campo.hidden) && nodo.dataset.ir === 'fCuerpo') {
          campo = $('.bloque-textarea') || $('#contenedorBloques') || $('#campoTexto');
        }
        if (!campo || campo.disabled) return;
        campo.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setTimeout(() => {
          if (typeof campo.focus === 'function') campo.focus();
          const cont = campo.closest('.field');
          if (cont) {
            cont.classList.add('senalado');
            setTimeout(() => cont.classList.remove('senalado'), 1600);
          }
        }, 300);
      };
    });
  }

  /* ---------------- opciones del backend ---------------- */
  function pintarOpciones(s) {
    const barra = $('#opcionesBarra');
    if (!barra) return;
    barra.innerHTML = '';
    if (!s.opciones.length) return;
    const tieneMetaPendiente = s.flujo === 'REVISION_BORRADOR' && !!(s.aviso_metadatos_heredados || (s.borrador && s.borrador.metadatos_anteriores && !s.borrador.metadatos_heredados_revisados));
    const cartelConBotones = Boolean(
      $('#bannerMetadatosHeredados') &&
      $('#bannerMetadatosHeredados').querySelector('#btnAcepMetaHeredados')
    );
    if (tieneMetaPendiente && cartelConBotones) return;
    s.opciones.forEach((op) => {
      if (op === 'confirmar_texto' && BACO.ACCION_PRINCIPAL[s.flujo] && BACO.ACCION_PRINCIPAL[s.flujo].campo === 'texto') {
        return;
      }
      const def = BACO.OPCIONES[op] || { label: op, estilo: 'btn-ghost' };
      const b = el('button', 'btn btn-sm ' + def.estilo, esc(def.label));
      b.disabled = s.enviando;
      b.onclick = () => accionar(op, def.label);
      barra.appendChild(b);
    });
  }

  /* =========================================================
     Acciones
     ========================================================= */
  function accionar(op, label) {
    const s = store.get();

    if (op === 'ver_articulo_final') {
      const sid = s.session_id || (api.sesionActual ? api.sesionActual() : '');
      const targetUrl = sid ? ('articulo.html?session_id=' + encodeURIComponent(sid)) : 'articulo.html';
      window.open(targetUrl, '_blank');
      return;
    }

    if (op === 'copiar_borrador') {
      copiarBorrador();
      return;
    }

    if (op === 'confirmar_texto') {
      return confirmarTexto();
    }

    if (op === 'editar' && s.flujo === 'REVISION_BORRADOR') {
      sincronizarTextoDesdePreview();
      sincronizarTextoConStore();
      return enviarTurno({ accion: 'editar' }, label);
    }
    if (op === 'reiniciar') {
      consultandoDocExistentePorTitulo = false;
      descartoDocExistentePorTitulo = false;
      tituloOriginalIngresado = '';
      consultandoDocExistentePorTexto = false;
      descartoDocExistentePorTexto = false;
      textoOriginalIngresado = '';
      bloquesOriginalesIngresados = [''];
      store.reiniciarLocal();
      if (api.olvidarSesion) api.olvidarSesion();
      $('#thread').innerHTML = '';
      $('#bannerError').innerHTML = '';
      if ($('#bannerPrivacidad')) $('#bannerPrivacidad').innerHTML = '';
      if ($('#bannerMetadatosHeredados')) $('#bannerMetadatosHeredados').innerHTML = '';
      const chatIn = $('#chatInput');
      if (chatIn) { chatIn.value = ''; chatIn.style.height = 'auto'; }
      reconstruirBloques([''], [], null);
      renderBloques();
      return enviarTurno({ accion: 'reiniciar' });
    }
    if (op === 'enriquecer' || op === 'actualizar') {
      if (s.flujo === 'DECISION_TITULO') {
        consultandoDocExistentePorTitulo = true;
        tituloOriginalIngresado = (s.form && s.form.titulo) || tituloOriginalIngresado || '';
      }
      sincronizarTextoDesdePreview();
      sincronizarTextoConStore();
      const sAct = store.get();
      if (s.flujo === 'DECISION_TEXTO') {
        consultandoDocExistentePorTexto = true;
        const textoCapturado = (sAct.form && typeof sAct.form.texto === 'string' && sAct.form.texto.trim())
          ? sAct.form.texto
          : (componerTextoDesdeBloques().trim() || textoOriginalIngresado || '');
        if (textoCapturado) {
          textoOriginalIngresado = textoCapturado;
        }
        if (estadoEditor.bloques_texto && estadoEditor.bloques_texto.length) {
          bloquesOriginalesIngresados = estadoEditor.bloques_texto.slice();
        } else if (textoCapturado) {
          bloquesOriginalesIngresados = [textoCapturado];
        }
      }
      const payload = { accion: op };
      const txt = (sAct.form && typeof sAct.form.texto === 'string' ? sAct.form.texto : '').trim() ||
                  componerTextoDesdeBloques().trim();
      if (txt) {
        payload.texto = txt;
      }
      return enviarTurno(payload, label);
    }
    if (op === 'descartar' && (consultandoDocExistentePorTitulo || consultandoDocExistentePorTexto) && s.flujo === 'ESPERANDO_TEXTO') {
      const eraPorTexto = consultandoDocExistentePorTexto;
      consultandoDocExistentePorTitulo = false;
      consultandoDocExistentePorTexto = false;
      if (eraPorTexto) {
        descartoDocExistentePorTexto = true;
      } else {
        descartoDocExistentePorTitulo = true;
      }

      const titConservado = tituloOriginalIngresado || (s.form && s.form.titulo) || '';
      const txtConservado = (eraPorTexto && textoOriginalIngresado) ? textoOriginalIngresado : '';
      const bloquesAUsar = (eraPorTexto && textoOriginalIngresado)
        ? ((bloquesOriginalesIngresados && bloquesOriginalesIngresados.length) ? bloquesOriginalesIngresados.slice() : [txtConservado])
        : [''];

      estadoVistaPrevia.bloques_texto = [''];
      estadoVistaPrevia.recursos = [];
      estadoEditor.bloques_texto = bloquesAUsar.slice();
      estadoEditor.recursos = [];
      textareasMap.clear();
      reconstruirBloques(bloquesAUsar, [], null);
      estadoEditor.modo = 'edicion';

      const btnEd = $('#btnEditor');
      if (btnEd) {
        btnEd.classList.add('sel');
        btnEd.setAttribute('aria-pressed', 'true');
      }
      const btnPr = $('#btnPreview');
      if (btnPr) {
        btnPr.classList.remove('sel');
        btnPr.setAttribute('aria-pressed', 'false');
      }
      const prEl = $('#preview');
      if (prEl) prEl.hidden = true;
      const ebwEl = $('#editorBloquesWrapper');
      if (ebwEl) ebwEl.hidden = false;
      const fcEl = $('#fCuerpo');
      if (fcEl) fcEl.value = txtConservado;
      const slotEl = $('#slotBorrador');
      if (slotEl) slotEl.innerHTML = '';
      const barEl = $('#editorImgBar');
      if (barEl) {
        barEl.hidden = true;
        barEl.innerHTML = '';
      }
      const pmEl = $('#panelMultimedia');
      if (pmEl) {
        pmEl.hidden = true;
        pmEl.innerHTML = '';
      }
      renderBloques();

      store.set({
        flujo: 'ESPERANDO_TEXTO',
        borrador: null,
        coincidencias: [],
        validacion: null,
        aviso_metadatos_heredados: null,
        opciones: ['confirmar_texto', 'volver']
      });
      store.setForm({
        titulo: titConservado,
        texto: txtConservado,
        texto_editor: txtConservado,
        tags: [],
        categoria_id: null
      });

      if ($('#fTitulo')) $('#fTitulo').value = titConservado;

      pintar(store.get());

      burbuja('me', esc(label || 'Es un tema distinto'));
      if (eraPorTexto) {
        decir('Listo, lo tomamos como un tema distinto. Podés continuar con tu texto.', ['confirmar_texto', 'volver']);
      } else {
        decir('Listo, lo tomamos como un tema distinto. Contame el contenido del artículo.', ['confirmar_texto', 'volver']);
      }
      return;
    }
    enviarTurno({ accion: op }, label);
  }

  BACO.accionar = accionar;

  async function confirmarTexto() {
    const s = store.get();
    sincronizarTextoDesdePreview();
    const contBloques = $('#contenedorBloques');
    if (contBloques) {
      contBloques.querySelectorAll('.bloque-textarea').forEach((ta) => {
        const idx = parseInt(ta.getAttribute('data-bloque-idx'), 10);
        if (!isNaN(idx)) {
          while (estadoEditor.bloques_texto.length <= idx) {
            estadoEditor.bloques_texto.push('');
          }
          estadoEditor.bloques_texto[idx] = ta.value;
        }
        const b = estadoEditor.bloques.find((x) => x.id === ta.getAttribute('data-id'));
        if (b) b.contenido = ta.value;
      });
    }
    const esEnriquecer = Boolean(s && s.borrador && s.borrador.modo === 'enriquecimiento');
    let textoFinal = '';
    const textoEditor = componerTextoDesdeBloques().trim();
    if (esEnriquecer) {
      textoFinal = (estadoVistaPrevia.bloques_texto && estadoVistaPrevia.bloques_texto.length)
        ? estadoVistaPrevia.bloques_texto.join('\n\n').trim()
        : (s.borrador && s.borrador.texto_limpio ? s.borrador.texto_limpio.trim() : '');
      store.setForm({ texto: textoFinal, texto_editor: textoEditor });
    } else {
      sincronizarTextoConStore();
      const fc = $('#fCuerpo');
      if (fc && !fc.hidden && fc.value !== s.form.texto) {
        store.setForm({ texto: fc.value });
      }
      textoFinal = (s.form && typeof s.form.texto === 'string' ? s.form.texto : (fc ? fc.value : '')).trim();
    }
    // Si hay múltiples bloques o recursos intercalados, sincronizamos primero /chat/bloques
    if (
      !esEnriquecer &&
      typeof api.confirmarBloques === 'function' &&
      (estadoEditor.bloques_texto.length > 1 || estadoEditor.recursos.length > 0)
    ) {
      try {
        const payloadBloques = [];
        sincronizarSecuenciaVisual();
        estadoEditor.bloques.forEach((b) => {
          if (b.tipo === 'texto') {
            payloadBloques.push({ tipo: 'texto', contenido: b.contenido || '' });
          } else if (b.tipo === 'recurso' && b.recurso) {
            const recObj = {
              nombre: b.recurso.nombre || '',
              tipo: b.recurso.tipo || 'imagen'
            };
            if (b.recurso.id) {
              recObj.id = b.recurso.id;
            }
            if (b.recurso.referencia || b.recurso.url) {
              recObj.url = b.recurso.referencia || b.recurso.url;
            }
            payloadBloques.push({
              tipo: 'recurso',
              recurso: recObj
            });
          }
        });
        const resB = await api.confirmarBloques(payloadBloques);
        if (resB && typeof resB.texto_limpio === 'string') {
          store.setForm({ texto: resB.texto_limpio });
        }
      } catch (_) {}
    }

    if (!textoFinal) {
      const fc = $('#fCuerpo');
      textoFinal = (s.form && typeof s.form.texto === 'string' ? s.form.texto : (fc ? fc.value : '')).trim();
    }
    if (textoFinal) {
      const lenCp = Array.from(textoFinal).length;
      if (lenCp > cfg.MAX_TEXTO_PERCENTIL_99) return;
      if (descartoDocExistentePorTitulo || descartoDocExistentePorTexto) {
        descartoDocExistentePorTitulo = false;
        descartoDocExistentePorTexto = false;
        return enviarTurno({
          accion: 'descartar',
          texto: textoFinal,
          titulo: (s.form && s.form.titulo) || tituloOriginalIngresado
        }, 'Confirmar texto (' + lenCp + ' caracteres)');
      }
      return enviarTurno({
        accion: 'confirmar_texto',
        texto: textoFinal,
        texto_editor: esEnriquecer ? textoEditor : undefined
      }, 'Confirmar texto (' + lenCp + ' caracteres)');
    }
    const chatIn = $('#chatInput');
    const pendiente = chatIn ? chatIn.value.trim() : '';
    if (pendiente) {
      const lenPend = Array.from(pendiente).length;
      if (lenPend > cfg.MAX_TEXTO_PERCENTIL_99) return;
      chatIn.value = '';
      chatIn.style.height = 'auto';
      if (descartoDocExistentePorTitulo || descartoDocExistentePorTexto) {
        descartoDocExistentePorTitulo = false;
        descartoDocExistentePorTexto = false;
        return enviarTurno({
          accion: 'descartar',
          texto: pendiente,
          titulo: (s.form && s.form.titulo) || tituloOriginalIngresado
        }, 'Confirmar texto (' + lenPend + ' caracteres)');
      }
      return enviarTurno({ accion: 'confirmar_texto', texto: pendiente }, 'Confirmar texto (' + lenPend + ' caracteres)');
    }
    if (descartoDocExistentePorTitulo || descartoDocExistentePorTexto) {
      descartoDocExistentePorTitulo = false;
      descartoDocExistentePorTexto = false;
      return enviarTurno({ accion: 'descartar' }, 'Confirmar texto');
    }
    return enviarTurno({ accion: 'confirmar_texto' }, 'Confirmar texto');
  }

  function enviarPrincipal() {
    const s = store.get();
    const acc = BACO.ACCION_PRINCIPAL[s.flujo];
    if (!acc) return;

    if (acc.campo === 'titulo') return enviarTurno({ titulo: s.form.titulo }, s.form.titulo);
    if (acc.campo === 'texto')  return confirmarTexto();
    if (acc.campo === 'tags') {
      return enviarTurno(
        { tags: s.form.tags, categoria_id: s.form.categoria_id },
        s.form.tags.join(', ') + ' · ' + nombreCategoria(s, s.form.categoria_id)
      );
    }
    return enviarTurno({
      titulo: s.form.titulo, texto: s.form.texto,
      tags: s.form.tags, categoria_id: s.form.categoria_id
    }, 'Guardar cambios');
  }

  function limpiarMarcadoresSeccion(texto) {
    if (!texto || typeof texto !== 'string') return '';
    return texto.replace(/^#{1,6}\s+/gm, '');
  }

  /* Cuando una skill devuelve texto, se vuelca en el panel izquierdo como un único bloque de texto (bloques_texto = [resultado]) */
  function transferirTextoAlPanelIzquierdo(texto, avisoToast = true) {
    const s = store.get();
    const textoLimpio = limpiarMarcadoresSeccion(texto);
    const recs = (s.borrador && (Array.isArray(s.borrador.multimedia) ? s.borrador.multimedia : Object.values(s.borrador.recursos || {}))) || [];

    store.setForm({ texto: textoLimpio });
    if (s.borrador) {
      s.borrador.bloques_texto = [texto];
      s.borrador.texto_limpio = textoLimpio;
      s.borrador.texto_alineado_discourse = texto;
      if (s.borrador.texto != null) s.borrador.texto = texto;
    }

    const fc = $('#fCuerpo');
    if (fc) fc.value = textoLimpio;

    reconstruirBloques([textoLimpio], recs, s.borrador);
    renderBloques();

    const prev = $('#preview');
    if (prev && !prev.hidden) {
      prev.innerHTML = renderMd(textoVistaPrevia(store.get()));
    }

    if (avisoToast) {
      toast('Texto transferido al panel de carga (como bloque único)');
    }
  }

  /* ---- skills del agente: endpoints dedicados ---- */
  async function invocarAgente(metodo, etiqueta) {
    const s = store.get();
    if (!s.borrador) {
      decir('Todavía no hay un borrador armado. Las skills se habilitan recién cuando lleguemos a la revisión.');
      return;
    }
    const tieneRecursos = Boolean(
      (Array.isArray(s.borrador.multimedia) && s.borrador.multimedia.length > 0) ||
      (s.borrador.recursos && Object.keys(s.borrador.recursos).length > 0) ||
      (estadoEditor.recursos && estadoEditor.recursos.length > 0)
    );
    if (s.borrador.skills_habilitadas === false || tieneRecursos) {
      const mot = s.borrador.skills_motivo || 'Quitá los recursos cargados si querés aplicar las skills de asistencia.';
      toast('Skills deshabilitadas: ' + mot);
      decir('⚠️ Las skills no están disponibles para este borrador:\n' + esc(mot));
      return;
    }
    burbuja('me', esc(etiqueta));
    const esperando = burbuja('bot', '<div class="typing"><i></i><i></i><i></i></div>' +
      '<div class="lento">El agente puede tardar varios segundos…</div>');
    estadoEditor.enviando = true;
    renderBloques();
    try {
      const r = typeof metodo === 'string'
        ? await api[metodo]()
        : (api.chat ? await api.chat(metodo.prompt) : await api.prompt(metodo));
      esperando.remove();
      estadoEditor.enviando = false;
      renderBloques();
      ultimoFallo = null;

      const textoRespuesta = (r && (r.texto_resultante || r.response)) || '';

      if (textoRespuesta) {
        transferirTextoAlPanelIzquierdo(textoRespuesta, true);
      }

      const textoChat = metodo === 'aplicarPlantilla' || metodo === 'auditarSemantica'
        ? '🤖 Apliqué la **skill** y los resultados fueron transferidos a la sección izquierda del panel'
        : r.response;

      const msgHtml = '<div class="respuesta-agente">' + nl2br(textoChat) + '</div>' +
        '<div style="margin-top:8px;"><button type="button" class="btn btn-sm btn-ghost btn-transferir-panel" style="font-size:12px; cursor:pointer;">↖ Transferido al panel de carga (clic para volver a transferir)</button></div>';
      const bubbleEl = decir(msgHtml, ['ver_articulo_final'], true);
      if (bubbleEl) {
        const btnTransf = bubbleEl.querySelector('.btn-transferir-panel');
        if (btnTransf) {
          btnTransf.onclick = () => transferirTextoAlPanelIzquierdo(textoRespuesta, true);
        }
        const btnVer = bubbleEl.querySelector('#btnVerArticuloFinal');
        if (btnVer && btnVer.parentElement) {
          const btnContinuar = el('button', 'btn btn-sm btn-primary', 'Continuar');
          btnContinuar.id = 'btnContinuarPostSkill';
          // TODO: etapa 6 (revalidación silenciosa)
          btnContinuar.onclick = () => {
            console.log("Continuar post-skill: pendiente de implementar");
          };
          btnVer.parentElement.appendChild(btnContinuar);
        }
      }
    } catch (e) {
      esperando.remove();
      estadoEditor.enviando = false;
      renderBloques();
      ultimoFallo = { tipo: 'agente', metodo: metodo, etiqueta: etiqueta };
      mostrarError(e);
      const es422 = e.http === 422 || (e.message && e.message.includes('422'));
      if (es422) {
        const detalle = e.message || (s.borrador && s.borrador.skills_motivo) || 'Skills deshabilitadas por el servidor.';
        toast('Skills deshabilitadas (422)');
        decir('⚠️ Las skills no están disponibles para este borrador:\n' + esc(detalle));
      } else {
        decir('El agente no respondió: ' + esc(e.message));
      }
    }
  }

  function aplicarPlantilla() {
    invocarAgente('aplicarPlantilla', 'Aplicar la plantilla al borrador');
  }

  function auditar() {
    invocarAgente('auditarSemantica', 'Auditar con el validador');
  }

  /* ---- borrador en conformidad ---- */
  async function mostrarConforme() {
    const s = store.get();
    try {
      const b = (api.borradorConforme ? await api.borradorConforme() : await api.borradorAprobado());
      const tagsFinales = (s.tags_acumulados && s.tags_acumulados.length)
        ? s.tags_acumulados
        : (b.tags || []);
      const etapaFinal = s.etapa
        ? ('Etapa ' + s.etapa.actual + ' de ' + s.etapa.total + ' · ' + s.etapa.nombre)
        : 'Etapa 5 de 5 · Conformidad';
      $('#recap').innerHTML =
        '<div class="r"><span class="k">Progreso</span><span class="v">' + esc(etapaFinal) + '</span></div>' +
        '<div class="r"><span class="k">Modo</span><span class="v">' + esc(b.modo) + '</span></div>' +
        (b.articulo_original_id ? '<div class="r"><span class="k">Sobre</span><span class="v">#' + b.articulo_original_id + '</span></div>' : '') +
        '<div class="r"><span class="k">Título</span><span class="v">' + esc(b.titulo) + '</span></div>' +
        '<div class="r"><span class="k">Plantilla</span><span class="v">' + esc(b.tipo_plantilla || '—') + '</span></div>' +
        '<div class="r"><span class="k">Categoría</span><span class="v">' + esc(nombreCategoria(s, b.categoria_id)) + '</span></div>' +
        '<div class="r"><span class="k">Etiquetas</span><span class="v">' + tagsFinales.map(esc).join(' · ') + '</span></div>';
      $('#overlay').hidden = false;
    } catch (e) { mostrarError(e); }
  }

  async function copiarBorrador() {
    const s = store.get();
    try {
      let b = s.borrador;
      if (s.flujo === 'CONFORMIDAD_USUARIO' || s.flujo === 'APROBADO') {
        try {
          b = (api.borradorConforme ? await api.borradorConforme() : await api.borradorAprobado()) || b;
        } catch (_) {}
      }
      const titulo = (b && b.titulo) || s.form.titulo || '';
      const textoDiscourse = (b && (b.texto_alineado_discourse || b.texto_limpio)) || s.form.texto || '';
      const textoACopiar = `# ${titulo}\n\n${textoDiscourse}`.trim();
      if (!textoACopiar) {
        toast('No hay contenido en el borrador para copiar');
        return;
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(textoACopiar);
      } else {
        const ta = document.createElement('textarea');
        ta.value = textoACopiar;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      toast('Borrador copiado al portapapeles');
    } catch (e) {
      toast('No se pudo copiar el borrador: ' + (e.message || e));
    }
  }

  /* =========================================================
     Chat
     ========================================================= */
  function burbuja(quien, html) {
    const m = el('div', 'msg ' + quien);
    m.appendChild(el('div', 'av', quien === 'bot'
      ? '<svg width="14" height="14" viewBox="0 0 16 16" fill="none"><rect x="2.6" y="4.6" width="10.8" height="8.2" rx="2.2" stroke="currentColor" stroke-width="1.4"/><circle cx="6.1" cy="8.4" r="1" fill="currentColor"/><circle cx="9.9" cy="8.4" r="1" fill="currentColor"/></svg>'
      : 'DK'));
    m.appendChild(el('div', 'bubble', html + '<div class="stamp">' + hora() + '</div>'));
    $('#thread').appendChild(m);
    $('#thread').scrollTop = $('#thread').scrollHeight;
    return m;
  }

  function decir(html, opciones, ancho) {
    const b = burbuja('bot', html);
    if (ancho) b.querySelector('.bubble').classList.add('ancha');
    /* En el panel derecho (BACO Companion) nunca se muestra el botón "Confirmar texto" */
    const opcionesCompanion = (opciones || []).filter((op) => op !== 'confirmar_texto');
    const sActual = store.get();
    const tieneMetaPendiente = (sActual.flujo === 'REVISION_BORRADOR' && !!(sActual.aviso_metadatos_heredados || (sActual.borrador && sActual.borrador.metadatos_anteriores && !sActual.borrador.metadatos_heredados_revisados)));
    const cartelConBotones = Boolean(
      $('#bannerMetadatosHeredados') &&
      $('#bannerMetadatosHeredados').querySelector('#btnAcepMetaHeredados')
    );
    const opcionesCompanionFinal = (tieneMetaPendiente && cartelConBotones) ? [] : opcionesCompanion;
    if (opcionesCompanionFinal.length) {
      const cont = el('div', 'acciones');
      opcionesCompanionFinal.forEach((op) => {
        const def = BACO.OPCIONES[op] || { label: op, estilo: 'btn-ghost' };
        const btn = el('button', 'btn btn-sm ' + def.estilo, esc(def.label));
        if (op === 'ver_articulo_final') btn.id = 'btnVerArticuloFinal';
        btn.onclick = () => accionar(op, def.label);
        cont.appendChild(btn);
      });
      b.querySelector('.bubble').insertBefore(cont, b.querySelector('.stamp'));
    }
    return b;
  }

  async function enviarChatLibre() {
    const v = $('#chatInput').value.trim();
    if (!v) return;
    $('#chatInput').value = ''; $('#chatInput').style.height = 'auto';

    const s = store.get();
    if (s.flujo === 'ESPERANDO_TITULO')  return enviarTurno({ titulo: v }, v);
    if (s.flujo === 'ESPERANDO_TEXTO') {
      const cmd = v.toLowerCase();
      if (['es un tema distinto', 'tema distinto', 'descartar'].includes(cmd) && (consultandoDocExistentePorTitulo || consultandoDocExistentePorTexto)) {
        return accionar('descartar', 'Es un tema distinto');
      }
      if (['volver', 'atras', 'atrás', 'regresar', 'reiniciar', 'ayuda', '?', 'descartar', 'continuar'].includes(cmd)) {
        return enviarTurno({ mensaje: v }, v);
      }
      if (cmd === 'confirmar' || cmd === 'confirmar texto' || cmd === 'confirmar_texto') {
        return confirmarTexto();
      }
      // Si ya hay bloques existentes, agregamos al final del último bloque de texto
      const lastIdx = Math.max(0, estadoEditor.bloques_texto.length - 1);
      const prevLast = String(estadoEditor.bloques_texto[lastIdx] || '').trim();
      estadoEditor.bloques_texto[lastIdx] = prevLast ? (prevLast + '\n\n' + v) : v;
      sincronizarTextoConStore();
      renderBloques();
      const acumulado = componerTextoDesdeBloques();
      if (descartoDocExistentePorTitulo || descartoDocExistentePorTexto) {
        descartoDocExistentePorTitulo = false;
        descartoDocExistentePorTexto = false;
        return enviarTurno({ accion: 'descartar', mensaje: v, texto: acumulado, titulo: (s.form && s.form.titulo) || tituloOriginalIngresado }, v);
      }
      return enviarTurno({ mensaje: v, texto: acumulado }, v);
    }
    if (s.flujo === 'ESPERANDO_METADATOS') {
      return enviarTurno({ mensaje: v, categoria_id: s.form.categoria_id }, v);
    }
    if (s.flujo === 'ESPERANDO_PLANTILLA' ||
        s.flujo === 'DECISION_TITULO' || s.flujo === 'DECISION_TEXTO') {
      return enviarTurno({ mensaje: v }, v);
    }
    invocarAgente({ prompt: v }, v);
  }

  /* =========================================================
     Errores y avisos
     ========================================================= */
  function mostrarError(e) {
    const b = $('#bannerError');
    if (!b) return;
    const ayuda = {
      SIN_API_KEY: 'Abrí js/config.js y pegá la API_KEY que te pase Caro.',
      NO_AUTORIZADO: 'La API key no coincide con la del backend.',
      SIN_CONEXION: '¿El backend está levantado? Revisá BASE_URL en js/config.js.'
    }[e.codigo];

    b.innerHTML = '<div class="banner">' +
      '<svg width="15" height="15" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6.4" stroke="currentColor" stroke-width="1.4"/><path d="M8 4.8v3.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="8" cy="11.2" r=".9" fill="currentColor"/></svg>' +
      '<span><b>' + esc(e.codigo || 'ERROR') + '</b> · ' + esc(e.message || 'Algo falló.') +
      (ayuda ? '<br><i>' + esc(ayuda) + '</i>' : '') + '</span>' +
      (ultimoFallo ? '<button class="btn btn-sm reintentar">Reintentar</button>' : '') +
      '<button class="cerrar" aria-label="Cerrar">&times;</button></div>';

    b.querySelector('.cerrar').onclick = () => { b.innerHTML = ''; };
    const rb = b.querySelector('.reintentar');
    if (rb) rb.onclick = reintentar;
  }

  function reintentar() {
    const f = ultimoFallo;
    ultimoFallo = null;
    $('#bannerError').innerHTML = '';
    if (!f) return;
    if (f.tipo === 'turno') enviarTurno(f.payload);
    else invocarAgente(f.metodo, f.etiqueta);
  }

  function mostrarAviso(texto) {
    const b = $('#bannerPrivacidad');
    if (!b) return;
    b.innerHTML = '<div class="banner aviso">' +
      '<svg width="15" height="15" viewBox="0 0 16 16" fill="none"><path d="M8 1.8l5 2v4.4c0 3-2.2 5.3-5 6-2.8-.7-5-3-5-6V3.8l5-2z" stroke="currentColor" stroke-width="1.3"/><path d="M5.9 8.1l1.5 1.5 3-3.1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>' +
      '<span><b>Datos sensibles anonimizados</b> · ' + esc(texto) + '</span>' +
      '<button class="cerrar" aria-label="Cerrar">&times;</button></div>';
    b.querySelector('.cerrar').onclick = () => { b.innerHTML = ''; };
  }

  function toast(msg) {
    const t = $('#toast');
    if (!t) return;
    t.textContent = msg; t.classList.add('show');
    clearTimeout(tToast);
    tToast = setTimeout(() => t.classList.remove('show'), 2400);
  }

  function pintarRecursosDetectados(s) {
    BACO.panelMultimedia.pintar($('#panelMultimedia'), s);
    const pm = $('#panelMultimedia');
    if (pm) { pm.hidden = true; pm.innerHTML = ''; }

    const bar = $('#editorImgBar');
    if (!bar) return;
    const b = s && s.borrador;
    const esEnriquecerOActualizar = b && (b.modo === 'enriquecimiento' || b.modo === 'actualizar' || b.articulo_original_id != null);
    const adicionales = (b && b.contenido_adicional) || [];

    /* 2. Contenido adicional (texto): sección aparte, solo en enriquecer / actualizar */
    if (!adicionales.length && !esEnriquecerOActualizar) {
      bar.hidden = true;
      bar.innerHTML = '';
      return;
    }

    let h = '';

    if (esEnriquecerOActualizar) {
      h += '<div class="eib-sec-adicional">' +
        '<div class="eib-sec-adicional-head">' +
          '<div>' +
            '<span class="eib-sec-adicional-tit">➕ Contenido adicional del artículo</span>' +
            '<button type="button" class="btn-agregar-contenido" id="btnAgregarContenido" title="Agregar contenido nuevo" aria-label="Agregar contenido nuevo">+</button>' +
            '<span class="eib-adicional-count">(' + adicionales.length + ')</span>' +
          '</div>' +
          '<span class="eib-subtit">Sección aparte · Las skills no leen ni modifican esta sección</span>' +
        '</div>' +
        '<div class="eib-nuevo-form">' +
          '<input type="text" class="input eib-input-nuevo" id="inputNuevoContenido" placeholder="Escribí aquí el contenido nuevo a incorporar..." autocomplete="off" />' +
          '<button type="button" class="btn btn-sm btn-dark" id="btnConfirmarAgregar">+ Añadir</button>' +
        '</div>';

      if (!adicionales.length) {
        h += '<div class="eib-vacio-aviso">' +
          '💡 Todavía no agregaste contenido adicional. Podés escribir arriba y presionar <b>+ Añadir</b> para sumarlo al borrador.' +
          '</div>';
      } else {
        h += '<div class="eib-adicional-list">';
        adicionales.forEach((item, idx) => {
          const itemId = esc(item.id);
          const itemTxt = esc(item.contenido || '');
          const itemTipo = esc(item.tipo || 'texto');
          h += '<div class="eib-adicional-item" data-id="' + itemId + '">' +
            '<div class="eib-item-view" id="eibItemView_' + itemId + '">' +
              '<div class="eib-item-left">' +
                '<button type="button" class="btn-eliminar-item" data-id="' + itemId + '" title="Eliminar ítem" aria-label="Eliminar ítem">×</button>' +
                '<span class="eib-item-num" title="Posición en la lista">#' + (idx + 1) + '</span>' +
                '<div class="eib-reordenar-btns">' +
                  '<button type="button" class="btn-mover-item" data-id="' + itemId + '" data-dir="up" title="Subir orden" ' + (idx === 0 ? 'disabled' : '') + '>▲</button>' +
                  '<button type="button" class="btn-mover-item" data-id="' + itemId + '" data-dir="down" title="Bajar orden" ' + (idx === adicionales.length - 1 ? 'disabled' : '') + '>▼</button>' +
                '</div>' +
              '</div>' +
              '<div class="eib-item-body">' +
                '<span class="eib-adicional-tipo">' + itemTipo + '</span>' +
                '<span class="eib-adicional-txt" title="' + itemTxt + '">' + itemTxt + '</span>' +
              '</div>' +
              '<div class="eib-item-actions">' +
                '<button type="button" class="btn-editar-item" data-id="' + itemId + '" title="Modificar contenido">✎ Modificar</button>' +
              '</div>' +
            '</div>' +
            '<div class="eib-item-edit" id="eibItemEdit_' + itemId + '" style="display:none;">' +
              '<input type="text" class="input eib-input-edit" id="inputEdit_' + itemId + '" value="' + itemTxt + '" />' +
              '<div class="eib-edit-actions">' +
                '<button type="button" class="btn btn-xs btn-primary btn-guardar-item" data-id="' + itemId + '">Guardar</button>' +
                '<button type="button" class="btn btn-xs btn-ghost btn-cancelar-item" data-id="' + itemId + '">Cancelar</button>' +
              '</div>' +
            '</div>' +
          '</div>';
        });
        h += '</div>';
      }
      h += '</div>';
    }

    bar.innerHTML = h;
    const prev = $('#preview');
    bar.hidden = !!(prev && !prev.hidden);

    const ejecutarAgregar = async () => {
      const input = $('#inputNuevoContenido');
      if (!input) return;
      const texto = input.value.trim();
      if (!texto) {
        toast('Escribí el contenido que querés añadir');
        input.focus();
        return;
      }
      try {
        let item;
        if (api.agregarContenidoAdicional) {
          item = await api.agregarContenidoAdicional(texto);
        } else {
          item = {
            id: 'ca_' + Math.random().toString(36).substr(2, 8),
            tipo: 'texto',
            contenido: texto,
            posicion: adicionales.length
          };
        }
        if (b) {
          b.contenido_adicional = b.contenido_adicional || [];
          b.contenido_adicional.push(item);
          if (b.conforme) {
            b.conforme = false;
            b.conforme_en = null;
            b.conformidad_invalidada = true;
            if (s.flujo === 'CONFORMIDAD_USUARIO') s.flujo = 'REVISION_BORRADOR';
          }
        }
        pintarRecursosDetectados(s);
        toast('Contenido nuevo agregado a la sección aparte');
      } catch (err) {
        toast('Error al agregar contenido: ' + (err.message || err));
      }
    };

    const btnAdd = $('#btnConfirmarAgregar');
    if (btnAdd) btnAdd.onclick = (e) => { e.preventDefault(); ejecutarAgregar(); };

    const btnPlus = $('#btnAgregarContenido');
    if (btnPlus) {
      btnPlus.onclick = (e) => {
        e.preventDefault();
        const inp = $('#inputNuevoContenido');
        if (inp) {
          inp.focus();
          if (inp.value.trim()) ejecutarAgregar();
        }
      };
    }

    const inpAdd = $('#inputNuevoContenido');
    if (inpAdd) {
      inpAdd.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          ejecutarAgregar();
        }
      });
    }

    bar.querySelectorAll('.btn-editar-item').forEach((btn) => {
      btn.onclick = (e) => {
        e.preventDefault();
        const id = btn.dataset.id;
        const v = $('#eibItemView_' + id);
        const ed = $('#eibItemEdit_' + id);
        const inp = $('#inputEdit_' + id);
        if (v && ed) {
          v.style.display = 'none';
          ed.style.display = 'flex';
          if (inp) { inp.focus(); inp.select(); }
        }
      };
    });

    bar.querySelectorAll('.btn-cancelar-item').forEach((btn) => {
      btn.onclick = (e) => {
        e.preventDefault();
        const id = btn.dataset.id;
        const v = $('#eibItemView_' + id);
        const ed = $('#eibItemEdit_' + id);
        if (v && ed) {
          ed.style.display = 'none';
          v.style.display = 'flex';
        }
      };
    });

    const guardarEdicion = async (id) => {
      const inp = $('#inputEdit_' + id);
      if (!inp) return;
      const nuevoTexto = inp.value.trim();
      if (!nuevoTexto) {
        toast('El contenido no puede estar vacío');
        inp.focus();
        return;
      }
      try {
        if (api.modificarContenidoAdicional) {
          await api.modificarContenidoAdicional(id, nuevoTexto);
        }
        if (b && b.contenido_adicional) {
          const it = b.contenido_adicional.find((x) => x.id === id);
          if (it) it.contenido = nuevoTexto;
          if (b.conforme) {
            b.conforme = false;
            b.conforme_en = null;
            b.conformidad_invalidada = true;
            if (s.flujo === 'CONFORMIDAD_USUARIO') s.flujo = 'REVISION_BORRADOR';
          }
        }
        pintarRecursosDetectados(s);
        toast('Contenido modificado correctamente');
      } catch (err) {
        toast('Error al modificar ítem: ' + (err.message || err));
      }
    };

    bar.querySelectorAll('.btn-guardar-item').forEach((btn) => {
      btn.onclick = (e) => {
        e.preventDefault();
        guardarEdicion(btn.dataset.id);
      };
    });

    bar.querySelectorAll('.eib-input-edit').forEach((inp) => {
      inp.addEventListener('keydown', (e) => {
        const id = inp.id.replace('inputEdit_', '');
        if (e.key === 'Enter') {
          e.preventDefault();
          guardarEdicion(id);
        } else if (e.key === 'Escape') {
          e.preventDefault();
          const v = $('#eibItemView_' + id);
          const ed = $('#eibItemEdit_' + id);
          if (v && ed) {
            ed.style.display = 'none';
            v.style.display = 'flex';
          }
        }
      });
    });

    bar.querySelectorAll('.btn-eliminar-item').forEach((btn) => {
      btn.onclick = async (e) => {
        e.preventDefault();
        const id = btn.dataset.id;
        if (!id) return;
        try {
          if (api.eliminarContenidoAdicional) {
            await api.eliminarContenidoAdicional(id);
          }
          if (b && b.contenido_adicional) {
            b.contenido_adicional = b.contenido_adicional.filter((it) => it.id !== id);
            b.contenido_adicional.forEach((it, idx) => { it.posicion = idx; });
            if (b.conforme) {
              b.conforme = false;
              b.conforme_en = null;
              b.conformidad_invalidada = true;
              if (s.flujo === 'CONFORMIDAD_USUARIO') s.flujo = 'REVISION_BORRADOR';
            }
          }
          pintarRecursosDetectados(s);
          toast('Ítem eliminado del borrador');
        } catch (err) {
          toast('Error al eliminar ítem: ' + (err.message || err));
        }
      };
    });

    bar.querySelectorAll('.btn-mover-item').forEach((btn) => {
      btn.onclick = async (e) => {
        e.preventDefault();
        const id = btn.dataset.id;
        const dir = btn.dataset.dir;
        if (!id || !b || !b.contenido_adicional) return;
        const idx = b.contenido_adicional.findIndex((it) => it.id === id);
        if (idx === -1) return;
        const targetIdx = dir === 'up' ? idx - 1 : idx + 1;
        if (targetIdx < 0 || targetIdx >= b.contenido_adicional.length) return;

        const temp = b.contenido_adicional[idx];
        b.contenido_adicional[idx] = b.contenido_adicional[targetIdx];
        b.contenido_adicional[targetIdx] = temp;
        b.contenido_adicional.forEach((it, i) => { it.posicion = i; });

        const ordenIds = b.contenido_adicional.map((it) => it.id);
        try {
          if (api.reordenarContenidoAdicional) {
            await api.reordenarContenidoAdicional(ordenIds);
          }
          if (b.conforme) {
            b.conforme = false;
            b.conforme_en = null;
            b.conformidad_invalidada = true;
            if (s.flujo === 'CONFORMIDAD_USUARIO') s.flujo = 'REVISION_BORRADOR';
          }
          pintarRecursosDetectados(s);
          toast('Orden de contenido actualizado');
        } catch (err) {
          toast('Error al reordenar: ' + (err.message || err));
        }
      };
    });
  }

  function pintarImagenesDetectadas(s) {
    pintarRecursosDetectados(s);
  }

  /* Markdown adaptativo para la vista previa */
  function renderMd(src) {
    const renderInline = (s) => {
      let res = String(s).replace(
        /!\[([^\]]*)\]\(((?:https?:\/\/|\/api\/recursos-temp\/)[^\s\)]+)\)/g,
        '___IMG_START___$1___SEP___$2___IMG_END___'
      ).replace(
        /\[([^\]]+)\|attachment\]\(((?:https?:\/\/|\/api\/recursos-temp\/)[^\s\)]+)\)/g,
        '___ATT_START___$1___SEP___$2___ATT_END___'
      ).replace(
        /\[([^\]]+)\]\((https?:\/\/[^\s\)]+)\)/g,
        '___LINK_START___$1___SEP___$2___LINK_END___'
      );

      res = esc(res);

      res = res.replace(
        /___IMG_START___(.*?)___SEP___(.*?)___IMG_END___/g,
        '<div class="preview-img-box"><img src="$2" alt="$1" class="preview-img" loading="lazy" referrerpolicy="no-referrer" /><span class="caption">$1</span></div>'
      ).replace(
        /___ATT_START___(.*?)___SEP___(.*?)___ATT_END___/g,
        '<div class="preview-media-card attachment"><div class="pmc-main"><span class="pmc-icon">📎</span><div class="pmc-info"><span class="pmc-tag">Archivo adjunto</span><a class="pmc-title" href="$2" target="_blank" rel="noopener">$1</a></div></div><a class="pmc-btn" href="$2" target="_blank" rel="noopener">Descargar ↗</a></div>'
      ).replace(
        /___LINK_START___(.*?)___SEP___(.*?)___LINK_END___/g,
        (match, title, url) => {
          const rec = clasificarRecurso(url, title, false, false);
          if (rec.tipo === 'doc') {
            return '<div class="preview-media-card docs"><div class="pmc-main"><span class="pmc-icon">📄</span><div class="pmc-info"><span class="pmc-tag">Google Docs</span><a class="pmc-title" href="' + url + '" target="_blank" rel="noopener">' + title + '</a></div></div><a class="pmc-btn" href="' + url + '" target="_blank" rel="noopener">Abrir documento ↗</a></div>';
          }
          if (rec.tipo === 'slides') {
            return '<div class="preview-media-card slides"><div class="pmc-main"><span class="pmc-icon">📊</span><div class="pmc-info"><span class="pmc-tag">Diapositivas</span><a class="pmc-title" href="' + url + '" target="_blank" rel="noopener">' + title + '</a></div></div><a class="pmc-btn" href="' + url + '" target="_blank" rel="noopener">Ver presentación ↗</a></div>';
          }
          if (rec.tipo === 'video') {
            return '<div class="preview-media-card video"><div class="pmc-main"><span class="pmc-icon">🎬</span><div class="pmc-info"><span class="pmc-tag">Video</span><a class="pmc-title" href="' + url + '" target="_blank" rel="noopener">' + title + '</a></div></div><a class="pmc-btn" href="' + url + '" target="_blank" rel="noopener">Ver video ↗</a></div>';
          }
          return '<a class="preview-link" href="' + url + '" target="_blank" rel="noopener">' + title + ' ↗</a>';
        }
      );

      return res
        .replace(/\*\*([^\*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^\*]+)\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code>$1</code>');
    };

    const out = []; let lista = null;
    const cerrar = () => { if (lista) { out.push('</' + lista + '>'); lista = null; } };

    String(src).split('\n').forEach((raw) => {
      const l = raw.trim();
      if (!l) { cerrar(); return; }

      const imgMatch = l.match(/^!\[([^\]]*)\]\(((?:https?:\/\/|\/api\/recursos-temp\/)[^\s\)]+)\)$/);
      if (imgMatch) {
        cerrar();
        const alt = esc(imgMatch[1]);
        const url = encodeURI(imgMatch[2]);
        out.push('<div class="preview-img-box"><img src="' + url + '" alt="' + alt + '" class="preview-img" loading="lazy" referrerpolicy="no-referrer" /><span class="caption">' + alt + '</span></div>');
        return;
      }

      const ytMatch = l.match(/^(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:watch\?v=|embed\/|shorts\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})(?:[^\s]*)?$/);
      if (ytMatch) {
        cerrar();
        const ytId = ytMatch[1];
        const fullUrl = l.startsWith('http') ? l : ('https://' + l);
        out.push('<div class="preview-video-box"><iframe class="preview-video-frame" src="https://www.youtube.com/embed/' + ytId + '" title="Video tutorial" frameborder="0" allowfullscreen loading="lazy"></iframe><div class="caption">🎬 Video explicativo · <a class="preview-link" href="' + encodeURI(fullUrl) + '" target="_blank" rel="noopener">Abrir en YouTube ↗</a></div></div>');
        return;
      }

      const urlSoleMatch = l.match(/^(https?:\/\/[^\s]+)$/);
      if (urlSoleMatch) {
        const u = urlSoleMatch[1];
        const rec = clasificarRecurso(u, '');
        if (rec.tipo === 'doc' || rec.tipo === 'slides' || rec.tipo === 'video') {
          cerrar();
          out.push(renderInline('[' + (rec.titulo || rec.etiqueta) + '](' + u + ')'));
          return;
        }
      }

      if (/^ruta\s*[:>]/i.test(l)) { cerrar(); out.push('<div class="ruta">' + renderInline(l) + '</div>'); return; }
      if (/^#{1,4}\s/.test(l)) { cerrar(); out.push('<h4>' + renderInline(l.replace(/^#+\s*/, '')) + '</h4>'); return; }
      if (/^>\s?/.test(l)) { cerrar(); out.push('<blockquote>' + renderInline(l.replace(/^>\s?/, '')) + '</blockquote>'); return; }
      if (/^\|/.test(l)) { cerrar(); out.push('<div class="tabla">' + renderInline(l) + '</div>'); return; }
      if (/^\d+[.)]\s/.test(l)) {
        if (lista !== 'ol') { cerrar(); out.push('<ol>'); lista = 'ol'; }
        out.push('<li>' + renderInline(l.replace(/^\d+[.)]\s*/, '')) + '</li>');
        return;
      }
      if (/^[-*]\s/.test(l)) {
        if (lista !== 'ul') { cerrar(); out.push('<ul>'); lista = 'ul'; }
        out.push('<li>' + renderInline(l.replace(/^[-*]\s*/, '')) + '</li>');
        return;
      }

      cerrar();
      out.push('<p>' + renderInline(l) + '</p>');
    });

    cerrar();
    return out.join('') || '<p class="vacio">Todavía no hay contenido.</p>';
  }

  /* =========================================================
     Selector Unicode simple de Emojis
     ========================================================= */
  function inicializarEmojiPicker() {
    const pop = $('#emojiPickerPopover');
    if (!pop) return;
    pop.innerHTML = EMOJIS_DISCOURSE.map((em) =>
      '<button type="button" class="emoji-option" role="option" data-emoji="' + em + '" aria-label="Emoji ' + em + '" title="Insertar ' + em + '">' + em + '</button>'
    ).join('');
  }

  function cerrarEmojiPicker() {
    const pop = $('#emojiPickerPopover');
    const btn = $('#btnEmojiToolbar');
    if (pop) pop.hidden = true;
    if (btn) btn.setAttribute('aria-expanded', 'false');
  }

  function insertarEmojiEnBloqueActivo(emoji) {
    const ta = obtenerTextareaObjetivo();
    if (!ta) return;
    const val = String(ta.value || '');
    const start = typeof ta.selectionStart === 'number' ? ta.selectionStart : val.length;
    const end = typeof ta.selectionEnd === 'number' ? ta.selectionEnd : start;
    ta.value = val.slice(0, start) + emoji + val.slice(end);
    const pos = start + emoji.length;
    if (typeof ta.focus === 'function') ta.focus();
    if (typeof ta.setSelectionRange === 'function') {
      try { ta.setSelectionRange(pos, pos); } catch (_) {}
    }
    ta.dispatchEvent(new Event('input', { bubbles: true }));
  }

  /* =========================================================
     Eventos Mini Panel Multimedia
     ========================================================= */
  function conectarEventosMultimedia() {
    const cont = $('#panelMultimedia');
    if (!cont) return;

    let arrastrandoIdx = null;

    cont.addEventListener('click', async (e) => {
      const btnCarga = e.target.closest('[data-accion="abrir-carga"]');
      if (btnCarga && !btnCarga.disabled) {
        e.preventDefault();
        const abierta = BACO.panelMultimedia.alternarCarga();
        BACO.panelMultimedia.pintar(cont, store.get());
        if (abierta) { const u = $('#pmUrl'); if (u) u.focus(); }
        return;
      }

      const btnQuitar = e.target.closest('[data-accion="quitar"]');
      if (btnQuitar && !btnQuitar.disabled) {
        e.preventDefault();
        const id = btnQuitar.getAttribute('data-id');
        if (!id) return;
        await eliminarBloque(id);
        return;
      }

      const btnMover = e.target.closest('[data-accion="subir"], [data-accion="bajar"]');
      if (btnMover && !btnMover.disabled) {
        e.preventDefault();
        const accion = btnMover.getAttribute('data-accion');
        const idx = parseInt(btnMover.getAttribute('data-idx'), 10);
        if (isNaN(idx)) return;
        const targetIdx = accion === 'subir' ? idx - 1 : idx + 1;
        try {
          store.set({ enviando: true });
          const res = await api.reordenarMultimedia(idx, targetIdx);
          aplicarEstadoRecursosServidor(res);
        } catch (err) {
          toast(err.message || 'No se pudo reordenar');
        } finally {
          store.set({ enviando: false });
        }
        return;
      }

      const btnUrl = e.target.closest('[data-accion="agregar-url"]');
      if (btnUrl && !btnUrl.disabled) {
        e.preventDefault();
        await agregarUrlMultimedia();
        return;
      }
    });

    async function agregarUrlMultimedia() {
      const inputUrl = $('#pmUrl');
      if (!inputUrl) return;
      const url = inputUrl.value.trim();
      if (!url) {
        toast('Ingresá una URL válida');
        return;
      }
      try {
        store.set({ enviando: true });
        const res = await api.agregarRecursoMultimedia({ referencia: url });
        inputUrl.value = '';
        aplicarEstadoRecursosServidor(res);
        toast('Recurso agregado');
      } catch (err) {
        toast(err.message || 'No se pudo agregar la URL');
      } finally {
        store.set({ enviando: false });
      }
    }

    cont.addEventListener('keydown', (e) => {
      if (e.target && e.target.id === 'pmUrl' && e.key === 'Enter') {
        e.preventDefault();
        agregarUrlMultimedia();
      }
    });

    cont.addEventListener('change', (e) => {
      if (e.target && e.target.id === 'pmArchivo') {
        const file = e.target.files && e.target.files[0];
        if (file) {
          e.target.value = '';
          validarYSubirArchivoIntercalado(file, { tieneFoco: false });
        }
      }
    });
  }

  /* =========================================================
     Eventos Principales y Barra de Herramientas
     ========================================================= */
  function conectarEventos() {
    const fTit = $('#fTitulo');
    if (fTit) fTit.addEventListener('input', (e) => store.setForm({ titulo: e.target.value }));
    const fCue = $('#fCuerpo');
    if (fCue) fCue.addEventListener('input', (e) => store.setForm({ texto: e.target.value }));
    function abrirDesplegable(sel) {
      if (!sel || sel.disabled) return;
      if (typeof sel.showPicker === 'function') {
        try {
          sel.showPicker();
          return;
        } catch (_) {}
      }
      sel.focus();
      sel.click();
    }

    const fCat = $('#fCategoria');
    if (fCat) {
      fCat.addEventListener('change', (e) => {
        actualizarColorCategoria(e.target);
        store.setForm({ categoria_id: parseInt(e.target.value, 10) || null });
      });
      fCat.addEventListener('input', (e) => actualizarColorCategoria(e.target));
      actualizarColorCategoria(fCat);
    }

    const btnFlechaCat = $('#btnFlechaCat');
    if (btnFlechaCat) {
      btnFlechaCat.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        abrirDesplegable($('#fCategoria'));
      });
    }

    const wrapCat = $('.selector-cat-wrap');
    if (wrapCat) {
      wrapCat.addEventListener('click', (e) => {
        if (e.target !== $('#fCategoria') && e.target !== btnFlechaCat) {
          abrirDesplegable($('#fCategoria'));
        }
      });
    }

    const fTagSel = $('#fTagsSelect');
    if (fTagSel) {
      fTagSel.addEventListener('change', (e) => {
        const val = e.target.value;
        if (!val) return;
        const s = store.get();
        if (s.form.tags.indexOf(val) === -1) {
          if (s.form.tags.length >= cfg.MAX_TAGS) {
            toast('Máximo ' + cfg.MAX_TAGS + ' etiquetas');
          } else {
            store.setForm({ tags: s.form.tags.concat([val]) });
          }
        }
        e.target.value = '';
      });
    }

    const btnFlechaTags = $('#btnFlechaTags');
    if (btnFlechaTags) {
      btnFlechaTags.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        abrirDesplegable($('#fTagsSelect'));
      });
    }

    if (fTit) {
      fTit.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          const s = store.get();
          if (s.flujo === 'ESPERANDO_TITULO') {
            const tit = s.form.titulo.trim();
            if (Array.from(tit).length >= cfg.MIN_TITULO && !s.enviando) {
              enviarTurno({ titulo: tit }, tit);
            }
          } else if ($('#btnPrincipal') && !$('#btnPrincipal').disabled) {
            enviarPrincipal();
          }
        }
      });
    }

    if (fCue) {
      fCue.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
          e.preventDefault();
          if ($('#btnPrincipal') && !$('#btnPrincipal').disabled) enviarPrincipal();
        }
      });
    }

    const tagIn = $('#tagInput');
    if (tagIn) {
      tagIn.addEventListener('keydown', (e) => {
        const s = store.get();
        if (e.key === 'Enter' || e.key === ',') {
          e.preventDefault();
          const v = e.target.value.trim().toLowerCase().replace(/\s+/g, '-');
          if (v && s.form.tags.indexOf(v) === -1) {
            if (s.form.tags.length >= cfg.MAX_TAGS) toast('Máximo ' + cfg.MAX_TAGS + ' etiquetas');
            else store.setForm({ tags: s.form.tags.concat([v]) });
          }
          e.target.value = '';
        } else if (e.key === 'Backspace' && !e.target.value && s.form.tags.length) {
          store.setForm({ tags: s.form.tags.slice(0, -1) });
        }
      });
    }
    const tagBx = $('#tagBox');
    if (tagBx) tagBx.addEventListener('click', (e) => { if (e.target === e.currentTarget && tagIn && !tagIn.disabled) tagIn.focus(); });

    if ($('#btnPrincipal')) $('#btnPrincipal').onclick = enviarPrincipal;

    /* Barra de herramientas estilo Discourse: botones Markdown, Emoji, Imagen y navegación por teclado */
    const toolbar = $('#editorToolbar');
    if (toolbar) {
      toolbar.addEventListener('click', (e) => {
        const btnMd = e.target.closest('[data-md]');
        if (btnMd && !btnMd.disabled) {
          e.preventDefault();
          const tipoMd = btnMd.getAttribute('data-md');
          const ta = obtenerTextareaObjetivo();
          if (ta) {
            insertarFormatoMarkdown(ta, tipoMd);
          }
          return;
        }

        const btnEmojiOpt = e.target.closest('.emoji-option');
        if (btnEmojiOpt) {
          e.preventDefault();
          e.stopPropagation();
          const emoji = btnEmojiOpt.getAttribute('data-emoji');
          if (emoji) insertarEmojiEnBloqueActivo(emoji);
          cerrarEmojiPicker();
          return;
        }
      });

      toolbar.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
          cerrarEmojiPicker();
          const btnEm = $('#btnEmojiToolbar');
          if (btnEm) btnEm.focus();
          return;
        }
        if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
          const botones = Array.from(toolbar.querySelectorAll('button:not(:disabled)')).filter((b) => !b.closest('[hidden]'));
          const idx = botones.indexOf(document.activeElement);
          if (idx !== -1) {
            e.preventDefault();
            const next = e.key === 'ArrowRight'
              ? botones[(idx + 1) % botones.length]
              : botones[(idx - 1 + botones.length) % botones.length];
            if (next) next.focus();
          }
        }
      });
    }

    const btnEmoji = $('#btnEmojiToolbar');
    if (btnEmoji) {
      btnEmoji.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (btnEmoji.disabled) return;
        const pop = $('#emojiPickerPopover');
        if (!pop) return;
        const abrir = pop.hidden;
        pop.hidden = !abrir;
        btnEmoji.setAttribute('aria-expanded', String(abrir));
        if (abrir) {
          const firstOpt = pop.querySelector('.emoji-option');
          if (firstOpt) firstOpt.focus();
        }
      });
    }

    const btnImgToolbar = $('#btnImagenToolbar');
    if (btnImgToolbar) {
      // Capturamos el cursor del bloque activo en mousedown antes de que el clic mueva el foco al botón
      btnImgToolbar.addEventListener('mousedown', () => {
        ultimoCursorCapturado = capturarCursorActualParaImagen();
      });
      btnImgToolbar.addEventListener('click', async (e) => {
        e.preventDefault();
        if (btnImgToolbar.disabled) return;

        const st = store.get();
        const esEnriq = Boolean(st && st.borrador && st.borrador.modo === 'enriquecimiento');
        const previewActiva = esVistaPreviaActiva();

        if (esEnriq && previewActiva) {
          const url = window.prompt('Ingresá la URL de la imagen (http/https):');
          if (!url || !url.trim()) return;
          const urlLimpia = url.trim();

          btnImgToolbar.disabled = true;
          try {
            const res = await api.agregarRecursoMultimedia({
              referencia: urlLimpia,
              tipo: 'imagen'
            });
            btnImgToolbar.disabled = false;
            aplicarEstadoRecursosServidor(res);
            toast('Imagen agregada al borrador');
          } catch (err) {
            btnImgToolbar.disabled = false;
            toast('Error al agregar imagen: ' + (err.message || 'Error'));
          }
          return;
        }

        if (!ultimoCursorCapturado) {
          ultimoCursorCapturado = capturarCursorActualParaImagen();
        }
        abrirSelectorImagenToolbar();
      });
    }

    /* Eventos del contenedor de bloques intercalados (Texto / Recurso / Texto) */
    const contBloques = $('#contenedorBloques');
    let recursoArrastradoId = null;

    if (contBloques) {
      contBloques.addEventListener('focusin', (e) => {
        if (e.target && e.target.classList && e.target.classList.contains('bloque-textarea')) {
          ultimoTextareaActivo = e.target;
        }
      });

      contBloques.addEventListener('click', (e) => {
        const targetAccion = e.target.closest('[data-accion]');
        if (!targetAccion || targetAccion.disabled) return;

        const accion = targetAccion.getAttribute('data-accion');
        const id = targetAccion.getAttribute('data-id');

        if (accion === 'eliminar-bloque') {
          e.stopPropagation();
          eliminarBloque(id);
        } else if (accion === 'subir-bloque') {
          e.stopPropagation();
          moverBloque(id, 'subir');
        } else if (accion === 'bajar-bloque') {
          e.stopPropagation();
          moverBloque(id, 'bajar');
        }
      });

      contBloques.addEventListener('input', (e) => {
        if (e.target && e.target.classList.contains('bloque-textarea')) {
          ultimoTextareaActivo = e.target;
          const idx = parseInt(e.target.getAttribute('data-bloque-idx'), 10);
          if (!isNaN(idx) && idx >= 0 && idx < estadoEditor.bloques_texto.length) {
            estadoEditor.bloques_texto[idx] = e.target.value;
          }
          const b = estadoEditor.bloques.find((x) => x.id === e.target.getAttribute('data-id'));
          if (b) b.contenido = e.target.value;
          sincronizarTextoConStore();
        }
      });

      contBloques.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
          e.preventDefault();
          if ($('#btnPrincipal') && !$('#btnPrincipal').disabled) enviarPrincipal();
        }
      });

      // Drag & Drop de recursos intercalados
      contBloques.addEventListener('dragstart', (e) => {
        const item = e.target.closest('.bloque-recurso-item');
        if (!item || item.getAttribute('draggable') !== 'true') return;
        recursoArrastradoId = item.getAttribute('data-recurso-id');
        if (e.dataTransfer) {
          e.dataTransfer.effectAllowed = 'move';
          e.dataTransfer.setData('text/plain', String(recursoArrastradoId));
        }
        item.classList.add('arrastrando');
      });

      contBloques.addEventListener('dragover', (e) => {
        if (!recursoArrastradoId) return;
        const destRec = e.target.closest('.bloque-recurso-item');
        const destTxt = e.target.closest('.bloque-texto-item');
        if (destRec || destTxt) {
          e.preventDefault();
          if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
          if (destRec) destRec.classList.add('destino');
        }
      });

      contBloques.addEventListener('dragleave', (e) => {
        const destRec = e.target.closest('.bloque-recurso-item');
        if (destRec) destRec.classList.remove('destino');
      });

      contBloques.addEventListener('dragend', () => {
        contBloques.querySelectorAll('.bloque-recurso-item.arrastrando, .bloque-recurso-item.destino').forEach((n) => {
          n.classList.remove('arrastrando', 'destino');
        });
        recursoArrastradoId = null;
      });

      contBloques.addEventListener('drop', (e) => {
        if (!recursoArrastradoId) return;
        const idOrigen = recursoArrastradoId;
        recursoArrastradoId = null;
        contBloques.querySelectorAll('.bloque-recurso-item.destino').forEach((n) => n.classList.remove('destino'));

        const destRec = e.target.closest('.bloque-recurso-item');
        if (destRec) {
          e.preventDefault();
          const idDest = destRec.getAttribute('data-recurso-id');
          if (idDest && idDest !== idOrigen) {
            const nuevaPos = parseInt(destRec.getAttribute('data-posicion'), 10);
            const nuevoOrd = parseInt(destRec.getAttribute('data-orden'), 10);
            reordenarRecursoHaciaDestino(idOrigen, isNaN(nuevaPos) ? 0 : nuevaPos, isNaN(nuevoOrd) ? 0 : nuevoOrd);
          }
          return;
        }

        const destTxt = e.target.closest('.bloque-texto-item');
        if (destTxt) {
          e.preventDefault();
          const bloqueIdx = parseInt(destTxt.getAttribute('data-bloque-idx'), 10);
          if (!isNaN(bloqueIdx)) {
            reordenarRecursoHaciaDestino(idOrigen, bloqueIdx, estadoEditor.recursos.length);
          }
        }
      });
    }

    document.addEventListener('click', (e) => {
      if (!e.target.closest('.ed-emoji-wrap')) {
        cerrarEmojiPicker();
      }
    });

    const inputSelector = $('#inputSelectorBloque');
    if (inputSelector) {
      inputSelector.addEventListener('change', (e) => {
        const f = e.target.files && e.target.files[0];
        const cursorInfo = ultimoCursorCapturado || capturarCursorActualParaImagen();
        ultimoCursorCapturado = null;
        if (f) {
          validarYSubirArchivoIntercalado(f, cursorInfo);
        }
        e.target.value = '';
      });
    }

    const btnConfBloques = $('#btnConfirmarBloques');
    if (btnConfBloques) {
      btnConfBloques.onclick = confirmarBloques;
    }

    if ($('#btnConfirmarTexto')) {
      $('#btnConfirmarTexto').onclick = confirmarTexto;
    }

    /* Alternar Markdown / Vista previa reutilizando #btnEditor y #btnPreview */
    if ($('#btnEditor')) {
      $('#btnEditor').onclick = () => {
        sincronizarTextoDesdePreview();
        const wrapper = $('#editorBloquesWrapper');
        if (wrapper) wrapper.hidden = false;
        const fc = $('#fCuerpo');
        if (fc) fc.hidden = true;
        const pr = $('#preview');
        if (pr) pr.hidden = true;
        $('#btnEditor').classList.add('sel');
        $('#btnEditor').setAttribute('aria-pressed', 'true');
        if ($('#btnPreview')) {
          $('#btnPreview').classList.remove('sel');
          $('#btnPreview').setAttribute('aria-pressed', 'false');
        }
        estadoEditor.modo = 'edicion';
        renderBloques();
        pintar(store.get());
        const ta = obtenerTextareaObjetivo();
        if (ta) ta.focus();
      };
    }
    if ($('#btnPreview')) {
      $('#btnPreview').onclick = () => {
        const st = store.get();
        const esEnriq = Boolean(st && st.borrador && st.borrador.modo === 'enriquecimiento');
        if (!esEnriq) {
          sincronizarTextoConStore();
        }
        const wrapper = $('#editorBloquesWrapper');
        if (wrapper) wrapper.hidden = true;
        const fc = $('#fCuerpo');
        if (fc) fc.hidden = true;
        let pr = $('#preview');
        if (!pr && $('#campoTexto')) {
          pr = el('div', 'preview');
          pr.id = 'preview';
          $('#campoTexto').appendChild(pr);
        }
        renderVistaPreviaEditable();
        conectarEventosVistaPrevia();
        if (pr) {
          pr.hidden = false;
        }
        $('#btnPreview').classList.add('sel');
        $('#btnPreview').setAttribute('aria-pressed', 'true');
        if ($('#btnEditor')) {
          $('#btnEditor').classList.remove('sel');
          $('#btnEditor').setAttribute('aria-pressed', 'false');
        }
        estadoEditor.modo = 'preview';
        const bar = $('#editorImgBar'); if (bar) bar.hidden = true;
        const pm = $('#panelMultimedia'); if (pm) { pm.hidden = true; pm.innerHTML = ''; }
      };
    }

    if ($('#btnSubir')) $('#btnSubir').onclick = () => { if ($('#fileInput')) $('#fileInput').click(); };
    if ($('#fileInput')) {
      $('#fileInput').addEventListener('change', (e) => {
        const f = e.target.files[0];
        if (!f) return;
        e.target.value = '';
        if (!/\.(txt|md)$/i.test(f.name)) {
          toast('Por ahora solo .txt y .md: el backend todavía no extrae PDF ni Word');
          return;
        }
        const lector = new FileReader();
        lector.onload = () => {
          const contenidoArchivo = String(lector.result || '');
          const lastIdx = Math.max(0, estadoEditor.bloques_texto.length - 1);
          const actual = String(estadoEditor.bloques_texto[lastIdx] || '').trim();
          estadoEditor.bloques_texto[lastIdx] = actual ? (actual + '\n\n' + contenidoArchivo) : contenidoArchivo;
          sincronizarTextoConStore();
          renderBloques();
          toast('Documento volcado en el editor');
          confirmarBloques();
        };
        lector.readAsText(f);
      });
    }

    if ($('#btnPlantilla')) $('#btnPlantilla').onclick = aplicarPlantilla;
    if ($('#btnAuditar')) $('#btnAuditar').onclick = auditar;

    if ($('#btnReiniciar')) $('#btnReiniciar').onclick = () => accionar('reiniciar', 'Empezar de nuevo');
    if ($('#btnEjemplo')) $('#btnEjemplo').onclick = cargarEjemplo;

    if ($('#btnCerrar')) $('#btnCerrar').onclick = () => { if ($('#overlay')) $('#overlay').hidden = true; };
    if ($('#btnCopiarBorrador')) $('#btnCopiarBorrador').onclick = copiarBorrador;
    if ($('#btnOtra')) $('#btnOtra').onclick = () => { if ($('#overlay')) $('#overlay').hidden = true; accionar('reiniciar', 'Empezar de nuevo'); };

    if ($('#swError')) {
      $('#swError').addEventListener('change', (e) => {
        cfg.mock.TASA_ERROR = e.target.checked ? 0.35 : 0;
        toast(e.target.checked ? 'Fallas simuladas activadas' : 'Fallas simuladas desactivadas');
      });
    }

    if ($('#btnSend')) $('#btnSend').onclick = enviarChatLibre;
    if ($('#chatInput')) {
      $('#chatInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviarChatLibre(); }
      });
      $('#chatInput').addEventListener('input', (e) => {
        e.target.style.height = 'auto';
        e.target.style.height = Math.min(110, e.target.scrollHeight) + 'px';
        const s = store.get();
        if (s.flujo === 'ESPERANDO_TEXTO') {
          contadorTexto($('#chatInputCont'), $('#chatInputAvisoMax'), Array.from(e.target.value || '').length, cfg.MIN_TEXTO, cfg.MAX_TEXTO_PERCENTIL_99);
        }
      });
    }
  }

  function cargarEjemplo() {
    const s = store.get();
    if (s.flujo === 'ESPERANDO_TITULO') {
      const t = BACO.datos.ejemplo.titulo;
      if ($('#fTitulo')) $('#fTitulo').value = t;
      store.setForm({ titulo: t });
      toast('Título de ejemplo cargado');
    } else if (s.flujo === 'ESPERANDO_TEXTO') {
      const c = BACO.datos.ejemplo.cuerpo;
      const fc = $('#fCuerpo');
      if (fc) fc.value = c;
      store.setForm({ texto: c });
      estadoEditor.bloques_texto = [c];
      renderBloques();
      toast('Contenido de ejemplo cargado en el editor. Tocá "Confirmar texto" cuando estés listo.');
    } else {
      toast('El ejemplo se carga en los pasos de título y contenido');
    }
  }

  iniciar();
})();
