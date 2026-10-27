---
name: plantillas
description: Transforma y normaliza borradores o textos de la Base de Conocimiento Finnegans al formato estructurado de Instructivo o Soluciones mediante procesamiento del lenguaje natural.
---

# Aplicar plantillas (Motor de Transformación NLP)

Usar esta skill para procesar, limpiar y reestructurar semánticamente textos en bruto o borradores, convirtiéndolos en artículos publicables bajo los estándares editoriales de Finnegans (**Instructivo** o **Soluciones**).

> **Garantía del Servidor:** La presencia de campos obligatorios (título, categoría, texto base, plantilla) y la validación de tipos son garantizadas previamente por la capa determinista de la aplicación. Esta skill opera sobre el contenido como un **transformador lingüístico y semántico**, enfocándose en redacción, síntesis y estructura.

---

## Directrices de Transformación

1. **Plantilla explícita:** BACO no infiere la plantilla a partir del contexto. Aplica únicamente la plantilla indicada (**Instructivo** o **Soluciones**).
2. **Normalización verbal:** Redactar todos los pasos y acciones en **modo infinitivo** (ej. *"Ingresar a..."*, *"Seleccionar el comprobante..."*, *"Hacer clic en Guardar"*). Evitar imperativos y segunda persona (*"ingresá"*, *"debés seleccionar"*).
3. **Fidelidad factual (cero alucinación):**
   - Conservar toda la información técnica, nombres de parámetros y rutas operativas confirmadas en la fuente.
   - Nunca inventar pantallas, módulos, botones, causas de error ni capacidades inexistentes en Finnegans.
   - Si falta un dato operativo que el usuario debe completar, insertar un marcador explícito, por ejemplo: `[Indicar ruta del menú]`.
4. **Limpieza editorial:**
   - Eliminar redundancias, muletillas, fórmulas conversacionales (*"A continuación veremos..."*, *"En este artículo te enseño..."*) y comentarios personales del autor.
   - Devolver **únicamente** el cuerpo Markdown del artículo final: sin saludos, sin metadatos ni ficha técnica y sin explicaciones sobre la plantilla aplicada.

---

## Estructuras por Tipo de Plantilla

### 1. Plantilla `instructivo`

Usar cuando el contenido describe un procedimiento paso a paso o una funcionalidad regular del sistema. Estructura detallada en [references/plantilla-instructivo.md](references/plantilla-instructivo.md).

Secciones, con estos encabezados:

- `## Objetivo`: sintetizar en uno o dos párrafos qué permite realizar la funcionalidad.
- `## Qué hace y qué no hace`: contrastar los límites confirmados del módulo, solo si la fuente los menciona.
- `## Requisitos previos`: configuraciones, permisos o datos maestros necesarios.
- `## Procedimiento paso a paso`: secuencia cronológica numerada, con verbos en infinitivo.
- `## Resultado esperado`: comprobante, asiento o estado final que produce el procedimiento.

### 2. Plantilla `soluciones`

Usar cuando el contenido describe la resolución de un mensaje de error, un comportamiento anómalo o una consulta frecuente (*Q&A técnico*). Estructura detallada en [references/plantilla-soluciones.md](references/plantilla-soluciones.md).

Incluir exactamente estas tres secciones:

1. `## Consulta`
   - Describir el síntoma o la consulta en tiempo presente.
   - Citar textualmente el mensaje de error entre comillas, si está en la fuente.
   - **No** adelantar la solución ni explicar causas.
2. `## Respuesta`
   - Explicar la causa raíz y el porqué del comportamiento, según la fuente.
   - **No** listar pasos operativos ni instrucciones numeradas.
3. `## Pasos a seguir`
   - Secuencia ordenada y numerada de pasos para resolver el problema.
   - Verbos en infinitivo, directos y enfocados exclusivamente en la acción de corrección.

---

## Secciones Condicionales por Dominio

- **Requiere AppBuilder:** Incluir esta sección técnica únicamente si el texto fuente confirma explícitamente el uso de personalizaciones o parametrizaciones en AppBuilder. Si no aplica o no se menciona, omitir por completo.
- **Etiqueta de tipo:** Asegurar internamente la etiqueta `instructivo` o `soluciones` según corresponda.