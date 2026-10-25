/* =============================================================
   Mini panel de carga multimedia del borrador
   -------------------------------------------------------------
   - Fuente de datos: s.borrador.multimedia (lista ordenada que
     devuelve el backend). Nunca se lee del texto.
   - Se muestra cuando s.multimedia_habilitada (criterio único del
     backend: superada buscar_duplicados, en cualquier rama).
     No depende de modo / enriquecer / actualizar.
   - Los recursos viven aparte de texto_limpio: el editor muestra
     solo texto y la vista previa los agrega al final.
   Sin dependencias.
   ============================================================= */
window.BACO = window.BACO || {};

BACO.panelMultimedia = (function () {
  'use strict';

  const ESTADOS_PREVIOS_A_DEDUP = ['ESPERANDO_TITULO', 'DECISION_TITULO', 'DECISION_TEXTO', 'RECHAZADO'];
  const ACCEPT = '.png,.jpg,.jpeg,.gif,.webp,.svg,.pdf,.mp4,.webm,.mp3,.docx,.pptx,.xlsx';
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
    return /^https?:\/\//i.test(String(ref || ''));
  }

  /* Lista ordenada. Usa `multimedia` (backend); si no viene (mock), ordena `recursos`. */
  function lista(s) {
    const b = s && s.borrador;
    if (!b) return [];
    if (Array.isArray(b.multimedia)) return b.multimedia.slice();
    return Object.values(b.recursos || {}).sort((x, y) => (x.orden || 0) - (y.orden || 0));
  }

  function habilitado(s) {
    if (!s) return false;
    if (typeof s.multimedia_habilitada === 'boolean') return s.multimedia_habilitada;
    return !!s.borrador && !ESTADOS_PREVIOS_A_DEDUP.includes(s.flujo);
  }

  /* Misma composición que el backend (componer_texto_publicable): solo para mostrar */
  function aMarkdown(r) {
    const n = r.nombre || '';
    const ref = r.referencia || '';
    if (r.tipo === 'imagen') return '![' + n + '](' + ref + ')';
    if (r.tipo === 'documento' && (/\/uploads\//.test(ref) || /\.(pdf|zip|docx)$/i.test(ref))) {
      return '[' + n + '|attachment](' + ref + ')';
    }
    return '[' + n + '](' + ref + ')';
  }

  function componerVistaPrevia(textoLimpio, items, s) {
    const cuerpo = String(textoLimpio || '').trim();
    const listaActual = items || [];

    // Si el borrador contiene el texto completo original de la API (con los medios integrados en su orden):
    const textoCompletoBorrador = (s && s.borrador && typeof s.borrador.texto === 'string')
      ? s.borrador.texto.trim()
      : ((s && s.coincidencias && s.coincidencias[0] && s.coincidencias[0].texto_original) ||
         (s && s.borrador && s.borrador.texto_original_aprobado) || '');

    const textoLimpioBase = (s && s.borrador && typeof s.borrador.texto_limpio === 'string')
      ? s.borrador.texto_limpio.trim()
      : '';

    const esBase = (!cuerpo || cuerpo === textoLimpioBase);

    // Cuando la persona no ha alterado el texto en el editor, la vista previa refleja exactamente el texto de la API
    if (textoCompletoBorrador && esBase) {
      let resultado = textoCompletoBorrador;
      const urlsActivas = new Set(listaActual.map((r) => String(r.referencia || '').trim()).filter(Boolean));
      const urlsOriginales = new Set();

      // Quitar del texto original los recursos que el usuario haya eliminado con la 'x'
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

      // Si el usuario agregó recursos nuevos en el mini panel, se agregan al final
      const recursosNuevos = listaActual.filter((r) => {
        const u = String(r.referencia || '').trim();
        return u && !urlsOriginales.has(u);
      });

      if (recursosNuevos.length > 0) {
        const bloqueNuevos = recursosNuevos.map(aMarkdown).join('\n\n');
        resultado = resultado ? resultado + '\n\n' + bloqueNuevos : bloqueNuevos;
      }

      return resultado.trim();
    }

    // Si el usuario modificó el texto en el editor (o es un artículo nuevo):
    if (!listaActual.length) return cuerpo;

    // Recursos que ya estén tipeados en el texto del editor no se duplican
    const recursosFaltantes = listaActual.filter((r) => {
      const ref = String(r.referencia || '').trim();
      return !ref || !cuerpo.includes(ref);
    });

    if (!recursosFaltantes.length) return cuerpo;
    const seccionNuevos = SECCION_RECURSOS_TITULO + '\n\n' + recursosFaltantes.map(aMarkdown).join('\n\n');
    return cuerpo ? cuerpo + '\n\n' + seccionNuevos : seccionNuevos;
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

  return { lista, habilitado, pintar, componerVistaPrevia, alternarCarga };
})();
