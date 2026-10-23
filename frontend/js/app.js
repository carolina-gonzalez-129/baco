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
  const nl2br = (s) => esc(s).replace(/\n/g, '<br>');
  let tToast = null;
  let ultimoFallo = null;   // para poder reintentar la llamada que falló

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
    const esperando = burbuja('bot', '<div class="typing"><i></i><i></i><i></i></div>');
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

      if (r.estado === 'APROBADO') mostrarAprobado();
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
    $('#meterFill').classList.toggle('full', s.flujo === 'APROBADO');
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
    $('#campoTags').classList.toggle('activo', !!act.tags);
    $('#tagBox').classList.toggle('off', !act.tags);

    if ($('#fTitulo').value !== s.form.titulo && document.activeElement !== $('#fTitulo')) {
      $('#fTitulo').value = s.form.titulo;
    }
    if ($('#fCuerpo').value !== s.form.texto && document.activeElement !== $('#fCuerpo')) {
      $('#fCuerpo').value = s.form.texto;
    }

    /* Contadores */
    contador($('#contTitulo'), s.form.titulo.length, cfg.MIN_TITULO, 'caracteres', cfg.MAX_TITULO);
    contador($('#contTexto'),  s.form.texto.length,  cfg.MIN_TEXTO,  'caracteres', cfg.MAX_TEXTO);
    contador($('#contTags'),   s.form.tags.length,   cfg.MIN_TAGS,   'etiquetas', cfg.MAX_TAGS);

    /* botón principal */
    const acc = BACO.ACCION_PRINCIPAL[s.flujo];
    const btn = $('#btnPrincipal');
    if (acc) {
      btn.hidden = false;
      btn.disabled = s.enviando || !listoParaEnviar(s, acc.campo);
      btn.textContent = (acc.campo === 'todo' && !hayCambios(s))
        ? 'Sin cambios para guardar'
        : acc.label;
      btn.title = btn.disabled && acc.campo === 'todo'
        ? 'Editá algún campo para habilitar el guardado' : '';
    } else {
      btn.hidden = true;
    }

    pintarTags(s);
    pintarCategorias(s, !!act.categoria && !s.enviando);
    pintarResumenFinal(s);
    pintarBorrador(s);
    pintarCoincidencias(s);
    pintarValidacion(s);
    pintarOpciones(s);
  }

  function pintarStepper(s, etapaActual) {
    const cont = $('#pasos');
    if (!cont) return;
    const nombres = (s.etapa && Array.isArray(s.etapa.etapas) && s.etapa.etapas.length)
      ? s.etapa.etapas
      : ['Título y duplicados', 'Contenido', 'Plantilla y etiquetas', 'Revisión', 'Aprobación'];

    if (cont.children.length !== nombres.length) {
      cont.innerHTML = '';
      nombres.forEach((nom, idx) => {
        cont.appendChild(el('div', 'paso', '<span class="pn">' + (idx + 1) + '</span> ' + esc(nom)));
      });
    }

    Array.prototype.forEach.call(cont.querySelectorAll('.paso'), (nodo, i) => {
      const n = i + 1;
      const completado = (s.flujo === 'APROBADO') ? true : (n < etapaActual);
      const activo = (s.flujo !== 'APROBADO') && (n === etapaActual);
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
      : [{ id: Number(s.form.categoria_id) || 1, nombre: 'Categoría ' + (Number(s.form.categoria_id) || 1) }];

    const actualId = Number(s.form.categoria_id) || 1;
    const tieneActual = cats.some((c) => Number(c.id) === actualId);
    const opcionesSelect = tieneActual
      ? cats
      : [{ id: actualId, nombre: 'Categoría ' + actualId }].concat(cats);

    sel.innerHTML = opcionesSelect.map((c) =>
      '<option value="' + esc(c.id) + '"' + (Number(c.id) === actualId ? ' selected' : '') + '>' +
      esc(c.nombre) + '</option>'
    ).join('');
    sel.value = String(actualId);

    chipsRow.innerHTML = '';
    if (!s.categorias_disponibles || !s.categorias_disponibles.length) return;

    chipsRow.appendChild(el('span', 'cap', 'Categorías'));
    s.categorias_disponibles.forEach((c) => {
      const activo = Number(c.id) === actualId;
      const chip = el('button', 'sugg cat-chip' + (activo ? ' on' : ''), esc(c.nombre));
      chip.type = 'button';
      chip.disabled = !habilitado;
      chip.onclick = () => {
        store.setForm({ categoria_id: Number(c.id) });
      };
      chipsRow.appendChild(chip);
    });
  }

  function pintarResumenFinal(s) {
    const slot = $('#slotResumenFinal');
    if (!slot) return;
    if (s.flujo !== 'APROBADO' || !s.borrador) {
      slot.innerHTML = '';
      return;
    }
    const b = s.borrador;
    const tags = (s.tags_acumulados && s.tags_acumulados.length) ? s.tags_acumulados : (b.tags || []);
    const etapaTxt = (s.etapa ? (s.etapa.actual + ' de ' + s.etapa.total + ' (' + s.etapa.nombre + ')') : '5 de 5 (Aprobación)');
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

  function listoParaEnviar(s, campo) {
    if (campo === 'titulo') return s.form.titulo.trim().length >= cfg.MIN_TITULO;
    if (campo === 'texto')  return s.form.texto.trim().length >= cfg.MIN_TEXTO;
    if (campo === 'tags')   return s.form.tags.length >= cfg.MIN_TAGS;
    if (campo === 'todo') return hayCambios(s);
    return true;
  }

  function hayCambios(s) {
    const b = s.borrador;
    if (!b) return true;
    const mismosTags = (b.tags || []).length === s.form.tags.length &&
      (b.tags || []).every((t, i) => t === s.form.tags[i]);
    return s.form.titulo !== b.titulo ||
           s.form.texto !== b.texto ||
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
      return enviarTurno({ accion: 'reiniciar' });
    }
    enviarTurno({ accion: op }, label);
  }

  function enviarPrincipal() {
    const s = store.get();
    const acc = BACO.ACCION_PRINCIPAL[s.flujo];
    if (!acc) return;

    if (acc.campo === 'titulo') return enviarTurno({ titulo: s.form.titulo }, s.form.titulo);
    if (acc.campo === 'texto')  return enviarTurno({ texto: s.form.texto }, 'Envié el contenido (' + s.form.texto.length + ' caracteres)');
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

  /* ---- borrador aprobado ---- */
  async function mostrarAprobado() {
    const s = store.get();
    try {
      const b = await api.borradorAprobado();
      const tagsFinales = (s.tags_acumulados && s.tags_acumulados.length)
        ? s.tags_acumulados
        : (b.tags || []);
      const etapaFinal = s.etapa
        ? ('Etapa ' + s.etapa.actual + ' de ' + s.etapa.total + ' · ' + s.etapa.nombre)
        : 'Etapa 5 de 5 · Aprobación';
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
    if (opciones && opciones.length) {
      const cont = el('div', 'acciones');
      opciones.forEach((op) => {
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
    if (s.flujo === 'ESPERANDO_TEXTO')   return enviarTurno({ texto: v }, v);
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

  /* Markdown mínimo para la vista previa */
  function renderMd(src) {
    const ln = (s) => esc(s).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
    const out = []; let lista = null;
    const cerrar = () => { if (lista) { out.push('</' + lista + '>'); lista = null; } };
    String(src).split('\n').forEach((raw) => {
      const l = raw.trim();
      if (!l) { cerrar(); return; }
      if (/^ruta\s*[:>]/i.test(l)) { cerrar(); out.push('<div class="ruta">' + ln(l) + '</div>'); return; }
      if (/^#{1,4}\s/.test(l)) { cerrar(); out.push('<h4>' + ln(l.replace(/^#+\s*/, '')) + '</h4>'); return; }
      if (/^>\s?/.test(l)) { cerrar(); out.push('<blockquote>' + ln(l.replace(/^>\s?/, '')) + '</blockquote>'); return; }
      if (/^\|/.test(l)) { cerrar(); out.push('<div class="tabla">' + ln(l) + '</div>'); return; }
      if (/^\d+[.)]\s/.test(l)) { if (lista !== 'ol') { cerrar(); out.push('<ol>'); lista = 'ol'; } out.push('<li>' + ln(l.replace(/^\d+[.)]\s*/, '')) + '</li>'); return; }
      if (/^[-*]\s/.test(l)) { if (lista !== 'ul') { cerrar(); out.push('<ul>'); lista = 'ul'; } out.push('<li>' + ln(l.replace(/^[-*]\s*/, '')) + '</li>'); return; }
      cerrar(); out.push('<p>' + ln(l) + '</p>');
    });
    cerrar();
    return out.join('') || '<p class="vacio">Todavía no hay contenido.</p>';
  }

  /* =========================================================
     Eventos
     ========================================================= */
  function conectarEventos() {
    $('#fTitulo').addEventListener('input', (e) => store.setForm({ titulo: e.target.value }));
    $('#fCuerpo').addEventListener('input', (e) => store.setForm({ texto: e.target.value }));
    $('#fCategoria').addEventListener('change', (e) => store.setForm({ categoria_id: parseInt(e.target.value, 10) || 1 }));

    $('#fTitulo').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); if (!$('#btnPrincipal').disabled) enviarPrincipal(); }
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

    $('#btnEditor').onclick = () => {
      $('#fCuerpo').hidden = false; $('#preview').hidden = true;
      $('#btnEditor').classList.add('sel'); $('#btnPreview').classList.remove('sel');
    };
    $('#btnPreview').onclick = () => {
      $('#preview').innerHTML = renderMd(store.get().form.texto);
      $('#fCuerpo').hidden = true; $('#preview').hidden = false;
      $('#btnPreview').classList.add('sel'); $('#btnEditor').classList.remove('sel');
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
        toast('Documento volcado en el editor');
      };
      lector.readAsText(f);
    });

    $('#btnPlantilla').onclick = aplicarPlantilla;
    $('#btnAuditar').onclick = auditar;

    $('#btnReiniciar').onclick = () => accionar('reiniciar', 'Empezar de nuevo');
    $('#btnEjemplo').onclick = cargarEjemplo;

    $('#btnCerrar').onclick = () => { $('#overlay').hidden = true; };
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
      $('#fCuerpo').value = c; store.setForm({ texto: c });
      toast('Contenido de ejemplo cargado');
    } else {
      toast('El ejemplo se carga en los pasos de título y contenido');
    }
  }

  iniciar();
})();
