/* =============================================================
   Fachada de la API
   -------------------------------------------------------------
   ES EL ÚNICO PUNTO POR DONDE LA UI HABLA CON EL BACKEND.
   Elige entre la implementación simulada y la real según
   config.MODO. La UI llama siempre a BACO.api.loQueSea().

   Si algún día hace falta un tercer modo (grabado, pruebas),
   se agrega acá y la UI sigue sin enterarse.
   ============================================================= */
window.BACO = window.BACO || {};

BACO.api = (function () {
  'use strict';

  const impl = BACO.config.MODO === 'http' ? BACO.apiHttp : BACO.apiMock;

  /* Envoltorio: deja un rastro en consola de cada llamada.
     Sirve para depurar y, cuando se conecte el backend real,
     para ver exactamente qué pide el panel. */
  function trazar(nombre, fn) {
    return function () {
      const args = Array.prototype.slice.call(arguments);
      const t0 = performance.now();
      const etiqueta = '[api:' + BACO.config.MODO + '] ' + nombre;

      return Promise.resolve(fn.apply(impl, args))
        .then((r) => {
          console.debug(etiqueta, '→', Math.round(performance.now() - t0) + 'ms', r);
          return r;
        })
        .catch((e) => {
          console.warn(etiqueta, '✗', e.codigo || 'ERROR', e.message);
          throw e;
        });
    };
  }

  const fachada = {};
  Object.keys(impl).forEach((nombre) => {
    fachada[nombre] = trazar(nombre, impl[nombre]);
  });

  fachada.modo = BACO.config.MODO;
  fachada.esMock = BACO.config.MODO !== 'http';

  return fachada;
})();
