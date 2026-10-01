---
name: validator
description: Revisa y mejora artículos de la Base de Conocimiento Finnegans según las pautas de títulos, redacción, claridad y publicación segura.
---

# Validator de artículos

Usa esta skill de forma independiente cuando la persona solicite revisar un artículo o texto para la Base de Conocimiento. Sigue las guías de [títulos](references/como_escribir_buenos_titulos.md) y [redacción de la Base de Conocimiento](references/pautas_base_conocimiento.md). Las comprobaciones mecánicas reutilizables están en `scripts/validate_article.py`; los casos de prueba se mantienen en `tests/` y fuera de las referencias que carga el agente.

## Procedimiento

1. Identificar el tipo de plantilla y revisar título, categoría, descripción, etiquetas y cuerpo. Si falta el tipo de plantilla o información clave, informar el bloqueo en la salida estructurada; no preguntar ni inferir datos dentro de esta skill.
2. Comprobar que el contenido sea generalizable, útil para los lectores previstos y apto para la Base de Conocimiento pública. Marcar casos particulares de clientes, datos personales, información de procesos internos, bugs sin solución y reportes internos de resolución. No repetir datos sensibles innecesariamente en la respuesta.
3. Revisar estructura, exactitud editorial, ortografía, gramática, puntuación, claridad, concisión, orden lógico, tono y contexto de los datos. Aplicar la plantilla correspondiente sin confundir secciones ni cambiar el sentido funcional. Ejecutar primero las comprobaciones mecánicas disponibles en `scripts/validate_article.py`.
4. Revisar el título con las pautas específicas: acción y contexto, infinitivo cuando corresponda, problema concreto, mensaje literal fiel si se cita, y ausencia de redundancias. No agregar la palabra “Error” salvo que forme parte del mensaje textual original.
5. Comprobar categoría y etiquetas: deben estar presentes; la categoría debe corresponder al frente, industria o módulo y las etiquetas deben describir acción, palabras clave y tipo de publicación. La lista de etiquetas debe incluir siempre el tipo de plantilla exacto: `instructivo` o `soluciones`, aunque la persona no lo haya incluido en sus etiquetas sugeridas. No duplicar la etiqueta si ya está. Si la adecuación de las demás etiquetas no se puede determinar con lo provisto, indicarlo como pendiente, sin inventar valores.
6. En artículos de solución, comprobar la estructura **Consulta** → **Respuesta** → **Pasos a seguir**; que la consulta esté en presente, la respuesta explique solo una causa respaldada y los pasos estén ordenados y redactados en infinitivo.
7. Comprobar **Requiere AppBuilder** solo si los pasos requieren AppBuilder o Tipos de Documentos y el usuario necesita ese permiso. Si el permiso o requisito no está confirmado, marcarlo como pendiente; no inferirlo.
8. Entregar la salida con el formato definido abajo. El modo predeterminado es informe; ofrecer una versión corregida completa solo si se solicita explícitamente `rewrite=true`.

## Formato de salida

Devolver un objeto o bloque equivalente a:

```text
Estado: Listo | Listo con ajustes sugeridos | Pendiente
Título: ...
Categoría: ...
Tipo de plantilla: instructivo | soluciones
Descripción: ...
Etiquetas: ...
Hallazgos:
- Severidad: Bloqueante | Requiere ajuste | Sugerencia
  Campo: ...
  Descripción: ...
  Acción: ...
Versión corregida: solo si rewrite=true
```

Clasificar cada hallazgo únicamente como:

- **Bloqueante:** riesgo de publicación (por ejemplo, información personal, caso privado, bug sin solución o dato interno), falta un dato esencial o el texto contradice la fuente.
- **Requiere ajuste:** incumplimiento editorial o problema de claridad, estructura, ortografía o formato que se pueda corregir.
- **Sugerencia:** mejora opcional que no impide publicar.

Cerrar con un estado: **Listo**, **Listo con ajustes sugeridos** o **Pendiente**. Usar **Pendiente** si hay bloqueantes o datos esenciales sin confirmar. “Pendiente” es un estado, no una severidad. La revisión editorial no verifica de manera independiente que las instrucciones sean técnicamente correctas; señalar esa limitación si corresponde.

## Reglas

- No inventar categorías, etiquetas, rutas, mensajes, resultados, causas ni requisitos de permisos.
- Asegurar que todas las entradas tengan título, categoría, tipo de plantilla y descripción; también deben tener la etiqueta de tipo (`instructivo` o `soluciones`) y conservar las etiquetas temáticas proporcionadas, normalizando solo el formato cuando haga falta.
- No alterar el significado técnico para mejorar el estilo. Si el texto es ambiguo o contradictorio, señalarlo en vez de elegir una interpretación.
- Conservar exactamente los mensajes del sistema entre comillas; no corregir ni parafrasear su contenido citado.
- Generalizar detalles particulares únicamente si se puede preservar la información útil. Si no se puede, pedir una versión anonimizada o marcar la entrada como no apta.
- No afirmar que una entrada es publicable si contiene información que debe excluirse de una base pública.
- No afirmar que herramientas externas, otra persona o un revisor adicional fueron consultados si no ocurrió.
- Las comprobaciones mecánicas no sustituyen la revisión semántica de generalización, privacidad, causa confirmada y claridad.
