---
name: aplicar-plantillas
description: Identifica si una entrada corresponde a un instructivo o una solución y la organiza usando la plantilla Instructivo o Soluciones de Finnegans.
---

# Aplicar plantillas

Usa esta skill para organizar un texto nuevo o existente como artículo de la Base de Conocimiento.

El tipo de plantilla es un dato obligatorio de entrada. Aplica únicamente la plantilla solicitada. Esta skill es independiente y no invoca otras skills.

## Datos obligatorios de entrada

La solicitud debe incluir:

- **Título**
- **Categoría**
- **Tipo de plantilla:** exactamente `instructivo` o `soluciones`
- **Contenido fuente**
- **Etiquetas temáticas**, si existen

Si falta el tipo de plantilla, no lo infieras ni apliques una plantilla: solicita ese dato.

Si falta otro dato, conserva un marcador claro como `[Indicar ...]` únicamente cuando sea posible estructurar el artículo sin inventar información.

## Aplicación

- Para `instructivo`, usa [la plantilla Instructivo](references/plantilla-instructivo.md).
- Para `soluciones`, usa [la plantilla de Soluciones](references/plantilla-soluciones.md).
- Conserva el orden y los nombres de las secciones de la plantilla elegida.
- Usa los ejemplos de referencia únicamente para comprender el formato. No copies su estructura si contradice la plantilla correspondiente.
- No uses los casos de prueba como contenido del artículo.
- Devuelve siempre el encabezado en este orden:

  **Título:** [título recibido]  
  **Categoría:** [categoría recibida]  
  **Tipo de plantilla:** [instructivo o soluciones]  
  **Etiquetas:** [tipo obligatorio y etiquetas temáticas recibidas]

- Después del encabezado, devuelve únicamente el cuerpo publicable del artículo.
- No agregues texto antes o después del artículo.
- No incluyas comentarios editoriales, observaciones, diagnósticos, estados de revisión ni explicaciones sobre la plantilla aplicada.
- No incluyas una sección o texto llamado `Plantilla aplicada`.
- No repitas el encabezado ni ninguna sección.
- No inventes categorías, rutas, pantallas, causas, mensajes, datos, acciones, resultados ni capacidades del sistema.
- Si falta información, conserva un marcador claro como `[Indicar ruta]` dentro de la sección correspondiente.
- Conserva toda la información confirmada del contenido fuente.

## Reglas para instructivos

Para la plantilla `instructivo`:

- Respetar exactamente las secciones definidas en `references/plantilla-instructivo.md`.
- Incluir **Qué hace y qué no hace** cuando el contenido describa el alcance o comportamiento de una funcionalidad.
- Usar únicamente capacidades y límites confirmados.
- Si no hay información suficiente sobre una capacidad o límite, conservar un marcador pendiente en lugar de inventarlo.
- Escribir las acciones y los pasos con verbos en infinitivo.

## Reglas para soluciones

Para la plantilla `soluciones`, incluir exactamente estas secciones y en este orden:

1. `## Consulta`
2. `## Respuesta`
3. `## Pasos a seguir`

### Consulta

En `## Consulta`:

- Describir únicamente el problema observado.
- Incluir las acciones que provocan el problema, si fueron proporcionadas.
- Describir el comportamiento observado del sistema.
- Incluir el mensaje de error, si fue proporcionado.
- Mantener la redacción en tiempo presente.
- Incluir la ruta únicamente si fue proporcionada.
- No explicar la causa.
- No explicar por qué ocurre el problema.
- No incluir instrucciones para resolverlo.
- No incluir pasos de solución.

### Respuesta

En `## Respuesta`:

- Explicar la causa del inconveniente.
- Explicar por qué ocurre el comportamiento observado.
- Explicar por qué la solución corrige el problema.
- Usar únicamente información confirmada en el contenido fuente.
- Si la causa no está confirmada, indicarla como posible causa.
- No inventar causas, datos ni comportamientos.
- No repetir innecesariamente la descripción de `Consulta`.
- No incluir pasos operativos numerados.

### Pasos a seguir

En `## Pasos a seguir`:

- Incluir únicamente acciones operativas para resolver el problema.
- Usar verbos en infinitivo.
- Numerar los pasos en orden.
- Mantener únicamente acciones confirmadas en el contenido fuente.
- Incluir la ruta de acceso únicamente si fue proporcionada.
- No agregar explicaciones conceptuales ni causas dentro de esta sección.
- No inventar pasos, pantallas, botones, rutas o resultados.

## Secciones opcionales

No incluir una sección **Requiere AppBuilder** salvo que:

1. La solicitud indique explícitamente si se necesita AppBuilder; y
2. La plantilla o el formato de integración requiera esa sección.

Si no se cumplen ambas condiciones, omitirla.

El tiempo de lectura no forma parte de la salida de esta skill. Si la aplicación lo necesita, debe calcularlo fuera de la skill a partir de la cantidad de palabras.

No incluir instrucciones sobre botones de edición, Paint, colores de marca, publicación ni otras pautas editoriales en el artículo.

## Etiquetas

Las etiquetas deben incluir siempre el tipo correspondiente:

- `instructivo` para la plantilla Instructivo.
- `soluciones` para la plantilla Soluciones.

Conservar las etiquetas temáticas recibidas y no inventar etiquetas adicionales, salvo la etiqueta obligatoria del tipo.

Usar siempre la forma `soluciones`, incluso cuando el texto fuente diga “Solución”.