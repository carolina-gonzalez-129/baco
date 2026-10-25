/* =============================================================
   BACO — Interfaz
   -------------------------------------------------------------
   El backend conduce el flujo: cada turno devuelve `estado`,
   `etapa`, `tags_acumulados`, `categorias_disponibles` y
   `opciones`, y el panel se acomoda a eso.

   · Derecha (chat) = el hilo de la conversación y los botones
     que el backend habilita en cada paso.
   · Izquierda (formulario) = espejo editable del borrador.

   Esta capa no sabe si detrás hay mock o backend real.
   ============================================================= */
(function () {
  'use strict';

  const api = BACO.api;
  const store = BACO.store;
  const cfg = BACO.config;

  const $ = (s) => document.querySelector(s);
  const el = (t, c, h) => { const n = document.createElement(t); if (c) n.className = c; if (h != null) n.innerHTML = h; return n; };
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const hora = () => new Date().toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
  function clasificarRecurso(url, altOrText, isExplicitImg, isAttachment) {
    const u = String(url || '').toLowerCase();
    const t = String(altOrText || '').toLowerCase();

    if (isExplicitImg || /\.(png|jpe?g|gif|webp|svg)(\?.*)?$/i.test(u)) {
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
    txt = txt.replace(/!\[([^\]]*)\]\((https?:\/\/[^\s\)]+)\)/g, '<div class="preview-img-box"><img src="$2" alt="$1" class="preview-img" loading="lazy" referrerpolicy="no-referrer" /><span class="caption">$1</span></div>');
    txt = txt.replace(/\[([^\]]+)\|attachment\]\((https?:\/\/[^\s\)]+)\)/g, '<a class="preview-adjunto" href="$2" target="_blank" rel="noopener">📎 $1</a>');
    txt = txt.replace(/\[([^\]]+)\]\((https?:\/\/[^\s\)]+)\)/g, (match, title, url) => {
      const rec = clasificarRecurso(url, title, false, false);
      return '<a class="chat-link" href="' + url + '" target="_blank" rel="noopener">' + rec.icono + ' ' + title + ' ↗</a>';
    });
    return txt.replace(/\n/g, '<br>');
  };
  let tToast = null;
  let ultimoFallo = null;   // para poder reintentar la llamada que falló

  /* =========================================================
     Editor de Bloques (Vanilla JS, Estado Único)
     ========================================================= */
  const MAX_ARCHIVO_BYTES = 10 * 1024 * 1024; // 10 MB
  const MAX_TOTAL_RECURSOS_BYTES = 50 * 1024 * 1024; // 50 MB
  let bloqueSeq = 1;
  const genId = () => 'b_' + Date.now() + '_' + (bloqueSeq++);

  const estadoEditor = {
    bloques: [
      { id: genId(), tipo: 'texto', contenido: '' }
    ],
    modo: 'edicion',
    enviando: false,
    menuAbiertoPos: null
  };

  let sesionCargadaId = null;
  let selectorTargetPos = null;
  let selectorTargetTipo = null;
  const textareasMap = new Map();

  function formatearBytes(bytes) {
    if (bytes == null || isNaN(bytes)) return '';
    if (bytes < 1024) return bytes + ' B';
    const kb = bytes / 1024;
    if (kb < 1024) return kb.toFixed(1) + ' KB';
    const mb = kb / 1024;
    return mb.toFixed(1) + ' MB';
  }

  function calcularTamanioTotalRecursos() {
    return estadoEditor.bloques.reduce((acc, b) => {
      if (b.tipo === 'recurso' && b.recurso && typeof b.recurso.tamanio === 'number') {
        return acc + b.recurso.tamanio;
      }
      return acc;
    }, 0);
  }

  function componerTextoDesdeBloques() {
    const partes = [];
    estadoEditor.bloques.forEach((b) => {
      if (b.tipo === 'texto') {
        const cont = (b.contenido || '').trim();
        if (cont) partes.push(cont);
      } else if (b.tipo === 'recurso' && b.recurso) {
        const r = b.recurso;
        const ref = r.url || r.referencia || '';
        const nom = r.nombre || 'Recurso';
        if (r.tipo === 'imagen') {
          partes.push('![' + nom + '](' + ref + ')');
        } else if (r.tipo === 'documento' || r.tipo === 'archivo') {
          partes.push('[' + nom + '|attachment](' + ref + ')');
        } else {
          partes.push('[' + nom + '](' + ref + ')');
        }
      }
    });
    return partes.join('\n\n');
  }

  function sincronizarTextoConStore() {
    const compuesto = componerTextoDesdeBloques();
    store.setForm({ texto: compuesto });
    const fc = $('#fCuerpo');
    if (fc) fc.value = compuesto;
  }

  function crearDivisor(pos, deshabilitado) {
    const div = document.createElement('div');
    div.className = 'bloque-divider';

    const line = document.createElement('div');
    line.className = 'bloque-divider-line';
    div.appendChild(line);

    const btnPlus = document.createElement('button');
    btnPlus.type = 'button';
    btnPlus.className = 'btn-agregar-bloque';
    btnPlus.textContent = '+';
    btnPlus.setAttribute('data-accion', 'toggle-menu');
    btnPlus.setAttribute('data-pos', String(pos));
    btnPlus.title = 'Agregar multimedia';
    if (deshabilitado) btnPlus.disabled = true;
    div.appendChild(btnPlus);

    if (estadoEditor.menuAbiertoPos === pos && !deshabilitado) {
      const menu = document.createElement('div');
      menu.className = 'menu-agregar-bloque';

      const opciones = [
        { tipo: 'imagen', icono: '🖼️', etiqueta: 'Imagen' },
        { tipo: 'video', icono: '🎬', etiqueta: 'Video' },
        { tipo: 'archivo', icono: '📎', etiqueta: 'Archivo' }
      ];

      opciones.forEach((opt) => {
        const btnOpt = document.createElement('button');
        btnOpt.type = 'button';
        btnOpt.className = 'menu-opcion-btn';
        btnOpt.setAttribute('data-accion', 'abrir-selector');
        btnOpt.setAttribute('data-tipo', opt.tipo);
        btnOpt.setAttribute('data-pos', String(pos));

        const spanIco = document.createElement('span');
        spanIco.textContent = opt.icono;
        btnOpt.appendChild(spanIco);

        const spanTxt = document.createElement('span');
        spanTxt.textContent = opt.etiqueta;
        btnOpt.appendChild(spanTxt);

        menu.appendChild(btnOpt);
      });

      div.appendChild(menu);
    }

    return div;
  }

  function crearItemTexto(b, deshabilitado) {
    const item = document.createElement('div');
    item.className = 'bloque-texto-item';
    item.setAttribute('data-id', b.id);

    let textarea = textareasMap.get(b.id);
    if (!textarea) {
      textarea = document.createElement('textarea');
      textarea.className = 'bloque-textarea';
      textarea.setAttribute('data-id', b.id);
      textarea.placeholder = 'Escribí el texto acá en formato Markdown...';
      textareasMap.set(b.id, textarea);
    }
    textarea.disabled = deshabilitado;
    if (document.activeElement !== textarea && textarea.value !== (b.contenido || '')) {
      textarea.value = b.contenido || '';
    }

    item.appendChild(textarea);
    return item;
  }

  function crearItemRecurso(b, idx, total, deshabilitado) {
    const item = document.createElement('div');
    item.className = 'bloque-recurso-item' + (b.cargando ? ' cargando' : '');
    item.setAttribute('data-id', b.id);

    // 1. Botón 'x' a la izquierda para eliminar
    const btnX = document.createElement('button');
    btnX.type = 'button';
    btnX.className = 'bloque-eliminar-btn';
    btnX.textContent = '×';
    btnX.setAttribute('data-accion', 'eliminar-bloque');
    btnX.setAttribute('data-id', b.id);
    btnX.title = 'Eliminar recurso';
    if (b.cargando || deshabilitado) btnX.disabled = true;
    item.appendChild(btnX);

    // 2. Icono o miniatura
    const r = b.recurso || {};
    const tipo = r.tipo || 'otro';
    const url = b.previewUrl || r.url || r.referencia || '';

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
      ico.textContent = tipo === 'video' ? '🎬' : (tipo === 'documento' || tipo === 'archivo' ? '📄' : '📎');
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
      const tamLabel = r.tamanio ? ' · ' + formatearBytes(r.tamanio) : '';
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
    btnSubir.setAttribute('data-id', b.id);
    btnSubir.title = 'Subir';
    if (idx === 0 || b.cargando || deshabilitado) btnSubir.disabled = true;
    mover.appendChild(btnSubir);

    const btnBajar = document.createElement('button');
    btnBajar.type = 'button';
    btnBajar.className = 'bloque-btn-mover';
    btnBajar.textContent = '↓';
    btnBajar.setAttribute('data-accion', 'bajar-bloque');
    btnBajar.setAttribute('data-id', b.id);
    btnBajar.title = 'Bajar';
    if (idx === total - 1 || b.cargando || deshabilitado) btnBajar.disabled = true;
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

    const frag = document.createDocumentFragment();
    const total = estadoEditor.bloques.length;

    // Limpiar map de textareas para bloques eliminados
    const idsValidos = new Set(estadoEditor.bloques.map((b) => b.id));
    for (const id of textareasMap.keys()) {
      if (!idsValidos.has(id)) textareasMap.delete(id);
    }

    // Divisor inicial (posición 0)
    frag.appendChild(crearDivisor(0, deshabilitado));

    estadoEditor.bloques.forEach((b, idx) => {
      if (b.tipo === 'texto') {
        frag.appendChild(crearItemTexto(b, deshabilitado));
      } else if (b.tipo === 'recurso') {
        frag.appendChild(crearItemRecurso(b, idx, total, deshabilitado));
      }
      // Divisor posterior (posición idx + 1)
      frag.appendChild(crearDivisor(idx + 1, deshabilitado));
    });

    cont.replaceChildren(frag);

    // Botón Confirmar siempre visible, deshabilitado mientras espera
    const btnConfirmar = $('#btnConfirmarBloques');
    if (btnConfirmar) {
      btnConfirmar.disabled = deshabilitado;
      btnConfirmar.textContent = estadoEditor.enviando ? 'Confirmando…' : 'Confirmar';
    }
  }

  function insertarBloqueRecurso(nuevoBloque, pos) {
    if (pos == null || pos < 0 || pos > estadoEditor.bloques.length) {
      pos = estadoEditor.bloques.length;
    }
    estadoEditor.bloques.splice(pos, 0, nuevoBloque);

    if (pos + 1 >= estadoEditor.bloques.length || estadoEditor.bloques[pos + 1].tipo !== 'texto') {
      estadoEditor.bloques.splice(pos + 1, 0, { id: genId(), tipo: 'texto', contenido: '' });
    }
    if (pos === 0 || estadoEditor.bloques[pos - 1].tipo !== 'texto') {
      estadoEditor.bloques.splice(pos, 0, { id: genId(), tipo: 'texto', contenido: '' });
    }
  }

  function eliminarBloque(id) {
    const idx = estadoEditor.bloques.findIndex((b) => b.id === id);
    if (idx === -1) return;
    const b = estadoEditor.bloques[idx];
    if (b.previewUrl) {
      URL.revokeObjectURL(b.previewUrl);
    }
    estadoEditor.bloques.splice(idx, 1);

    if (!estadoEditor.bloques.length) {
      estadoEditor.bloques.push({ id: genId(), tipo: 'texto', contenido: '' });
    }
    renderBloques();
    sincronizarTextoConStore();
  }

  function moverBloque(id, direccion) {
    const idx = estadoEditor.bloques.findIndex((b) => b.id === id);
    if (idx === -1) return;
    const targetIdx = direccion === 'subir' ? idx - 1 : idx + 1;
    if (targetIdx < 0 || targetIdx >= estadoEditor.bloques.length) return;

    const temp = estadoEditor.bloques[idx];
    estadoEditor.bloques[idx] = estadoEditor.bloques[targetIdx];
    estadoEditor.bloques[targetIdx] = temp;

    renderBloques();
    sincronizarTextoConStore();
  }

  function abrirSelectorParaTipo(tipo, pos) {
    const input = $('#inputSelectorBloque');
    if (!input) return;
    selectorTargetTipo = tipo;
    selectorTargetPos = pos;

    if (tipo === 'imagen') {
      input.accept = 'image/png,image/jpeg,image/webp,image/gif';
    } else if (tipo === 'video') {
      input.accept = 'video/mp4,video/webm,video/ogg';
    } else if (tipo === 'archivo') {
      input.accept = '.pdf,.doc,.docx,.odt,.txt,.xlsx,.pptx,.zip';
    } else {
      input.accept = '*/*';
    }

    input.value = '';
    input.click();
  }

  function validarYSubirArchivo(file, tipoMenu, pos) {
    if (!file) return;

    const nombre = (file.name || '').toLowerCase();
    const mime = (file.type || '').toLowerCase();
    if (nombre.endsWith('.svg') || mime === 'image/svg+xml') {
      toast('No se permiten archivos SVG por motivos de seguridad.');
      return;
    }

    if (file.size > MAX_ARCHIVO_BYTES) {
      toast('El archivo supera el tamaño máximo permitido de 10 MB.');
      return;
    }

    const totalActual = calcularTamanioTotalRecursos();
    if (totalActual + file.size > MAX_TOTAL_RECURSOS_BYTES) {
      toast('El tamaño acumulado de los recursos superaría el límite de 50 MB.');
      return;
    }

    let tipoRecurso = 'otro';
    if (tipoMenu === 'imagen' || mime.startsWith('image/')) {
      tipoRecurso = 'imagen';
    } else if (tipoMenu === 'video' || mime.startsWith('video/')) {
      tipoRecurso = 'video';
    } else if (tipoMenu === 'archivo' || mime.startsWith('application/') || mime.startsWith('text/')) {
      tipoRecurso = 'documento';
    }

    const previewUrl = URL.createObjectURL(file);
    const bloqueId = genId();
    const nuevoBloque = {
      id: bloqueId,
      tipo: 'recurso',
      cargando: true,
      previewUrl: previewUrl,
      recurso: {
        id: bloqueId,
        tipo: tipoRecurso,
        nombre: file.name,
        url: previewUrl,
        tamanio: file.size,
        mime: file.type
      }
    };

    insertarBloqueRecurso(nuevoBloque, pos);
    renderBloques();

    subirArchivoRecurso(file, bloqueId, previewUrl);
  }

  async function subirArchivoRecurso(file, bloqueId, previewUrl) {
    try {
      let res = null;
      if (typeof api.subirRecursoMultimedia === 'function') {
        res = await api.subirRecursoMultimedia(file);
      }
      const b = estadoEditor.bloques.find((x) => x.id === bloqueId);
      if (!b) {
        URL.revokeObjectURL(previewUrl);
        return;
      }
      b.cargando = false;
      if (res && (res.referencia || res.url)) {
        b.recurso.url = res.referencia || res.url;
        if (res.id) b.recurso.id = res.id;
      }
      toast('Recurso subido correctamente');
      renderBloques();
      sincronizarTextoConStore();
    } catch (err) {
      URL.revokeObjectURL(previewUrl);
      const idx = estadoEditor.bloques.findIndex((x) => x.id === bloqueId);
      if (idx !== -1) estadoEditor.bloques.splice(idx, 1);
      toast('Error al subir: ' + (err.message || 'Error'));
      renderBloques();
    }
  }

  async function confirmarBloques() {
    if (estadoEditor.enviando) return;
    const s = store.get();
    if (s.enviando) return;

    const subiendo = estadoEditor.bloques.some((b) => b.cargando);
    if (subiendo) {
      toast('Esperá a que terminen de subirse los archivos');
      return;
    }

    const payloadBloques = [];
    estadoEditor.bloques.forEach((b) => {
      if (b.tipo === 'texto') {
        payloadBloques.push({
          tipo: 'texto',
          contenido: b.contenido || ''
        });
      } else if (b.tipo === 'recurso' && b.recurso) {
        payloadBloques.push({
          tipo: 'recurso',
          recurso: {
            url: b.recurso.url || b.recurso.referencia || '',
            nombre: b.recurso.nombre || '',
            tipo: b.recurso.tipo || 'otro'
          }
        });
      }
    });

    estadoEditor.enviando = true;
    renderBloques();

    try {
      const res = await api.confirmarBloques(payloadBloques);
      estadoEditor.enviando = false;

      if (res) {
        if (res.texto_limpio != null) {
          store.setForm({ texto: res.texto_limpio });
          const fc = $('#fCuerpo');
          if (fc) fc.value = res.texto_limpio;
        }
        if (res.borrador) {
          store.set({ borrador: res.borrador });
        } else if (res.recursos) {
          store.actualizarRecursos(res.recursos);
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
    if (sesionCambio) {
      sesionCargadaId = s.session_id;
      estadoEditor.bloques.forEach((b) => {
        if (b.previewUrl) URL.revokeObjectURL(b.previewUrl);
      });
      textareasMap.clear();

      const textoLimpio = (s.borrador && s.borrador.texto_limpio) || (s.form && s.form.texto) || '';
      const recs = (s.borrador && (Array.isArray(s.borrador.multimedia) ? s.borrador.multimedia : Object.values(s.borrador.recursos || {}))) || [];

      if (textoLimpio && /\[\[R\d+\]\]/.test(textoLimpio)) {
        const partes = textoLimpio.split(/(\[\[R\d+\]\])/g);
        const nuevosBloques = [];
        partes.forEach((p) => {
          const match = p.match(/^\[\[R(\d+)\]\]$/);
          if (match) {
            const num = parseInt(match[1], 10);
            const r = recs[num - 1] || { id: 'rec_' + num, nombre: 'Recurso ' + num, tipo: 'otro', url: '' };
            nuevosBloques.push({
              id: genId(),
              tipo: 'recurso',
              cargando: false,
              recurso: {
                id: r.id || ('rec_' + num),
                tipo: r.tipo || 'otro',
                nombre: r.nombre || ('Recurso ' + num),
                url: r.referencia || r.url || ''
              }
            });
          } else {
            nuevosBloques.push({
              id: genId(),
              tipo: 'texto',
              contenido: p
            });
          }
        });
        estadoEditor.bloques = nuevosBloques.length ? nuevosBloques : [{ id: genId(), tipo: 'texto', contenido: '' }];
      } else if (textoLimpio) {
        const nuevosBloques = [{ id: genId(), tipo: 'texto', contenido: textoLimpio }];
        recs.forEach((r, i) => {
          nuevosBloques.push({
            id: genId(),
            tipo: 'recurso',
            cargando: false,
            recurso: {
              id: r.id || ('rec_' + (i + 1)),
              tipo: r.tipo || 'otro',
              nombre: r.nombre || ('Recurso ' + (i + 1)),
              url: r.referencia || r.url || ''
            }
          });
          nuevosBloques.push({ id: genId(), tipo: 'texto', contenido: '' });
        });
        estadoEditor.bloques = nuevosBloques;
      } else {
        estadoEditor.bloques = [{ id: genId(), tipo: 'texto', contenido: '' }];
      }
      renderBloques();
    } else {
      const editorVacio = estadoEditor.bloques.length === 1 &&
        estadoEditor.bloques[0].tipo === 'texto' &&
        !estadoEditor.bloques[0].contenido.trim();
      const textoLimpio = s.borrador && s.borrador.texto_limpio;

      if (editorVacio && textoLimpio) {
        sesionCargadaId = null;
        sincronizarBloquesDesdeStore(s);
      }
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

    conectarEventos();
    store.suscribir(pintar);
    await enviarTurno({});     // primer turno: trae la bienvenida
  }

  /* =========================================================
     Un turno contra el backend
     ========================================================= */
  async function enviarTurno(payload, etiquetaUsuario) {
    const cuerpo = Object.assign({}, payload);   // la sesión la maneja la capa de API

    if (etiquetaUsuario) burbuja('me', esc(etiquetaUsuario));
    const htmlEspera = (cuerpo && cuerpo.accion === 'confirmar_texto')
      ? '<div class="typing-wrap"><div class="typing"><i></i><i></i><i></i></div><span class="typing-lbl">Baco está buscando…</span></div>'
      : '<div class="typing"><i></i><i></i><i></i></div>';
    const esperando = burbuja('bot', htmlEspera);
    store.set({ enviando: true, error: null });

    try {
      const r = await api.turno(cuerpo);
      esperando.remove();
      ultimoFallo = null;
      store.aplicarTurno(r);
      store.set({ enviando: false });

      /* El backend avisa cuando anonimizó datos sensibles solo */
      if (r.aviso_privacidad) mostrarAviso(r.aviso_privacidad);

      decir(nl2br(r.mensaje), r.opciones);

      if (r.estado === 'CONFORMIDAD_USUARIO' || r.estado === 'APROBADO') mostrarConforme();
    } catch (e) {
      esperando.remove();
      store.set({ enviando: false });
      /* Se guarda el pedido para poder repetirlo sin rehacer el paso */
      ultimoFallo = { tipo: 'turno', payload: payload };
      mostrarError(e);
      decir('No pude completar el paso: ' + esc(e.message));
    }
  }

  function nombreCategoria(s, catId) {
    const idNum = Number(catId);
    if (!idNum || idNum <= 1) return 'Sin categoría';
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
    pill.textContent = info.etiqueta;
    pill.className = 'pill ' + info.tono;
    $('#ayudaEstado').textContent = info.ayuda;

    const pct = BACO.avance(s);
    $('#meterFill').style.width = pct + '%';
    $('#meterFill').classList.toggle('full', s.flujo === 'CONFORMIDAD_USUARIO' || s.flujo === 'APROBADO');
    $('#meterPct').textContent = 'Etapa ' + etapaActual + ' de ' + etapaTotal;

    $('#sesion').textContent = s.session_id ? 'sesión ' + s.session_id.slice(0, 8) : '';

    /* Stepper dinámico dictado por s.etapa */
    pintarStepper(s, etapaActual);
    pintarTagsAcumuladosRail(s);

    /* campos activos según el estado */
    const act = BACO.CAMPOS_ACTIVOS[s.flujo] || {};
    $('#fTitulo').disabled = !act.titulo || s.enviando;
    $('#fCuerpo').disabled = !act.texto || s.enviando;
    $('#tagInput').disabled = !act.tags || s.enviando;
    $('#fCategoria').disabled = !act.categoria || s.enviando;
    $('#campoTitulo').classList.toggle('activo', !!act.titulo);
    $('#campoTexto').classList.toggle('activo', !!act.texto);

    /* Visibilidad y activación de campoTags:
       - No se muestra en los pasos de título ni contenido (ESPERANDO_TITULO, DECISION_TITULO, ESPERANDO_TEXTO, DECISION_TEXTO).
       - En modo enriquecer / actualizar: se oculta si ya cuenta con categoría válida (>1) y tags (>=2).
         Solo se muestra si requiere completar categoría o tags en la etapa post-texto.
       - En alta nueva: se muestra en la etapa post-texto.
    */
    const b = s.borrador;
    const esEnriquecerOActualizar = b && (b.modo === 'enriquecimiento' || b.modo === 'actualizar' || b.articulo_original_id != null);
    const tagsValidos = (s.form.tags || []).length >= cfg.MIN_TAGS;
    const catValida = Number(s.form.categoria_id) > 1;
    const etapaPostTexto = s.flujo !== 'ESPERANDO_TITULO' && s.flujo !== 'DECISION_TITULO' && s.flujo !== 'ESPERANDO_TEXTO' && s.flujo !== 'DECISION_TEXTO';

    let mostrarCampoTags = false;
    if (etapaPostTexto) {
      if (esEnriquecerOActualizar) {
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
    $('#tagBox').classList.toggle('off', !act.tags);

    if ($('#fTitulo').value !== s.form.titulo && document.activeElement !== $('#fTitulo')) {
      $('#fTitulo').value = s.form.titulo;
    }
    if ($('#fCuerpo').value !== s.form.texto && document.activeElement !== $('#fCuerpo')) {
      $('#fCuerpo').value = s.form.texto;
    }

    /* Contadores */
    contador($('#contTitulo'), s.form.titulo.length, cfg.MIN_TITULO, 'caracteres', cfg.MAX_TITULO);
    contadorTexto($('#contTexto'), $('#avisoMaxTexto'), s.form.texto.length, cfg.MIN_TEXTO, cfg.MAX_TEXTO);
    contador($('#contTags'),   s.form.tags.length,   cfg.MIN_TAGS,   'etiquetas', cfg.MAX_TAGS);

    const enEsperandoTexto = s.flujo === 'ESPERANDO_TEXTO';
    const compMeta = $('#chatComposerMeta');
    const chatIn = $('#chatInput');
    if (compMeta) {
      compMeta.hidden = true;
    }
    if (chatIn) {
      chatIn.placeholder = 'Respondé acá o preguntale algo a BACO…';
    }

    /* botón principal */
    const acc = BACO.ACCION_PRINCIPAL[s.flujo];
    const btn = $('#btnPrincipal');
    if (acc) {
      btn.hidden = false;
      btn.disabled = s.enviando || !listoParaEnviar(s, acc.campo);
      btn.textContent = (acc.campo === 'todo' && !hayCambios(s))
        ? 'Sin cambios para guardar'
        : acc.label;
      const textoCorto = s.form.texto.trim().length < cfg.MIN_TEXTO;
      const textoLargo = s.form.texto.length > cfg.MAX_TEXTO;
      const tagsFaltan = (s.form.tags || []).length < cfg.MIN_TAGS;
      const catFalta = !s.form.categoria_id || Number(s.form.categoria_id) <= 1;
      btn.title = btn.disabled && acc.campo === 'todo'
        ? 'Editá algún campo para habilitar el guardado'
        : (btn.disabled && acc.campo === 'texto'
            ? (textoCorto
                ? 'El texto debe tener al menos ' + cfg.MIN_TEXTO + ' caracteres'
                : (textoLargo ? 'El texto supera el máximo de ' + cfg.MAX_TEXTO + ' caracteres' : ''))
            : (btn.disabled && acc.campo === 'tags'
                ? ((tagsFaltan ? 'Se requieren al menos ' + cfg.MIN_TAGS + ' etiquetas. ' : '') + (catFalta ? 'Debe seleccionarse una categoría del desplegable.' : ''))
                : ''));
    } else {
      btn.hidden = true;
    }

    pintarTags(s);
    pintarCategorias(s, !!act.categoria && !s.enviando);
    pintarResumenFinal(s);
    pintarBorrador(s);
    pintarAvisoMetadatosHeredados(s);
    pintarCoincidencias(s);
    pintarValidacion(s);
    pintarOpciones(s);
    pintarImagenesDetectadas(s);

    sincronizarBloquesDesdeStore(s);
    renderBloques();

    if (!$('#preview').hidden) {
      $('#preview').innerHTML = renderMd(textoVistaPrevia(s));
    }
  }

  /* Vista previa reactiva a partir de los bloques del editor */
  function textoVistaPrevia(s) {
    if (estadoEditor && estadoEditor.bloques && estadoEditor.bloques.length) {
      return componerTextoDesdeBloques();
    }
    return (s && s.form && s.form.texto) || '';
  }

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

    let selHtml = '<option value=""' + (!actualId ? ' selected' : '') + ' disabled>Elegí una categoría del desplegable…</option>';
    
    // Ordenar alfabéticamente para facilitar la navegación en las 165 opciones
    const catsOrdenadas = [...cats].sort((a, b) =>
      (a.nombre || '').localeCompare(b.nombre || '', 'es', { sensitivity: 'base' })
    );

    catsOrdenadas.forEach((c) => {
      const selected = actualId && Number(c.id) === actualId;
      selHtml += '<option value="' + esc(c.id) + '"' + (selected ? ' selected' : '') + '>' + esc(c.nombre) + '</option>';
    });
    sel.innerHTML = selHtml;
    sel.value = actualId ? String(actualId) : '';

    chipsRow.innerHTML = '';
    if (!cats.length) return;

    // Mostrar como chips rápidos solo las categorías principales/frecuentes
    const IDS_CHIPS_FRECUENTES = new Set([
      20, 21, 24, 22, 23, 19, 37, 39, 25, 26, 28, 29, 33, 40, 48, 62, 63, 65, 81, 82, 83
    ]);
    const catsChips = cats.length > 25
      ? cats.filter((c) => IDS_CHIPS_FRECUENTES.has(Number(c.id)))
      : cats;

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

  function pintarAvisoMetadatosHeredados(s) {
    const bannerAviso = $('#bannerAviso');
    if (!bannerAviso) return;
    const b = s.borrador;
    const metaAnt = b && b.metadatos_anteriores;
    const pendiente = metaAnt && !b.metadatos_heredados_revisados;

    if (pendiente) {
      const nomCat = metaAnt.categoria_nombre || nombreCategoria(s, metaAnt.categoria_id);
      const tagsStr = (metaAnt.tags || []).join(', ') || 'sin etiquetas';
      bannerAviso.innerHTML =
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
          enviarTurno({ accion: 'aceptar_metadatos' }, 'Aceptar metadatos heredados');
        };
      }
      const btnRech = $('#btnRechMetaHeredados');
      if (btnRech) {
        btnRech.onclick = () => {
          store.setForm({ categoria_id: null, tags: [] });
          enviarTurno({ accion: 'rechazar_metadatos' }, 'Rechazar metadatos heredados');
        };
      }
    } else {
      const bannerMeta = bannerAviso.querySelector('.banner-meta-ant');
      if (bannerMeta) {
        bannerAviso.innerHTML = '';
      }
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

  /* Pinta un contador: mientras falta, "12 / 15 mín."; cuando ya
     alcanza, solo el número. Si hay máximo, avisa al acercarse. */
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
    if (nodo) {
      nodo.textContent = actual + ' / ' + maximo + ' caracteres';
      if (actual > maximo) {
        nodo.className = 'cont exceso';
      } else if (actual > 0 && actual < minimo) {
        nodo.className = 'cont falta';
      } else if (actual >= minimo) {
        nodo.className = 'cont ok';
      } else {
        nodo.className = 'cont';
      }
    }
    if (nodoAviso) {
      if (actual > maximo) {
        const sobran = actual - maximo;
        nodoAviso.hidden = false;
        nodoAviso.textContent = 'El texto supera el límite máximo permitido de ' + maximo + ' caracteres (excede por ' + sobran + '). Acortalo o dividilo para poder confirmar.';
      } else {
        nodoAviso.hidden = true;
        nodoAviso.textContent = '';
      }
    }
  }

  function listoParaEnviar(s, campo) {
    if (campo === 'titulo') return s.form.titulo.trim().length >= cfg.MIN_TITULO;
    if (campo === 'texto')  return s.form.texto.trim().length >= cfg.MIN_TEXTO && s.form.texto.length <= cfg.MAX_TEXTO;
    if (campo === 'tags')   return s.form.tags.length >= cfg.MIN_TAGS && Number(s.form.categoria_id) > 1;
    if (campo === 'todo') return hayCambios(s) && s.form.texto.length <= cfg.MAX_TEXTO;
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

    const row = $('#suggRow'); row.innerHTML = '';
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
  function pintarCoincidencias(s) {
    const slot = $('#slotCoincidencias');
    if (!s.coincidencias.length) { slot.innerHTML = ''; return; }
    let h = '<div class="alert dup"><div class="ah">' +
      '<span class="ic"><svg width="18" height="18" viewBox="0 0 16 16" fill="none"><path d="M8 2.2l6.2 11H1.8L8 2.2z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M8 6.6v3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="8" cy="11.4" r=".85" fill="currentColor"/></svg></span>' +
      '<div><b>Ya hay algo parecido publicado</b><p>Elegí abajo si lo enriquecés o seguís con tu contenido.</p></div>' +
      '</div><div class="hits">';
    const TIPOS = {
      exacto:    'título idéntico',
      serie:     'parece parte de la misma serie',
      trigrama:  'texto muy parecido',
      semantico: 'habla de lo mismo'
    };
    s.coincidencias.forEach((c) => {
      h += '<div class="hit">' +
        (c.url
          ? '<a href="' + esc(c.url) + '" target="_blank" rel="noopener">#' + c.id + ' · ' + esc(c.titulo) + '</a>'
          : '<a>#' + c.id + ' · ' + esc(c.titulo) + '</a>') +
        (c.score != null ? '<span class="sc' + (c.score >= 0.9 ? ' hi' : '') + '">' + Number(c.score).toFixed(2) + '</span>' : '') +
        (c.tipo_coincidencia ? '<span class="vd">' + esc(TIPOS[c.tipo_coincidencia] || c.tipo_coincidencia) + '</span>' : '') +
        '</div>';
    });
    slot.innerHTML = h + '</div></div>';
  }

  /* ---------------- validación ---------------- */
  function pintarValidacion(s) {
    const slot = $('#slotValidacion');
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
        const campo = $('#' + nodo.dataset.ir);
        if (!campo || campo.disabled) return;
        campo.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setTimeout(() => {
          campo.focus();
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
    barra.innerHTML = '';
    if (!s.opciones.length) return;
    s.opciones.forEach((op) => {
      /* Si la acción principal ya es confirmar_texto (el botón principal del panel izquierdo),
         no la duplicamos en opcionesBarra para no tener dos botones idénticos uno al lado del otro. */
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

    if (op === 'copiar_borrador') {
      copiarBorrador();
      return;
    }

    if (op === 'confirmar_texto') {
      return confirmarTexto();
    }

    /* 'editar' en revisión manda los campos del formulario */
    if (op === 'editar' && s.flujo === 'REVISION_BORRADOR') {
      return enviarTurno({
        accion: 'editar',
        titulo: s.form.titulo,
        texto: s.form.texto,
        tags: s.form.tags,
        categoria_id: s.form.categoria_id
      }, 'Guardar cambios');
    }
    if (op === 'reiniciar') {
      store.reiniciarLocal();
      if (api.olvidarSesion) api.olvidarSesion();
      $('#thread').innerHTML = '';
      $('#bannerError').innerHTML = '';
      $('#bannerAviso').innerHTML = '';
      const chatIn = $('#chatInput');
      if (chatIn) { chatIn.value = ''; chatIn.style.height = 'auto'; }
      return enviarTurno({ accion: 'reiniciar' });
    }
    enviarTurno({ accion: op }, label);
  }

  function confirmarTexto() {
    const s = store.get();
    const texto = (s.form && typeof s.form.texto === 'string' ? s.form.texto : '').trim();
    if (texto) {
      if (texto.length > cfg.MAX_TEXTO) return;
      return enviarTurno({ accion: 'confirmar_texto', texto: texto }, 'Confirmar texto (' + texto.length + ' caracteres)');
    }
    const chatIn = $('#chatInput');
    const pendiente = chatIn ? chatIn.value.trim() : '';
    if (pendiente) {
      if (pendiente.length > cfg.MAX_TEXTO) return;
      chatIn.value = '';
      chatIn.style.height = 'auto';
      return enviarTurno({ accion: 'confirmar_texto', texto: pendiente }, 'Confirmar texto (' + pendiente.length + ' caracteres)');
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

  /* ---- skills del agente: endpoints dedicados ---- */
  async function invocarAgente(metodo, etiqueta) {
    const s = store.get();
    if (!s.borrador) {
      decir('Todavía no hay un borrador armado. Las skills se habilitan recién cuando lleguemos a la revisión.');
      return;
    }
    burbuja('me', esc(etiqueta));
    const esperando = burbuja('bot', '<div class="typing"><i></i><i></i><i></i></div>' +
      '<div class="lento">El agente puede tardar varios segundos…</div>');
    try {
      const r = await api[metodo]();
      esperando.remove();
      ultimoFallo = null;
      decir('<div class="respuesta-agente">' + nl2br(r.response) + '</div>', [], true);
    } catch (e) {
      esperando.remove();
      ultimoFallo = { tipo: 'agente', metodo: metodo, etiqueta: etiqueta };
      mostrarError(e);
      decir('El agente no respondió: ' + esc(e.message));
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
  const mostrarAprobado = mostrarConforme;

  async function copiarBorrador() {
    const s = store.get();
    try {
      let b = s.borrador;
      if (!b && (s.flujo === 'CONFORMIDAD_USUARIO' || s.flujo === 'APROBADO')) {
        b = (api.borradorConforme ? await api.borradorConforme() : await api.borradorAprobado());
      }
      const titulo = (b && b.titulo) || s.form.titulo || '';
      const texto = (b && (b.texto || b.texto_limpio)) || s.form.texto || '';
      const textoACopiar = `# ${titulo}\n\n${texto}`.trim();
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
    if (opcionesCompanion.length) {
      const cont = el('div', 'acciones');
      opcionesCompanion.forEach((op) => {
        const def = BACO.OPCIONES[op] || { label: op, estilo: 'btn-ghost' };
        const btn = el('button', 'btn btn-sm ' + def.estilo, esc(def.label));
        btn.onclick = () => accionar(op, def.label);
        cont.appendChild(btn);
      });
      b.querySelector('.bubble').insertBefore(cont, b.querySelector('.stamp'));
    }
  }

  async function enviarChatLibre() {
    const v = $('#chatInput').value.trim();
    if (!v) return;
    $('#chatInput').value = ''; $('#chatInput').style.height = 'auto';

    const s = store.get();
    if (s.flujo === 'ESPERANDO_TITULO')  return enviarTurno({ titulo: v }, v);
    if (s.flujo === 'ESPERANDO_TEXTO') {
      const cmd = v.toLowerCase();
      if (['volver', 'atras', 'atrás', 'regresar', 'reiniciar', 'ayuda', '?', 'descartar', 'continuar'].includes(cmd)) {
        return enviarTurno({ mensaje: v }, v);
      }
      if (cmd === 'confirmar' || cmd === 'confirmar texto' || cmd === 'confirmar_texto') {
        return confirmarTexto();
      }
      const actual = (s.form && typeof s.form.texto === 'string') ? s.form.texto.trim() : '';
      const acumulado = actual ? (actual + '\n\n' + v) : v;
      store.setForm({ texto: acumulado });
      $('#fCuerpo').value = acumulado;
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
    const b = $('#bannerAviso');
    b.innerHTML = '<div class="banner aviso">' +
      '<svg width="15" height="15" viewBox="0 0 16 16" fill="none"><path d="M8 1.8l5 2v4.4c0 3-2.2 5.3-5 6-2.8-.7-5-3-5-6V3.8l5-2z" stroke="currentColor" stroke-width="1.3"/><path d="M5.9 8.1l1.5 1.5 3-3.1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>' +
      '<span><b>Datos sensibles anonimizados</b> · ' + esc(texto) + '</span>' +
      '<button class="cerrar" aria-label="Cerrar">&times;</button></div>';
    b.querySelector('.cerrar').onclick = () => { b.innerHTML = ''; };
  }

  function toast(msg) {
    const t = $('#toast');
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

    // 2. Sección de Contenido adicional (habilitada en flujos de actualizar o enriquecer)
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
    bar.hidden = !$('#preview').hidden;

    // Handlers para agregar contenido nuevo mediante el formulario directo
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

    // Handlers para abrir modo de edición de un ítem
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

    // Handlers para cancelar la edición de un ítem
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

    // Guardar edición de un ítem modificado
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

    // Handlers para eliminar ítems individuales
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

    // Handlers para reordenar ítems (subir / bajar)
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
      // 1. Tokens de reemplazo previo al escape HTML
      let res = String(s).replace(
        /!\[([^\]]*)\]\((https?:\/\/[^\s\)]+)\)/g,
        '___IMG_START___$1___SEP___$2___IMG_END___'
      ).replace(
        /\[([^\]]+)\|attachment\]\((https?:\/\/[^\s\)]+)\)/g,
        '___ATT_START___$1___SEP___$2___ATT_END___'
      ).replace(
        /\[([^\]]+)\]\((https?:\/\/[^\s\)]+)\)/g,
        '___LINK_START___$1___SEP___$2___LINK_END___'
      );

      // 2. Escapar caracteres HTML peligrosos
      res = esc(res);

      // 3. Restaurar imágenes y medios seguros
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

      // 4. Formatos inline estándar (negrita, código)
      return res
        .replace(/\*\*([^\*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+)`/g, '<code>$1</code>');
    };

    const out = []; let lista = null;
    const cerrar = () => { if (lista) { out.push('</' + lista + '>'); lista = null; } };

    String(src).split('\n').forEach((raw) => {
      const l = raw.trim();
      if (!l) { cerrar(); return; }

      // Línea solitaria con imagen
      const imgMatch = l.match(/^!\[([^\]]*)\]\((https?:\/\/[^\s\)]+)\)$/);
      if (imgMatch) {
        cerrar();
        const alt = esc(imgMatch[1]);
        const url = encodeURI(imgMatch[2]);
        out.push('<div class="preview-img-box"><img src="' + url + '" alt="' + alt + '" class="preview-img" loading="lazy" referrerpolicy="no-referrer" /><span class="caption">' + alt + '</span></div>');
        return;
      }

      // Línea solitaria con video de YouTube (reproductor integrado)
      const ytMatch = l.match(/^(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:watch\?v=|embed\/|shorts\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})(?:[^\s]*)?$/);
      if (ytMatch) {
        cerrar();
        const ytId = ytMatch[1];
        const fullUrl = l.startsWith('http') ? l : ('https://' + l);
        out.push('<div class="preview-video-box"><iframe class="preview-video-frame" src="https://www.youtube.com/embed/' + ytId + '" title="Video tutorial" frameborder="0" allowfullscreen loading="lazy"></iframe><div class="caption">🎬 Video explicativo · <a class="preview-link" href="' + encodeURI(fullUrl) + '" target="_blank" rel="noopener">Abrir en YouTube ↗</a></div></div>');
        return;
      }

      // Línea solitaria con URL cruda de docs, diapositivas o video
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
     Eventos Mini Panel Multimedia
     ========================================================= */
  function conectarEventosMultimedia() {
    const cont = $('#panelMultimedia');
    if (!cont) return;

    let arrastrandoIdx = null;

    cont.addEventListener('click', async (e) => {
      // 1. Abrir / cerrar área de carga
      const btnCarga = e.target.closest('[data-accion="abrir-carga"]');
      if (btnCarga && !btnCarga.disabled) {
        e.preventDefault();
        const abierta = BACO.panelMultimedia.alternarCarga();
        BACO.panelMultimedia.pintar(cont, store.get());
        if (abierta) { const u = $('#pmUrl'); if (u) u.focus(); }
        return;
      }

      // 2. Quitar recurso (botón ×)
      const btnQuitar = e.target.closest('[data-accion="quitar"]');
      if (btnQuitar && !btnQuitar.disabled) {
        e.preventDefault();
        const id = btnQuitar.getAttribute('data-id');
        if (!id) return;
        try {
          store.set({ enviando: true });
          await api.eliminarRecurso(id);
          const recs = await api.obtenerRecursos();
          store.actualizarRecursos(recs);
          toast('Recurso quitado');
        } catch (err) {
          toast(err.message || 'No se pudo quitar el recurso');
        } finally {
          store.set({ enviando: false });
        }
        return;
      }

      // 3. Reordenar con botones ↑ / ↓
      const btnMover = e.target.closest('[data-accion="subir"], [data-accion="bajar"]');
      if (btnMover && !btnMover.disabled) {
        e.preventDefault();
        const accion = btnMover.getAttribute('data-accion');
        const idx = parseInt(btnMover.getAttribute('data-idx'), 10);
        if (isNaN(idx)) return;
        const targetIdx = accion === 'subir' ? idx - 1 : idx + 1;
        try {
          store.set({ enviando: true });
          await api.reordenarMultimedia(idx, targetIdx);
          const recs = await api.obtenerRecursos();
          store.actualizarRecursos(recs);
        } catch (err) {
          toast(err.message || 'No se pudo reordenar');
        } finally {
          store.set({ enviando: false });
        }
        return;
      }

      // 4. Agregar por URL
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
        await api.agregarRecursoMultimedia({ referencia: url });
        inputUrl.value = '';
        const recs = await api.obtenerRecursos();
        store.actualizarRecursos(recs);
        toast('Recurso agregado');
      } catch (err) {
        toast(err.message || 'No se pudo agregar la URL');
      } finally {
        store.set({ enviando: false });
      }
    }

    async function subirArchivoMultimedia(file) {
      if (!file) return;
      try {
        store.set({ enviando: true });
        await api.subirRecursoMultimedia(file);
        const recs = await api.obtenerRecursos();
        store.actualizarRecursos(recs);
        toast('Archivo subido');
      } catch (err) {
        toast(err.message || 'No se pudo subir el archivo');
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
          subirArchivoMultimedia(file);
        }
      }
    });

    // Drag and drop de archivos sobre .pm-drop
    cont.addEventListener('dragover', (e) => {
      const drop = e.target.closest('.pm-drop');
      if (drop && e.dataTransfer && e.dataTransfer.types && Array.from(e.dataTransfer.types).includes('Files')) {
        e.preventDefault();
        drop.classList.add('sobre');
      }
    });
    cont.addEventListener('dragleave', (e) => {
      const drop = e.target.closest('.pm-drop');
      if (drop) drop.classList.remove('sobre');
    });
    cont.addEventListener('drop', (e) => {
      const drop = e.target.closest('.pm-drop');
      if (drop && e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
        e.preventDefault();
        drop.classList.remove('sobre');
        subirArchivoMultimedia(e.dataTransfer.files[0]);
      }
    });

    // Drag and drop para reordenar items .pm-item
    cont.addEventListener('dragstart', (e) => {
      const item = e.target.closest('.pm-item');
      if (!item) return;
      arrastrandoIdx = parseInt(item.getAttribute('data-idx'), 10);
      if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', String(arrastrandoIdx));
      }
      item.classList.add('arrastrando');
    });

    cont.addEventListener('dragover', (e) => {
      const item = e.target.closest('.pm-item');
      if (item && arrastrandoIdx !== null) {
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
        item.classList.add('destino');
      }
    });

    cont.addEventListener('dragleave', (e) => {
      const item = e.target.closest('.pm-item');
      if (item) item.classList.remove('destino');
    });

    cont.addEventListener('dragend', (e) => {
      const item = e.target.closest('.pm-item');
      if (item) item.classList.remove('arrastrando');
      cont.querySelectorAll('.pm-item.destino').forEach(el => el.classList.remove('destino'));
      arrastrandoIdx = null;
    });

    cont.addEventListener('drop', async (e) => {
      const item = e.target.closest('.pm-item');
      if (item && arrastrandoIdx !== null) {
        e.preventDefault();
        item.classList.remove('destino');
        const destinoIdx = parseInt(item.getAttribute('data-idx'), 10);
        const origenIdx = arrastrandoIdx;
        arrastrandoIdx = null;
        if (!isNaN(destinoIdx) && origenIdx !== destinoIdx) {
          try {
            store.set({ enviando: true });
            await api.reordenarMultimedia(origenIdx, destinoIdx);
            const recs = await api.obtenerRecursos();
            store.actualizarRecursos(recs);
          } catch (err) {
            toast(err.message || 'No se pudo reordenar');
          } finally {
            store.set({ enviando: false });
          }
        }
      }
    });
  }

  /* =========================================================
     Eventos
     ========================================================= */
  function conectarEventos() {
    $('#fTitulo').addEventListener('input', (e) => store.setForm({ titulo: e.target.value }));
    $('#fCuerpo').addEventListener('input', (e) => store.setForm({ texto: e.target.value }));
    $('#fCategoria').addEventListener('change', (e) => store.setForm({ categoria_id: parseInt(e.target.value, 10) || null }));

    $('#fTitulo').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const s = store.get();
        if (s.flujo === 'ESPERANDO_TITULO') {
          const tit = s.form.titulo.trim();
          if (tit.length >= cfg.MIN_TITULO && !s.enviando) {
            enviarTurno({ titulo: tit }, tit);
          }
        } else if (!$('#btnPrincipal').disabled) {
          enviarPrincipal();
        }
      }
    });

    $('#fCuerpo').addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        if (!$('#btnPrincipal').disabled) enviarPrincipal();
      }
    });

    $('#tagInput').addEventListener('keydown', (e) => {
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
    $('#tagBox').addEventListener('click', (e) => { if (e.target === e.currentTarget && !$('#tagInput').disabled) $('#tagInput').focus(); });

    $('#btnPrincipal').onclick = enviarPrincipal;

    const contBloques = $('#contenedorBloques');
    if (contBloques) {
      contBloques.addEventListener('click', (e) => {
        const targetAccion = e.target.closest('[data-accion]');
        if (!targetAccion) return;

        const accion = targetAccion.getAttribute('data-accion');
        const id = targetAccion.getAttribute('data-id');
        const posStr = targetAccion.getAttribute('data-pos');
        const pos = posStr != null ? parseInt(posStr, 10) : null;
        const tipo = targetAccion.getAttribute('data-tipo');

        if (accion === 'toggle-menu') {
          e.stopPropagation();
          estadoEditor.menuAbiertoPos = estadoEditor.menuAbiertoPos === pos ? null : pos;
          renderBloques();
        } else if (accion === 'abrir-selector') {
          e.stopPropagation();
          estadoEditor.menuAbiertoPos = null;
          renderBloques();
          abrirSelectorParaTipo(tipo, pos);
        } else if (accion === 'eliminar-bloque') {
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
          const id = e.target.getAttribute('data-id');
          const b = estadoEditor.bloques.find((x) => x.id === id);
          if (b) {
            b.contenido = e.target.value;
            sincronizarTextoConStore();
          }
        }
      });
    }

    document.addEventListener('click', (e) => {
      if (estadoEditor.menuAbiertoPos !== null && !e.target.closest('.bloque-divider')) {
        estadoEditor.menuAbiertoPos = null;
        renderBloques();
      }
    });

    const inputSelector = $('#inputSelectorBloque');
    if (inputSelector) {
      inputSelector.addEventListener('change', (e) => {
        const f = e.target.files && e.target.files[0];
        if (f) {
          validarYSubirArchivo(f, selectorTargetTipo, selectorTargetPos);
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
    $('#btnEditor').onclick = () => {
      $('#editorBloquesWrapper').hidden = false;
      $('#fCuerpo').hidden = true;
      $('#preview').hidden = true;
      $('#btnEditor').classList.add('sel');
      $('#btnPreview').classList.remove('sel');
      estadoEditor.modo = 'edicion';
      renderBloques();
    };
    $('#btnPreview').onclick = () => {
      sincronizarTextoConStore();
      $('#preview').innerHTML = renderMd(textoVistaPrevia(store.get()));
      $('#editorBloquesWrapper').hidden = true;
      $('#fCuerpo').hidden = true;
      $('#preview').hidden = false;
      $('#btnPreview').classList.add('sel');
      $('#btnEditor').classList.remove('sel');
      estadoEditor.modo = 'preview';
      const bar = $('#editorImgBar'); if (bar) bar.hidden = true;
      const pm = $('#panelMultimedia'); if (pm) { pm.hidden = true; pm.innerHTML = ''; }
    };

    $('#btnSubir').onclick = () => $('#fileInput').click();
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
        const s = store.get();
        const nuevo = (s.form.texto.trim() ? s.form.texto + '\n\n' : '') + lector.result;
        store.setForm({ texto: nuevo });
        $('#fCuerpo').value = nuevo;
        if (estadoEditor.bloques.length && estadoEditor.bloques[estadoEditor.bloques.length - 1].tipo === 'texto') {
          const ult = estadoEditor.bloques[estadoEditor.bloques.length - 1];
          ult.contenido = (ult.contenido.trim() ? ult.contenido + '\n\n' : '') + lector.result;
        } else {
          estadoEditor.bloques.push({ id: genId(), tipo: 'texto', contenido: String(lector.result) });
        }
        renderBloques();
        toast('Documento volcado en el editor');
      };
      lector.readAsText(f);
    });

    $('#btnPlantilla').onclick = aplicarPlantilla;
    $('#btnAuditar').onclick = auditar;

    $('#btnReiniciar').onclick = () => accionar('reiniciar', 'Empezar de nuevo');
    $('#btnEjemplo').onclick = cargarEjemplo;

    $('#btnCerrar').onclick = () => { $('#overlay').hidden = true; };
    $('#btnCopiarBorrador').onclick = copiarBorrador;
    $('#btnOtra').onclick = () => { $('#overlay').hidden = true; accionar('reiniciar', 'Empezar de nuevo'); };

    $('#swError').addEventListener('change', (e) => {
      cfg.mock.TASA_ERROR = e.target.checked ? 0.35 : 0;
      toast(e.target.checked ? 'Fallas simuladas activadas' : 'Fallas simuladas desactivadas');
    });

    $('#btnSend').onclick = enviarChatLibre;
    $('#chatInput').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviarChatLibre(); }
    });
    $('#chatInput').addEventListener('input', (e) => {
      e.target.style.height = 'auto';
      e.target.style.height = Math.min(110, e.target.scrollHeight) + 'px';
      const s = store.get();
      if (s.flujo === 'ESPERANDO_TEXTO') {
        contadorTexto($('#chatInputCont'), $('#chatInputAvisoMax'), e.target.value.length, cfg.MIN_TEXTO, cfg.MAX_TEXTO);
      }
    });
  }

  function cargarEjemplo() {
    const s = store.get();
    if (s.flujo === 'ESPERANDO_TITULO') {
      const t = BACO.datos.ejemplo.titulo;
      $('#fTitulo').value = t; store.setForm({ titulo: t });
      toast('Título de ejemplo cargado');
    } else if (s.flujo === 'ESPERANDO_TEXTO') {
      const c = BACO.datos.ejemplo.cuerpo;
      $('#fCuerpo').value = c;
      store.setForm({ texto: c });
      estadoEditor.bloques = [{ id: genId(), tipo: 'texto', contenido: c }];
      renderBloques();
      toast('Contenido de ejemplo cargado en el editor. Tocá "Confirmar texto" cuando estés listo.');
    } else {
      toast('El ejemplo se carga en los pasos de título y contenido');
    }
  }

  iniciar();
})();
