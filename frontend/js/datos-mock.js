/* =============================================================
   Datos del mock
   -------------------------------------------------------------
   Nada de esto existe en producción: es la Base de Conocimiento
   simulada contra la que corre el panel mientras no haya backend.
   Modelado sobre los catálogos y plantillas reales que mandó
   Finnegans.
   ============================================================= */
window.BACO = window.BACO || {};

BACO.datos = {

  /* ---- Categorías: listado fijo, el usuario no puede crear ---- */
  categorias: [
    { id: 37,  nombre: 'Agro' },
    { id: 25,  nombre: 'App Builder' },
    { id: 94,  nombre: 'Comercializadoras' },
    { id: 48,  nombre: 'Comercialización de granos' },
    { id: 24,  nombre: 'Compras' },
    { id: 115, nombre: 'Constructoras' },
    { id: 21,  nombre: 'Contabilidad' },
    { id: 62,  nombre: 'GO' },
    { id: 39,  nombre: 'HCM' },
    { id: 23,  nombre: 'Impuestos Argentina' },
    { id: 19,  nombre: 'Inventarios' },
    { id: 67,  nombre: 'México' },
    { id: 82,  nombre: 'Paraguay' },
    { id: 81,  nombre: 'Perú' },
    { id: 129, nombre: 'Readme' },
    { id: 65,  nombre: 'Recursos de conocimiento' },
    { id: 63,  nombre: 'Soporte técnico' },
    { id: 22,  nombre: 'Tesorería' },
    { id: 83,  nombre: 'Uruguay' },
    { id: 20,  nombre: 'Ventas' },
    { id: 61,  nombre: 'Videos Cómo se hace' }
  ],

  /* ---- Etiquetas ---- */
  etiquetas: [
    // tipo de documentación — una es obligatoria
    { tag: 'instructivo',          usos: 1299, es_tipo_documentacion: true,  tiene_plantilla: true },
    { tag: 'cómo-se-hace',         usos: 1097, es_tipo_documentacion: true,  tiene_plantilla: false },
    { tag: 'soluciones',           usos: 834,  es_tipo_documentacion: true,  tiene_plantilla: true },
    { tag: 'videos-cómo-se-hace',  usos: 126,  es_tipo_documentacion: true,  tiene_plantilla: true },
    { tag: 'documento-de-alcance', usos: 111,  es_tipo_documentacion: true,  tiene_plantilla: true },
    { tag: 'maestro',              usos: 59,   es_tipo_documentacion: true,  tiene_plantilla: false },
    { tag: 'localización',         usos: 33,   es_tipo_documentacion: true,  tiene_plantilla: false },
    { tag: 'pautas-de-uso',        usos: 22,   es_tipo_documentacion: true,  tiene_plantilla: false },
    { tag: 'gestión-de-negocios',  usos: 13,   es_tipo_documentacion: true,  tiene_plantilla: false },
    { tag: 'primeros-pasos',       usos: 10,   es_tipo_documentacion: true,  tiene_plantilla: false },
    { tag: 'prompt',               usos: 10,   es_tipo_documentacion: true,  tiene_plantilla: false },
    // temáticas
    { tag: 'agro', usos: 455 }, { tag: 'erp', usos: 380 }, { tag: 'ventas', usos: 350 },
    { tag: 'arca', usos: 151 }, { tag: 'factura-de-venta', usos: 79 }, { tag: 'api', usos: 62 },
    { tag: 'granos', usos: 53 }, { tag: 'ia', usos: 52 }, { tag: 'liquidacion-granos', usos: 49 },
    { tag: 'importación', usos: 46 }, { tag: 'planificación-agrícola', usos: 43 },
    { tag: 'stock', usos: 39 }, { tag: 'crm', usos: 37 }, { tag: 'bproc', usos: 36 },
    { tag: 'integraciones', usos: 32 }, { tag: 'cpe', usos: 31 }, { tag: 'riego', usos: 18 },
    { tag: 'lotes', usos: 8 }, { tag: 'sensores', usos: 6 }, { tag: 'humedad-de-suelo', usos: 4 },
    { tag: 'sequía', usos: 3 },
    { tag: 'generado-con-ia', usos: 479 }, { tag: 'generado-con-skill', usos: 4 }
  ],

  /* ---- Plantillas reales publicadas en la BC ---- */
  plantillas: {
    'soluciones': `**Consulta:**

Ruta> [Indicar la ruta de acceso que llevó al mensaje de error]

[Describir la consulta o problema y las acciones que lo produjeron, en tiempo presente:
1. ¿Qué pasa? ¿Cuál es el problema a resolver?
2. ¿Dónde o cuándo ocurre? ¿Qué acciones dan error?
3. ¿Cómo sucede? ¿Qué mensaje sale?]

**Respuesta:**

[Explicar por qué sucede ese inconveniente y qué lo originó.]

**Pasos a seguir:**

Ruta> [Indicar la ruta desde donde acceder a la solución]

1. [Acción 1]
2. [Acción 2]
3. [Acción 3]

Requiere AppBuilder [Indicar en negrita solo si aplica. Si no, BORRAR esta línea]`,

    'instructivo': `[Breve descripción de la funcionalidad o procedimiento]

**Antes de empezar**

[Configuraciones iniciales en los maestros y componentes del sistema. Verbos en infinitivo.]

**Modo de uso**

Ruta> Menú > Gestión Empresarial > [Funcionalidad]

1. [Completar los parámetros]
2. [Describir las acciones con verbos en infinitivo]
3. [Cada acción es un paso]

[Los campos marcados con asterisco (*) son obligatorios.]`,

    'documento-de-alcance': `[Breve descripción de la funcionalidad o producto]

**¿Para qué sirve?**

> [Explicar para qué sirve la funcionalidad y el paso a paso a desarrollar.]

**Antes de empezar**

[Configuraciones iniciales en los distintos maestros y componentes.]

**Modo de uso**

Ruta> Menú > Gestión Empresarial > [Funcionalidad]

1. [Completar los parámetros]
2. [Describir las acciones con verbos en infinitivo]`,

    'videos-cómo-se-hace': `En este video vamos a ver...

**¿Quiénes pueden hacerlo?**

[Indicar perfiles o permisos necesarios]

> Recomendamos reproducir en pantalla completa y en calidad HD.

**[Título del video 1]**

- Duración: [min]
- [Pegar link del video]`
  },

  /* ---- Base de Conocimiento simulada ----
     Los scores que devuelve la búsqueda caen en 0.40–0.74, que es
     el rango real: en el ejemplo que mandó Finnegans los artículos
     relevantes puntuaban entre 0.58 y 0.66. */
  baseConocimiento: [
    {
      id_externo: 3829,
      titulo: 'Monitoreo de riego y sensores de humedad - Configuración de umbrales',
      categoria: 'Gestión de actividades agrícolas',
      etiquetas: ['agro', 'riego', 'sensores', 'instructivo'],
      autor: 'mlopez', actualizado: '2024-03-12', fragmentos: 6,
      claves: ['riego', 'humedad', 'sensor', 'monitoreo', 'umbral', 'suelo', 'parcela', 'hidrico'],
      veredicto: 'parcial — cubre la configuración de umbrales pero no el protocolo operativo bajo sequía'
    },
    {
      id_externo: 4412,
      titulo: 'Planificación agrícola - Registrar labores de riego en el plan',
      categoria: 'Gestión de actividades agrícolas',
      etiquetas: ['agro', 'planificación-agrícola', 'cómo-se-hace'],
      autor: 'arives', actualizado: '2025-07-02', fragmentos: 4,
      claves: ['riego', 'laboreo', 'planificacion', 'labores', 'parcela', 'lote'],
      veredicto: 'parcial — se solapa en la carga de labores, no en los criterios de disparo'
    },
    {
      id_externo: 2187,
      titulo: 'Balance hídrico por lote - Mensaje: "No hay datos de humedad para el período"',
      categoria: 'Gestión de actividades agrícolas',
      etiquetas: ['agro', 'lotes', 'humedad-de-suelo', 'soluciones'],
      autor: 'gfleitas', actualizado: '2025-09-18', fragmentos: 3,
      claves: ['humedad', 'balance', 'hidrico', 'lote', 'suelo', 'sequia', 'capacidad'],
      veredicto: 'parcial — confirma la terminología de capacidad de campo'
    },
    {
      id_externo: 5108,
      titulo: 'Obtener CAE - Mensaje ARCA: "Imposible conectar con webservice"',
      categoria: 'Ventas',
      etiquetas: ['erp', 'arca', 'factura-de-venta', 'soluciones'],
      autor: 'jperez', actualizado: '2026-02-04', fragmentos: 5,
      claves: ['cae', 'arca', 'webservice', 'factura', 'conectar', 'certificado', 'obtener'],
      veredicto: 'cubre el caso — revisar si corresponde actualizar en lugar de duplicar'
    },
    {
      id_externo: 4856,
      titulo: 'Comisiones MATBA - Configuraciones',
      categoria: 'Comercialización de granos',
      etiquetas: ['agro', 'granos', 'instructivo'],
      autor: 'arives', actualizado: '2025-11-20', fragmentos: 4,
      claves: ['matba', 'comision', 'corredor', 'contrato', 'granos', 'agente', 'configurar'],
      veredicto: 'parcial — confirma nombres de campos de la subsección Comerciales'
    },
    {
      id_externo: 1843,
      titulo: 'Contrato de granos - La suma de kilogramos entregados es mayor a los vinculados',
      categoria: 'Comercialización de granos',
      etiquetas: ['agro', 'granos', 'soluciones'],
      autor: 'gfleitas', actualizado: '2026-07-11', fragmentos: 3,
      claves: ['contrato', 'granos', 'kilogramos', 'entregados', 'vinculados', 'total'],
      veredicto: 'parcial — confirma el campo "Total aplicado" de la sección Totales'
    },
    {
      id_externo: 6021,
      titulo: 'Cargar una factura de compra - Aviso: "Falta especificar un workflow"',
      categoria: 'Compras',
      etiquetas: ['erp', 'bproc', 'soluciones'],
      autor: 'mlopez', actualizado: '2026-05-09', fragmentos: 4,
      claves: ['factura', 'compra', 'workflow', 'cargar', 'aviso', 'especificar'],
      veredicto: 'cubre el caso — mismo mensaje del sistema'
    }
  ],

  /* ---- Ejemplo precargado, para demostrar sin tipear ---- */
  ejemplo: {
    titulo: 'Configurar el monitoreo hídrico en cultivos de soja - Protocolo operativo bajo sequía',
    categoria_id: 'cat_agro_actividades',
    etiquetas: ['instructivo', 'agro', 'riego'],
    cuerpo: `Esta entrada explica cómo configurar el protocolo de riego controlado cuando el balance hídrico de la parcela cae por debajo del umbral crítico.

**Antes de empezar**

Verificar que el lote tenga un sensor de humedad activo asociado desde el maestro de Lotes.

**Modo de uso**

Ruta> Menú > Gestión Empresarial > Agro > Planificación agrícola > Lotes

1. Ingresar a la solapa Riego del lote a configurar.
2. Definir la condición de disparo: balance de humedad en parcela menor al 35% de capacidad de campo.
3. Configurar el riego controlado aplicando pulsos nocturnos de 12 mm entre las 19:00 y las 04:00 hs, para evitar pérdidas por evaporación.
4. Guardar los cambios y verificar que el estado del lote pase a "Monitoreo activo".

Requiere AppBuilder [Indicar en negrita solo si aplica. Si no, BORRAR esta línea]`
  }
};
