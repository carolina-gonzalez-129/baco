/* =============================================================
   Configuración del panel
   -------------------------------------------------------------
   Alineado con el backend de Caro al commit 237dcfb (22/10/2026).

   PARA CONECTAR AL BACKEND:
     1. MODO: 'http'
     2. BASE_URL: la URL del backend (local o túnel de cloudflared)
     3. API_KEY: el valor de API_KEY_SERVIDOR que te pase Caro

   ⚠ EL PANEL TIENE QUE CORRER EN EL PUERTO 5173.
   El backend solo acepta estos orígenes por CORS:
     localhost:3000 · localhost:5173 · 127.0.0.1:3000 · 127.0.0.1:5173
   (salvo que Caro agregue otro en la variable CORS_ORIGINS de su .env)
   ============================================================= */
window.BACO = window.BACO || {};

BACO.config = {

  /* 'mock' = simulado en el navegador · 'http' = backend de Caro */
  MODO: 'http',

  /* Túnel de Caro: 'https://algo.trycloudflare.com'
     Local:         'http://127.0.0.1:8080'            */
  BASE_URL: 'http://127.0.0.1:8080',

  /* API_KEY_SERVIDOR del .env del backend. Sin esto, todo da 401. */
  API_KEY: 'Ojalaaprobemos123',

  /* ---- Límites del backend (baco/server/config_limites.py) ---- */
  MIN_TITULO: 15,
  MAX_TITULO: 255,
  MIN_TEXTO: 20,
  MAX_TEXTO: 6687,     // percentil 95 del largo de los artículos
  MIN_TAGS: 2,
  MAX_TAGS: 5,         // límite habitual de Discourse

  /* ---- Solo para el mock ---- */
  mock: {
    LATENCIA_MS: 420,
    LATENCIA_AGENTE_MS: 2600,
    TASA_ERROR: 0        // subir a 0.3 para probar los estados de error
  }
};
