---
name: plantillas
description: Transforma y normaliza borradores o textos de la Base de Conocimiento Finnegans al formato estructurado de Instructivo o Soluciones mediante procesamiento del lenguaje natural.
---

# Aplicar plantillas (Motor de Transformación NLP)

Usa esta skill para procesar, limpiar y reestructurar semánticamente textos en bruto o borradores, convirtiéndolos en artículos publicables bajo los estándares editoriales de Finnegans (**Instructivo** o **Soluciones**).

> **Garantía del Servidor:** La presencia de campos obligatorios (título, categoría, texto base) y la validación de tipos son garantizadas previamente por la capa determinista de la aplicación. Esta skill opera directamente sobre el contenido como un **transformador lingüístico y semántico**, enfocándose en la redacción, síntesis y estructura.

---

## Directrices de Transformación Lingüística

1. **Comprensión Semántica:** Analiza el texto fuente para identificar el propósito operativo real (aprender a usar una función vs. diagnosticar y corregir un error).
2. **Normalización Verbal:** 
   * Redacta todos los pasos y acciones en **modo infinitivo** (ej. *"Ingresar a...", "Seleccionar el comprobante...", "Hacer clic en Guardar"*), eliminando el uso de imperativos o segunda persona (*"ingresá", "debés seleccionar"*).
3. **Fidelidad Factual (Cero Alucinación):** 
   * Conserva toda la información técnica, nombres de parámetros y rutas operativas confirmadas en la fuente.
   * Nunca inventes pantallas, módulos, botones, causas de error ni capacidades inexistentes en Finnegans.
   * Si en la fuente falta un dato operativo puntual que el usuario debe completar, inserta un marcador explícito: `[Indicar ...]`.
4. **Limpieza Editorial:** 
   * Elimina redundancias, muletillas, fórmulas conversacionales (*"A continuación veremos...", "En este artículo te enseño..."*) y comentarios personales del autor.
   * Devuelve **únicamente** el cuerpo Markdown del artículo final listo para ser publicado (sin saludos, sin metadatos duplicados como ficha técnica, y sin explicaciones sobre la plantilla aplicada).

---

## Estructuras por Tipo de Plantilla

### 1. Plantilla `instructivo`
Aplica la estructura detallada en [references/plantilla-instructivo.md](references/plantilla-instructivo.md) cuando el contenido describe un procedimiento paso a paso o una funcionalidad regular del sistema.

* **Objetivo:** Sintetizar con claridad en uno o dos párrafos qué permite realizar la funcionalidad.
* **Alcance ("Qué hace y qué no hace"):** Extraer y contrastar los límites confirmados del módulo si el texto fuente los menciona.
* **Requisitos previos:** Aislar configuraciones previas, permisos o datos maestros necesarios.
* **Procedimiento paso a paso:** Desglosar la secuencia cronológica numerada con verbos en infinitivo.
* **Resultado esperado:** Detallar el comprobante, asiento o estado final que produce el procedimiento.

### 2. Plantilla `soluciones`
Aplica la estructura detallada en [references/plantilla-soluciones.md](references/plantilla-soluciones.md) cuando el contenido describe la resolución de un mensaje de error, comportamiento anómalo o consulta frecuente (*Q&A técnico*).

Debe incluir exactamente estas tres secciones principales:
1. `## Consulta`: 
   * Describe el síntoma o consulta en tiempo presente.
   * Cita textualmente el mensaje de error entre comillas si está presente en la fuente.
   * **No** adelantar la solución ni explicar las causas aquí.
2. `## Respuesta`: 
   * Explica la causa raíz y el porqué del comportamiento observado según la fuente.
   * **No** listar pasos operativos ni instrucciones numeradas aquí.
3. `## Pasos a seguir`: 
   * Secuencia ordenada y numerada de pasos para resolver el problema.
   * Verbos en infinitivo, directos y enfocados exclusivamente en la acción de corrección.

---

## Secciones Condicionales por Dominio

* **Requiere AppBuilder:** Incluir esta sección técnica únicamente si el texto fuente confirma explícitamente el uso de personalizaciones o parametrizaciones en AppBuilder. Si no aplica o no se menciona, omitir por completo.
* **Etiqueta de tipo:** Asegurar internamente la etiqueta `instructivo` o `soluciones` según corresponda.