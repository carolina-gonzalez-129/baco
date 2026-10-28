/* =============================================================
   BACO — Vista de Artículo Final (Solo Lectura)
   -------------------------------------------------------------
   - Lee el borrador directamente del servidor por session_id
   - Renderiza Título, Categoría y Etiquetas arriba
   - Divide el contenido en secciones en orden estricto:
       Encabezado (clase .encabezado-articulo)
       Texto
       Imagen(es) (si tiene, en orden)
   - Sin controles de edición ni formularios
   - Mensajes claros si no existe o está vacío
   ============================================================= */
(async function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function mostrarMensaje(titulo, detalle) {
    const estadoCarga = document.getElementById('estadoCarga');
    if (estadoCarga) estadoCarga.hidden = true;
    const articuloContenido = document.getElementById('articuloContenido');
    if (articuloContenido) articuloContenido.hidden = true;
    const mensajeEstado = document.getElementById('mensajeEstado');
    if (mensajeEstado) {
      mensajeEstado.innerHTML =
        '<div class="articulo-aviso-vacio">' +
          '<h3>' + esc(titulo) + '</h3>' +
          '<p>' + esc(detalle) + '</p>' +
        '</div>';
      mensajeEstado.hidden = false;
    }
  }

  function resolverUrlRecurso(url, baseUrl) {
    if (!url) return '';
    const u = String(url).trim();
    if (u.startsWith('http://') || u.startsWith('https://') || u.startsWith('data:')) {
      return u;
    }
    const base = baseUrl.replace(/\/$/, '');
    if (u.startsWith('/')) {
      return base + u;
    }
    return base + '/' + u;
  }

  /* Renderizador seguro de Markdown liviano para el texto de cada sección */
  function renderMarkdownTexto(src) {
    if (!src) return '';

    const lineas = String(src).split('\n');
    const out = [];
    let enListaUl = false;
    let enListaOl = false;
    let enBloqueCodigo = false;
    let lineasCodigo = [];

    const cerrarListas = () => {
      if (enListaUl) { out.push('</ul>'); enListaUl = false; }
      if (enListaOl) { out.push('</ol>'); enListaOl = false; }
    };

    const formatearEnLinea = (texto) => {
      let t = esc(texto);
      // Enlaces: [texto](url)
      t = t.replace(/\[([^\]]+)\]\((https?:\/\/[^\s\)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1 ↗</a>');
      // Negrita: **texto**
      t = t.replace(/\*\*([^\*]+)\*\*/g, '<strong>$1</strong>');
      // Cursiva: *texto*
      t = t.replace(/\*([^\*]+)\*/g, '<em>$1</em>');
      // Código en línea: `codigo`
      t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
      return t;
    };

    for (let i = 0; i < lineas.length; i++) {
      const linea = lineas[i];
      const trim = linea.trim();

      if (trim.startsWith('```')) {
        cerrarListas();
        if (enBloqueCodigo) {
          out.push('<pre><code>' + esc(lineasCodigo.join('\n')) + '</code></pre>');
          lineasCodigo = [];
          enBloqueCodigo = false;
        } else {
          enBloqueCodigo = true;
          lineasCodigo = [];
        }
        continue;
      }

      if (enBloqueCodigo) {
        lineasCodigo.push(linea);
        continue;
      }

      if (!trim) {
        cerrarListas();
        continue;
      }

      // Citas
      if (trim.startsWith('>')) {
        cerrarListas();
        out.push('<blockquote>' + formatearEnLinea(trim.replace(/^>\s*/, '')) + '</blockquote>');
        continue;
      }

      // Listas desordenadas
      if (/^[-*]\s+/.test(trim)) {
        if (!enListaUl) {
          cerrarListas();
          enListaUl = true;
          out.push('<ul>');
        }
        out.push('<li>' + formatearEnLinea(trim.replace(/^[-*]\s+/, '')) + '</li>');
        continue;
      }

      // Listas ordenadas
      if (/^\d+\.\s+/.test(trim)) {
        if (!enListaOl) {
          cerrarListas();
          enListaOl = true;
          out.push('<ol>');
        }
        out.push('<li>' + formatearEnLinea(trim.replace(/^\d+\.\s+/, '')) + '</li>');
        continue;
      }

      // Sub-encabezados dentro del texto (ej. ### o ####)
      if (/^#{3,6}\s+/.test(trim)) {
        cerrarListas();
        const subTtl = trim.replace(/^#{3,6}\s+/, '');
        out.push('<h4 style="margin:14px 0 6px 0; font-size:15px; font-weight:700; color:var(--ink);">' + formatearEnLinea(subTtl) + '</h4>');
        continue;
      }

      // Párrafo normal
      cerrarListas();
      out.push('<p>' + formatearEnLinea(trim) + '</p>');
    }

    cerrarListas();
    if (enBloqueCodigo && lineasCodigo.length) {
      out.push('<pre><code>' + esc(lineasCodigo.join('\n')) + '</code></pre>');
    }

    return out.join('');
  }

  /* Extrae imágenes de un texto en Markdown y devuelve el texto limpio y las imágenes */
  function extraerImagenesDeMarkdown(textoMd, baseUrl) {
    const imagenes = [];
    if (!textoMd) return { textoLimpio: '', imagenes: imagenes };

    const regexImg = /!\[([^\]]*)\]\(((?:https?:\/\/|\/api\/recursos-temp\/)[^\s\)]+)\)/g;
    let match;
    while ((match = regexImg.exec(textoMd)) !== null) {
      imagenes.push({
        nombre: match[1] || 'Imagen',
        url: resolverUrlRecurso(match[2], baseUrl)
      });
    }

    // Remueve las marcas de imágenes del texto para que no se dupliquen dentro del texto
    const limpio = textoMd.replace(regexImg, '').replace(/\n{3,}/g, '\n\n').trim();
    return { textoLimpio: limpio, imagenes: imagenes };
  }

  /* Parsea el borrador en secciones estructuradas */
  function parsearSecciones(borrador, baseUrl) {
    const secciones = [];
    const textoAlineado = (borrador.texto_alineado_discourse || '').trim();
    const bloques = Array.isArray(borrador.bloques_texto) ? borrador.bloques_texto : [];
    const recursosList = Array.isArray(borrador.multimedia)
      ? borrador.multimedia
      : Object.values(borrador.recursos || {});

    // Mapeo de recursos multimedia de tipo imagen ordenados
    const recursosImg = recursosList
      .filter((r) => r.tipo === 'imagen' || /\.(png|jpe?g|gif|webp|bmp)($|\?)/i.test(r.referencia || ''))
      .sort((a, b) => ((a.posicion ?? 0) - (b.posicion ?? 0)) || ((a.orden ?? 0) - (b.orden ?? 0)));

    // Estrategia 1: Si el texto contiene encabezados Markdown (# Encabezado o ## Encabezado)
    const textoFuente = textoAlineado || bloques.join('\n\n');
    const lineas = textoFuente.split('\n');
    const tieneEncabezadosMd = lineas.some((l) => /^#{1,2}\s+\S+/.test(l.trim()));

    if (tieneEncabezadosMd) {
      let encabezadoActual = '';
      let lineasSeccion = [];

      const guardarSeccion = () => {
        const contenidoSeccion = lineasSeccion.join('\n').trim();
        if (encabezadoActual || contenidoSeccion) {
          const { textoLimpio, imagenes } = extraerImagenesDeMarkdown(contenidoSeccion, baseUrl);
          secciones.push({
            encabezado: encabezadoActual,
            texto: textoLimpio,
            imagenes: imagenes
          });
        }
        lineasSeccion = [];
      };

      for (let i = 0; i < lineas.length; i++) {
        const linea = lineas[i];
        const matchH = linea.trim().match(/^#{1,2}\s+(.+)$/);
        if (matchH) {
          guardarSeccion();
          encabezadoActual = matchH[1].trim();
        } else {
          lineasSeccion.push(linea);
        }
      }
      guardarSeccion();

      return secciones.filter((s) => s.encabezado || s.texto || (s.imagenes && s.imagenes.length));
    }

    // Estrategia 2: Por bloques de texto si no hay encabezados Markdown
    if (bloques.length > 0) {
      bloques.forEach((bloqueStr, idx) => {
        const b = String(bloqueStr || '').trim();
        if (!b) return;

        // Separar primera línea como encabezado si hay salto de línea
        const partesBloque = b.split('\n');
        let enc = '';
        let rest = '';

        if (partesBloque.length > 0 && /^#+\s+/.test(partesBloque[0].trim())) {
          enc = partesBloque[0].replace(/^#+\s*/, '').trim();
          rest = partesBloque.slice(1).join('\n').trim();
        } else {
          enc = '';
          rest = b;
        }

        const { textoLimpio, imagenes: imgsMd } = extraerImagenesDeMarkdown(rest, baseUrl);

        // Sumar recursos asociados a este bloque (posicion === idx)
        const imgsRecursos = recursosImg
          .filter((r) => (r.posicion ?? 0) === idx)
          .map((r) => ({
            nombre: r.nombre || 'Imagen',
            url: resolverUrlRecurso(r.referencia || r.url, baseUrl)
          }));

        // Unir evitando URLs duplicadas
        const urlsVistas = new Set();
        const imagenesFinales = [];
        [...imgsMd, ...imgsRecursos].forEach((img) => {
          if (img.url && !urlsVistas.has(img.url)) {
            urlsVistas.add(img.url);
            imagenesFinales.push(img);
          }
        });

        secciones.push({
          encabezado: enc,
          texto: textoLimpio,
          imagenes: imagenesFinales
        });
      });

      return secciones;
    }

    // Estrategia 3: Fallback si solo hay texto plano
    if (textoFuente) {
      const { textoLimpio, imagenes } = extraerImagenesDeMarkdown(textoFuente, baseUrl);
      secciones.push({
        encabezado: '',
        texto: textoLimpio,
        imagenes: imagenes
      });
    }

    return secciones;
  }

  /* -----------------------------------------------------------
     Inicio de la página
     ----------------------------------------------------------- */
  const params = new URLSearchParams(window.location.search);
  const sessionId = params.get('session_id') || params.get('sid') || '';

  if (!sessionId) {
    mostrarMensaje(
      'Falta identificar la sesión',
      'No se especificó un ID de sesión en la URL (?session_id=...). Para visualizar el artículo final, accedé a través del botón en el chat de BACO.'
    );
    return;
  }

  const sesionIndicador = document.getElementById('sesionIndicador');
  if (sesionIndicador) {
    sesionIndicador.textContent = 'sesión ' + sessionId.slice(0, 8);
  }

  const baseUrl = (window.BACO && window.BACO.config && window.BACO.config.BASE_URL)
    ? window.BACO.config.BASE_URL.replace(/\/$/, '')
    : 'http://127.0.0.1:8080';
  const apiKey = (window.BACO && window.BACO.config && window.BACO.config.API_KEY)
    ? window.BACO.config.API_KEY
    : '';

  const headers = {};
  if (apiKey) headers['X-API-Key'] = apiKey;
  headers['X-Session-ID'] = sessionId;

  let borrador = null;

  function obtenerBorradorSesionExistente() {
    try {
      const padre = window.opener || window.parent;
      if (padre && padre !== window && padre.BACO && padre.BACO.store) {
        const sOp = padre.BACO.store.get();
        if (sOp && sOp.borrador && (!sessionId || sOp.session_id === sessionId)) {
          return sOp.borrador;
        }
      }
    } catch (_) {}
    return null;
  }

  try {
    const res = await fetch(baseUrl + '/chat/borrador', {
      method: 'GET',
      headers: headers,
      credentials: 'include'
    });

    if (res.status === 404) {
      borrador = obtenerBorradorSesionExistente();
      if (!borrador) {
        mostrarMensaje(
          'Borrador no encontrado',
          `No existe un borrador para la sesión '${sessionId}' o la sesión expiró.`
        );
        return;
      }
    } else if (res.status === 409) {
      borrador = obtenerBorradorSesionExistente();
      if (!borrador) {
        let detalle = 'El borrador todavía no cuenta con conformidad registrada.';
        try {
          const errJson = await res.json();
          if (errJson && errJson.detail) detalle = errJson.detail;
        } catch (_) {}
        mostrarMensaje(
          'Artículo no finalizado',
          detalle + ' Para visualizarlo como artículo final, registrá tu conformidad en el chat.'
        );
        return;
      }
    } else if (res.status === 401) {
      mostrarMensaje(
        'Acceso no autorizado',
        'El servidor rechazó la solicitud. Verificá la clave API en config.js.'
      );
      return;
    } else if (!res.ok) {
      borrador = obtenerBorradorSesionExistente();
      if (!borrador) {
        let detalle = `Error HTTP ${res.status}`;
        try {
          const errJson = await res.json();
          if (errJson && errJson.detail) detalle = errJson.detail;
        } catch (_) {}
        mostrarMensaje('Error al obtener el borrador', detalle);
        return;
      }
    } else {
      borrador = await res.json();
    }
  } catch (err) {
    borrador = obtenerBorradorSesionExistente();
    if (!borrador) {
      mostrarMensaje(
        'Error de conexión',
        `No se pudo conectar con el servidor en ${baseUrl}. Comprobá que esté iniciado.`
      );
      return;
    }
  }

  // Validación de borrador vacío
  if (!borrador) {
    mostrarMensaje('Borrador inexistente', 'El servidor no devolvió datos del borrador.');
    return;
  }

  const titulo = (borrador.titulo || '').trim();
  const textoLimpio = (borrador.texto_limpio || '').trim();
  const textoDiscourse = (borrador.texto_alineado_discourse || '').trim();
  const bloques = Array.isArray(borrador.bloques_texto) ? borrador.bloques_texto : [];

  const estaVacio = !titulo && !textoLimpio && !textoDiscourse && bloques.every((b) => !String(b || '').trim());
  if (estaVacio) {
    mostrarMensaje('Borrador vacío', 'El borrador existe pero no contiene título ni cuerpo para mostrar.');
    return;
  }

  // Renderizar metadatos arriba
  const tituloEl = document.getElementById('articuloTitulo');
  if (tituloEl) tituloEl.textContent = titulo || 'Artículo sin título';

  // Categoría
  let nombreCat = 'Sin categoría';
  if (borrador.categoria_nombre) {
    nombreCat = borrador.categoria_nombre;
  } else if (borrador.categoria_id) {
    const catId = borrador.categoria_id;
    if (window.BACO && window.BACO.datos && Array.isArray(window.BACO.datos.categorias)) {
      const encontrada = window.BACO.datos.categorias.find((c) => Number(c.id) === Number(catId));
      if (encontrada) nombreCat = encontrada.nombre;
      else nombreCat = 'Categoría ' + catId;
    } else {
      nombreCat = 'Categoría ' + catId;
    }
  }
  const catEl = document.getElementById('articuloCategoria');
  if (catEl) catEl.textContent = nombreCat;

  // Tags
  const tagsEl = document.getElementById('articuloTags');
  if (tagsEl) {
    tagsEl.innerHTML = '';
    const tags = Array.isArray(borrador.tags) ? borrador.tags : [];
    if (tags.length) {
      tags.forEach((t) => {
        const chip = document.createElement('span');
        chip.className = 'tag';
        chip.textContent = t;
        tagsEl.appendChild(chip);
      });
    } else {
      const vacio = document.createElement('span');
      vacio.className = 'articulo-meta-label';
      vacio.textContent = 'Sin etiquetas';
      tagsEl.appendChild(vacio);
    }
  }

  // Secciones
  const secciones = parsearSecciones(borrador, baseUrl);
  const contSecciones = document.getElementById('articuloSecciones');
  if (contSecciones) {
    contSecciones.innerHTML = '';

    if (!secciones.length) {
      mostrarMensaje('Borrador sin contenido', 'No hay secciones disponibles en el artículo.');
      return;
    }

    secciones.forEach((sec) => {
      const secEl = document.createElement('section');
      secEl.className = 'articulo-seccion';

      // 1. Encabezado con clase única .encabezado-articulo (solo si hay encabezado explícito)
      const encLimpio = (sec.encabezado || '').trim();
      if (encLimpio && !/^secci[oó]n(\s*\d+)?$/i.test(encLimpio)) {
        const h = document.createElement('h2');
        h.className = 'encabezado-articulo';
        h.textContent = encLimpio;
        secEl.appendChild(h);
      }

      // 2. Texto
      if (sec.texto) {
        const txtEl = document.createElement('div');
        txtEl.className = 'articulo-texto';
        txtEl.innerHTML = renderMarkdownTexto(sec.texto);
        secEl.appendChild(txtEl);
      }

      // 3. Imagen(es) si tiene (en orden estricto)
      if (sec.imagenes && sec.imagenes.length) {
        const imgsWrap = document.createElement('div');
        imgsWrap.className = 'articulo-imagenes';

        sec.imagenes.forEach((img) => {
          const figure = document.createElement('figure');
          figure.className = 'articulo-img-box';

          const imgTag = document.createElement('img');
          imgTag.className = 'articulo-img';
          imgTag.src = img.url;
          imgTag.alt = img.nombre || 'Imagen del artículo';
          imgTag.loading = 'lazy';
          figure.appendChild(imgTag);

          if (img.nombre && img.nombre !== img.url && img.nombre !== 'Imagen') {
            const cap = document.createElement('figcaption');
            cap.className = 'articulo-img-caption';
            cap.textContent = img.nombre;
            figure.appendChild(cap);
          }

          imgsWrap.appendChild(figure);
        });

        secEl.appendChild(imgsWrap);
      }

      contSecciones.appendChild(secEl);
    });
  }

  const estadoCarga = document.getElementById('estadoCarga');
  if (estadoCarga) estadoCarga.hidden = true;
  const articuloContenido = document.getElementById('articuloContenido');
  if (articuloContenido) articuloContenido.hidden = false;
})();
