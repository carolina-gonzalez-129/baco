# Casos de prueba de aplicar-plantillas

Usar estos casos para verificar que la skill respete el formato de salida, no invente información y mantenga las notas fuera del artículo.

## 1. Instructivo completo

Entrada:

- Título, categoría, tipo `instructivo`, etiquetas y contenido con objetivo, ruta, requisitos y pasos.

Resultado esperado:

- Verificar internamente **Título**, **Categoría**, **Tipo de plantilla** y **Descripción** antes de aplicar la plantilla.
- No repetir esos metadatos en la salida; devolver únicamente el cuerpo publicable.
- Secciones del instructivo en el orden definido.
- Sin tiempo de lectura ni instrucciones editoriales.

## 2. Solución sin causa confirmada

Entrada:

- Tipo `soluciones`.
- Problema observado y pasos parciales, sin evidencia de la causa.

Resultado esperado:

- Incluir la descripción del problema y los pasos confirmados.
- Omitir cualquier explicación de causa o solución presentada como certeza.
- Mantener un marcador solo cuando falte un dato estructural, por ejemplo `[Indicar ruta]`.

## 3. Texto ambiguo

Entrada:

- Título, categoría y contenido que podrían ser un instructivo o una solución, pero sin tipo de plantilla.

Resultado esperado:

- No inferir el tipo.
- Solicitar `instructivo` o `soluciones` antes de generar el artículo.

## 4. Datos contradictorios

Entrada:

- Tipo informado y contenido con dos valores incompatibles para una misma configuración.

Resultado esperado:

- No elegir un valor ni calcular una equivalencia.
- Conservar el dato como pendiente fuera del cuerpo publicable o solicitar confirmación.
- No convertir la nota de revisión en una sección del artículo.
