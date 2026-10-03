---
name: aplicar_plantillas
description: Identifica si una entrada corresponde a un instructivo o una solución y la organiza usando la plantilla Instructivo o Soluciones de Finnegans.
---

# Aplicar plantillas

Usa esta skill para organizar un texto nuevo o existente como artículo de la Base de Conocimiento.

Antes de aplicar una plantilla, verifica que estén disponibles los metadatos mínimos. Son datos de trabajo internos y no deben repetirse en la salida.

## Datos obligatorios de entrada

La solicitud debe incluir:

- **Título**
- **Categoría**
- **Tipo de plantilla:** exactamente `instructivo` o `soluciones`
- **Descripción**
- **Contenido fuente**, que puede ser la misma descripción cuando no haya información adicional

Las etiquetas temáticas son opcionales. Si falta cualquiera de los cuatro datos mínimos, no apliques la plantilla: solicita únicamente el dato faltante. No infieras el tipo de plantilla ni completes datos ausentes con marcadores.

Una vez confirmados los metadatos mínimos, conserva la descripción y todo el contenido fuente confirmado. Los marcadores `[Indicar ...]` solo pueden usarse dentro de una sección cuando falta un detalle operativo que la fuente no proporciona.

## Aplicación

- Para `instructivo`, usa [la plantilla Instructivo](references/plantilla-instructivo.md).
- Para `soluciones`, usa [la plantilla de Soluciones](references/plantilla-soluciones.md).
- Conserva el orden y los nombres de las secciones de la plantilla elegida.
- Usa los ejemplos de referencia únicamente para comprender el formato. No copies su estructura si contradice la plantilla correspondiente.
- No uses los casos de prueba como contenido del artículo.
- Usa título, categoría, tipo de plantilla y descripción como etiquetas implícitas de clasificación. No los muestres como encabezado, ficha, resumen ni sección adicional.
- Devuelve únicamente el cuerpo publicable del artículo.
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

Incluir **Requiere AppBuilder** únicamente cuando la solicitud confirme que aplica o que se necesita AppBuilder. Si la solicitud confirma que no aplica, omitirla. Si no hay confirmación, no inventar el requisito ni mostrar una sección de duda.

La sección puede incluir los campos o acciones de AppBuilder confirmados por la fuente.

El tiempo de lectura no forma parte de la salida de esta skill. Si la aplicación lo necesita, debe calcularlo fuera de la skill a partir de la cantidad de palabras.

No incluir instrucciones sobre botones de edición, Paint, colores de marca, publicación ni otras pautas editoriales en el artículo.

## Etiquetas

Las etiquetas deben incluir siempre el tipo correspondiente:

- `instructivo` para la plantilla Instructivo.
- `soluciones` para la plantilla Soluciones.

Conservar las etiquetas temáticas recibidas y no inventar etiquetas adicionales, salvo la etiqueta obligatoria del tipo.

Usar siempre la forma `soluciones`, incluso cuando el texto fuente diga “Solución”.