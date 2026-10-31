/* =============================================================
   Configuración del panel
   -------------------------------------------------------------
   Alineado con el backend de Caro al commit 237dcfb (22/10/2026).

###ELIMINAR O READAPTAR
   ============================================================= */
window.BACO = window.BACO || {};

BACO.config = {

  /* 'mock' = simulado en el navegador · 'http' = backend de Caro */
  MODO: 'http',

  BASE_URL: 'http://127.0.0.1:8080',

  /* API_KEY_SERVIDOR del .env del backend. Sin esto, t odo da 401. */
  API_KEY: 'Ojalaaprobemos123',

  /* ---- Límites del backend (baco/server/config_limites.py) ---- */
  MIN_TITULO: 15,
  MAX_TITULO: 255,
  MIN_TEXTO: 20,
  MAX_TEXTO: 6687,                  // Límite máximo para uso de skills / agente
  MAX_TEXTO_PERCENTIL_99: 150000,    //  CAMBIO A MAXIMO DEFAULT DE DISCOURSE, HAY Q HABLAR CON ELLOS Q PREFIEREN
  MIN_TAGS: 2,
  MAX_TAGS: 5,         // límite habitual de Discourse

};
