/* =============================================================
   Implementación REAL — backend de Caro (commit 237dcfb)
   -------------------------------------------------------------
   Endpoints (baco/server/app/api.py):

     POST /chat                      turno del orquestador
     GET  /chat/borrador             borrador aprobado y sanitizado
     POST /chat/aplicar-plantilla    skill 'plantillas'
     POST /chat/auditar-semantica    skill 'validador'

   Autenticación:  header  X-API-Key: <API_KEY_SERVIDOR>

   SESIÓN: el backend la gestiona. La devuelve en la cookie
   'baco_session' (httpOnly) y en el header 'X-Session-ID'.
   Como la cookie es cross-origin y los navegadores la bloquean
   cada vez más, acá se usa el header: se guarda el que llega y
   se reenvía en cada pedido. El `session_id` del cuerpo está
   deprecado y el backend lo ignora.
   ============================================================= */
window.BACO = window.BACO || {};

BACO.apiHttp = (function () {
  'use strict';

  let sessionId = null;

  function url(path) {
    return BACO.config.BASE_URL.replace(/\/$/, '') + path;
  }

  async function pedir(metodo, path, cuerpo) {
    if (!BACO.config.API_KEY) {
      const e = new Error('Falta la API_KEY en js/config.js. Pedísela a Caro (es el API_KEY_SERVIDOR del .env).');
      e.codigo = 'SIN_API_KEY';
      throw e;
    }

    const headers = { 'X-API-Key': BACO.config.API_KEY };
    if (sessionId) headers['X-Session-ID'] = sessionId;
    if (cuerpo !== undefined) headers['Content-Type'] = 'application/json';

    const init = {
      method: metodo,
      headers: headers,
      credentials: 'include'   // por si la cookie sí llega a viajar
    };
    if (cuerpo !== undefined) init.body = JSON.stringify(cuerpo);

    let res;
    try {
      res = await fetch(url(path), init);
    } catch (e) {
      const err = new Error('No se pudo contactar al backend. Revisá que esté levantado, que BASE_URL sea correcta y que el panel corra en el puerto 5173.');
      err.codigo = 'SIN_CONEXION';
      throw err;
    }

    /* El backend devuelve la sesión acá; es lo que hay que reenviar */
    const sid = res.headers.get('X-Session-ID');
    if (sid) sessionId = sid;

    let datos = null;
    try { datos = await res.json(); } catch (e) { /* sin cuerpo */ }

    if (!res.ok) {
      let mensaje = 'Error ' + res.status + ' del backend.';
      let codigo = 'HTTP_' + res.status;

      if (res.status === 401) {
        const detalle = datos && datos.detail ? String(datos.detail) : '';
        if (/sesi[oó]n/i.test(detalle)) {
          codigo = 'SIN_SESION';
          mensaje = 'La sesión expiró o no existe. Empezá de nuevo.';
          sessionId = null;
        } else {
          codigo = 'NO_AUTORIZADO';
          mensaje = 'El backend rechazó la API key. Revisá API_KEY en js/config.js.';
        }
      } else if (res.status === 422 && datos && datos.detail) {
        codigo = 'VALIDACION';
        mensaje = Array.isArray(datos.detail)
          ? datos.detail.map((d) => d.msg || JSON.stringify(d)).join(' · ')
          : String(datos.detail);
      } else if (datos && datos.detail) {
        mensaje = typeof datos.detail === 'string' ? datos.detail : JSON.stringify(datos.detail);
      }

      const err = new Error(mensaje);
      err.codigo = codigo;
      err.http = res.status;
      throw err;
    }

    return datos;
  }

  return {

    /* --------------------------------------------------------
       Un turno del orquestador.
       payload: { mensaje, accion, titulo, texto, categoria_id, tags }
       Devuelve: { session_id, estado, mensaje, opciones,
                   coincidencias, borrador, validacion,
                   aviso_privacidad }
       -------------------------------------------------------- */
    async turno(payload) {
      const cuerpo = Object.assign({}, payload || {});
      delete cuerpo.session_id;            // deprecado, el backend lo ignora
      const r = await pedir('POST', '/chat', cuerpo);
      /* Al rechazar, el backend borra la cookie: se descarta la sesión */
      if (r && r.estado === 'RECHAZADO') sessionId = null;
      return r;
    },

    /* Borrador aprobado y sanitizado de la sesión activa */
    borradorAprobado() {
      return pedir('GET', '/chat/borrador');
    },

    /* Skill 'plantillas': reestructura el borrador en su formato oficial.
       El backend toma el borrador de la sesión, no hace falta mandarlo. */
    aplicarPlantilla() {
      return pedir('POST', '/chat/aplicar-plantilla', {});
    },

    /* Skill 'validador': auditoría semántica y de estilo */
    auditarSemantica() {
      return pedir('POST', '/chat/auditar-semantica', {});
    },

    /* Para que el panel pueda mostrar / limpiar la sesión */
    sesionActual() { return sessionId; },
    olvidarSesion() { sessionId = null; }
  };
})();
