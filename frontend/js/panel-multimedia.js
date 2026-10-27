/* =============================================================
   Mini panel de carga multimedia del borrador
   -------------------------------------------------------------
   - Fuente de datos: s.borrador.multimedia (lista ordenada que
     devuelve el backend). Nunca se lee del texto.
   - Se muestra cuando s.multimedia_habilitada (criterio único del
     backend: superada buscar_duplicados, en cualquier rama).
     No depende de modo / enriquecer / actualizar.
   - Los recursos viven aparte de texto_limpio: la vista previa
     respeta el orden exacto (posicion, orden) intercalado con
     bloques_texto.
   Sin dependencias.
   ============================================================= */
window.BACO = window.BACO || {};

BACO.panelMultimedia = (function () {
  'use strict';

  const ACCEPT = '.png,.jpg,.jpeg,.gif,.webp,.pdf,.mp4,.webm,.mp3,.docx,.pptx,.xlsx';
  const ICONOS = { imagen: '🖼️', video: '🎬', audio: '🎵', documento: '📄', otro: '🔗' };
  const ETIQUETAS = { imagen: 'Imagen', video: 'Video', audio: 'Audio', documento: 'Documento', otro: 'Enlace' };
  const SECCION_RECURSOS_TITULO = '## Recursos';

  /* Estado local de UI (no es estado del borrador) */
  let cargaAbierta = false;

  function esc(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function esUrlWeb(ref) {
    return /^(https?:\/\/|\/api\/recursos-temp\/)/i.test(String(ref || ''));
  }

  function ordenarPorPosicionYOrden(arr) {
    return (arr || []).slice().sort((a, b) => {
      const hasPosA = typeof a.posicion === 'number';
      const hasPosB = typeof b.posicion === 'number';
      if (hasPosA || hasPosB) {
        const pa = hasPosA ? a.posicion : 0;
        const pb = hasPosB ? b.posicion : 0;
        if (pa !== pb) return pa - pb;
      }
      return (a.orden || 0) - (b.orden || 0);
    });
  }

  /* Lista ordenada por (posicion, orden). Usa `multimedia` o `recursos` del borrador. */
  function lista(s) {
    const b = s && s.borrador;
    if (!b) return [];
    if (Array.isArray(b.multimedia)) return ordenarPorPosicionYOrden(b.multimedia);
    if (Array.isArray(b.recursos)) return ordenarPorPosicionYOrden(b.recursos);
    return ordenarPorPosicionYOrden(Object.values(b.recursos || {}));
  }

  /* La disponibilidad la decide exclusivamente el servidor mediante multimedia_habilitada */
  function habilitado(s) {
    return Boolean(s && s.multimedia_habilitada === true);
  }

  /* Misma composición que el backend (componer_texto_publicable): solo para mostrar */
  function aMarkdown(r) {
    const n = r.nombre || '';
    const ref = r.referencia || r.url || '';
    if (r.tipo === 'imagen') return '![' + n + '](' + ref + ')';
    if (r.tipo === 'documento' && (/\/uploads\//.test(ref) || /\/api\/recursos-temp\//.test(ref) || /\.(pdf|zip|docx)$/i.test(ref))) {
      return '[' + n + '|attachment](' + ref + ')';
    }
    return '[' + n + '](' + ref + ')';
  }

  /* Compone la vista previa respetando el orden exacto (posicion, orden) entre bloques_texto */
  function componerIntercaladoPorBloques(bloquesTexto, items) {
    const bloques = Array.isArray(bloquesTexto) && bloquesTexto.length ? bloquesTexto : [''];
    const ordenados = ordenarPorPosicionYOrden(items || []);
    const partes = [];

    // Recursos antes del primer bloque (posicion === -1)
    ordenados
      .filter((r) => r.posicion === -1)
      .forEach((r) => partes.push(aMarkdown(r)));

    for (let i = 0; i < bloques.length; i++) {
      const txt = String(bloques[i] == null ? '' : bloques[i]).trim();
      if (txt) partes.push(txt);
      ordenados
        .filter((r) => (typeof r.posicion === 'number' ? r.posicion : 0) === i)
        .forEach((r) => partes.push(aMarkdown(r)));
    }

    // Recursos cuya posicion supere el último índice (fallback defensivo)
    ordenados
      .filter((r) => typeof r.posicion === 'number' && r.posicion >= bloques.length)
      .forEach((r) => partes.push(aMarkdown(r)));

    return partes.join('\n\n').trim();
  }

  function componerVistaPrevia(textoLimpio, items, s) {
    const listaActual = items || [];

    // Si textoLimpio es directamente un arreglo de bloques_texto o s provee bloques_texto con recursos posicionados:
    if (Array.isArray(textoLimpio)) {
      return componerIntercaladoPorBloques(textoLimpio, listaActual);
    }

    const bloquesEnEstado = (s && Array.isArray(s.bloques_texto) && s.bloques_texto.length)
      ? s.bloques_texto
      : ((s && s.borrador && Array.isArray(s.borrador.bloques_texto) && s.borrador.bloques_texto.length)
          ? s.borrador.bloques_texto
          : null);
    const tienePosicionExplicita = listaActual.some((r) => typeof r.posicion === 'number');

    if (bloquesEnEstado || tienePosicionExplicita) {
      const cuerpoActual = String(textoLimpio || '').trim();
      const derivadoEstado = bloquesEnEstado
        ? bloquesEnEstado.map((b) => String(b || '').trim()).filter(Boolean).join('\n\n')
        : '';
      const bloquesParaUsar = (bloquesEnEstado && (!cuerpoActual || cuerpoActual === derivadoEstado))
        ? bloquesEnEstado
        : (bloquesEnEstado && bloquesEnEstado.length > 1 && tienePosicionExplicita
            ? bloquesEnEstado
            : [String(textoLimpio || '')]);
      return componerIntercaladoPorBloques(bloquesParaUsar, listaActual);
    }

    const cuerpo = String(textoLimpio || '').trim();

    // Texto original de la API (si existe en las coincidencias o en el borrador inicial)
    const textoOriginalApi = ((s && s.coincidencias && s.coincidencias[0] && s.coincidencias[0].texto_original) ||
      (s && s.borrador && s.borrador.texto_original_aprobado) || '').trim();

    // El texto base limpio original sin markdown de imágenes ni adjuntos
    const textoOriginalLimpioApi = (s && s.borrador && typeof s.borrador.texto_base_limpio === 'string' && s.borrador.texto_base_limpio.trim())
      ? s.borrador.texto_base_limpio.trim()
      : (textoOriginalApi
          ? textoOriginalApi
              .replace(/!\[([^\]]*)\]\([^\)]+\)/g, '')
              .replace(/\[([^\]]+)\|attachment\]\([^\)]+\)/g, '')
              .replace(/\[\[recurso:[a-zA-Z0-9_\-]+\]\]/g, '')
              .replace(/\r\n/g, '\n')
              .replace(/\n{3,}/g, '\n\n')
              .trim()
          : '');

    const esBase = Boolean(textoOriginalApi && textoOriginalLimpioApi && cuerpo && cuerpo === textoOriginalLimpioApi);

    if (esBase) {
      let resultado = textoOriginalApi;
      const urlsActivas = new Set(listaActual.map((r) => String(r.referencia || '').trim()).filter(Boolean));
      const urlsOriginales = new Set();

      resultado = resultado.replace(/!\[([^\]]*)\]\((https?:\/\/[^\s\)]+)\)/g, (match, alt, url) => {
        urlsOriginales.add(url.trim());
        return urlsActivas.has(url.trim()) ? match : '';
      });
      resultado = resultado.replace(/\[([^\]]+)\|attachment\]\((https?:\/\/[^\s\)]+)\)/g, (match, nom, url) => {
        urlsOriginales.add(url.trim());
        return urlsActivas.has(url.trim()) ? match : '';
      });
      resultado = resultado.replace(/\[([^\]]+)\]\((https?:\/\/[^\s\)]+)\)/g, (match, nom, url) => {
        const u = url.trim();
        const esRec = listaActual.some((r) => String(r.referencia || '').trim() === u);
        if (esRec) urlsOriginales.add(u);
        return (!esRec || urlsActivas.has(u)) ? match : '';
      });

      const recursosNuevos = listaActual.filter((r) => {
        const u = String(r.referencia || '').trim();
        return u && !urlsOriginales.has(u);
      });

      if (recursosNuevos.length > 0) {
        const bloqueNuevos = recursosNuevos.map(aMarkdown).join('\n\n');
        resultado = resultado ? resultado + '\n\n' + bloqueNuevos : bloqueNuevos;
      }

      return resultado.replace(/\n{3,}/g, '\n\n').trim();
    }

    if (!listaActual.length) return cuerpo.replace(/\[\[recurso:[a-zA-Z0-9_\-]+\]\]/g, '').trim();

    let resultado = cuerpo;
    const recsMap = new Map();
    listaActual.forEach((r) => {
      if (r.id) recsMap.set(r.id, r);
    });

    resultado = resultado.replace(/\[\[recurso:([a-zA-Z0-9_\-]+)\]\]/g, (match, id) => {
      const r = recsMap.get(id);
      return r ? aMarkdown(r) : '';
    });

    const recursosFaltantes = listaActual.filter((r) => {
      const ref = String(r.referencia || '').trim();
      return !ref || (!resultado.includes(ref) && !cuerpo.includes(r.id));
    });

    if (!recursosFaltantes.length) return resultado;
    const seccionNuevos = SECCION_RECURSOS_TITULO + '\n\n' + recursosFaltantes.map(aMarkdown).join('\n\n');
    return resultado ? resultado + '\n\n' + seccionNuevos : seccionNuevos;
  }

  function pintarItem(r, idx, total, deshabilitado) {
    const id = esc(r.id);
    const tipo = ETIQUETAS[r.tipo] ? r.tipo : 'otro';
    const nombre = esc(r.nombre || r.referencia || r.id);
    const dis = deshabilitado ? ' disabled' : '';
    const miniatura = (tipo === 'imagen' && esUrlWeb(r.referencia))
      ? '<img class="pm-mini" src="' + esc(encodeURI(r.referencia)) + '" alt="" loading="lazy" referrerpolicy="no-referrer" />'
      : '<span class="pm-icono" aria-hidden="true">' + ICONOS[tipo] + '</span>';
    const nombreHtml = esUrlWeb(r.referencia)
      ? '<a class="pm-nombre" href="' + esc(encodeURI(r.referencia)) + '" target="_blank" rel="noopener" title="' + nombre + '">' + nombre + '</a>'
      : '<span class="pm-nombre" title="' + nombre + '">' + nombre + '</span>';

    return '<li class="pm-item" data-id="' + id + '" data-idx="' + idx + '" draggable="' + (deshabilitado ? 'false' : 'true') + '">' +
      '<button type="button" class="pm-quitar" data-accion="quitar" data-id="' + id + '" title="Quitar" aria-label="Quitar ' + nombre + '"' + dis + '>×</button>' +
      '<span class="pm-asa" title="Arrastrar para reordenar" aria-hidden="true">⠿</span>' +
      miniatura +
      '<span class="pm-info">' + nombreHtml + '<span class="pm-tipo">' + ETIQUETAS[tipo] + (r.origen === 'subido' ? ' · subido' : '') + '</span></span>' +
      '<span class="pm-mover">' +
        '<button type="button" class="pm-btn-mover" data-accion="subir" data-idx="' + idx + '" title="Subir" aria-label="Subir"' + (idx === 0 || deshabilitado ? ' disabled' : '') + '>↑</button>' +
        '<button type="button" class="pm-btn-mover" data-accion="bajar" data-idx="' + idx + '" title="Bajar" aria-label="Bajar"' + (idx === total - 1 || deshabilitado ? ' disabled' : '') + '>↓</button>' +
      '</span>' +
    '</li>';
  }

  function pintarCarga(deshabilitado) {
    const dis = deshabilitado ? ' disabled' : '';
    return '<div class="pm-carga"' + (cargaAbierta ? '' : ' hidden') + '>' +
      '<label class="pm-drop" data-accion="soltar-archivo">' +
        '<input type="file" class="pm-file" id="pmArchivo" accept="' + ACCEPT + '"' + dis + ' />' +
        '<span>Subí un archivo o soltalo acá</span>' +
        '<small>Imágenes, PDF, video, audio u Office · máx. 10 MB</small>' +
      '</label>' +
      '<div class="pm-url">' +
        '<input type="url" class="input pm-url-input" id="pmUrl" placeholder="…o pegá un enlace (YouTube, Drive, imagen, PDF)" autocomplete="off"' + dis + ' />' +
        '<button type="button" class="btn btn-sm btn-dark" data-accion="agregar-url"' + dis + '>Agregar</button>' +
      '</div>' +
    '</div>';
  }

  function pintar(cont, s) {
    if (!cont) return;
    if (!habilitado(s)) {
      cont.hidden = true;
      cont.innerHTML = '';
      return;
    }
    const previewEl = typeof document !== 'undefined' ? document.getElementById('preview') : null;
    if (previewEl && !previewEl.hidden) {
      cont.hidden = true;
      return;
    }
    const items = lista(s);
    const deshabilitado = !!(s && s.enviando);

    let h = '<div class="pm-head">' +
      '<span class="pm-tit">Multimedia <span class="pm-count">(' + items.length + ')</span></span>' +
      '<span class="pm-sub">Se guarda aparte del texto</span>' +
      '<button type="button" class="pm-agregar" id="pmAgregar" data-accion="abrir-carga" aria-expanded="' + cargaAbierta + '"' + (deshabilitado ? ' disabled' : '') + '>' +
        (cargaAbierta ? '− Cerrar' : '+ Agregar multimedia') +
      '</button>' +
    '</div>';

    h += pintarCarga(deshabilitado);

    if (items.length) {
      h += '<ol class="pm-lista" id="pmLista">' +
        items.map((r, i) => pintarItem(r, i, items.length, deshabilitado)).join('') +
      '</ol>';
    } else {
      h += '<div class="pm-vacio">Todavía no hay imágenes, videos ni documentos. Tocá <b>+ Agregar multimedia</b>.</div>';
    }

    cont.innerHTML = h;
    cont.hidden = false;
  }

  function alternarCarga(abrir) {
    cargaAbierta = typeof abrir === 'boolean' ? abrir : !cargaAbierta;
    return cargaAbierta;
  }

  return {
    lista,
    habilitado,
    pintar,
    componerVistaPrevia,
    renderPreview: componerVistaPrevia,
    componerIntercaladoPorBloques,
    alternarCarga
  };
})();
