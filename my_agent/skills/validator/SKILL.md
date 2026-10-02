 ---
name: validator
description: Revisa y mejora entradas de la Base de Conocimiento Finnegans según pautas de redacción, calidad editorial, claridad semántica y publicación segura.
---

# Validator de entradas

Usa esta skill cuando se solicite auditar o mejorar el contenido de una entrada para la Base de Conocimiento. Sigue las guías de [títulos](references/como_escribir_buenos_titulos.md) y [redacción de la Base de Conocimiento](references/pautas_base_conocimiento.md).

> **Nota:** La presencia de los campos obligatorios, la longitud mínima y el formato de datos son garantizados previamente por el servidor. Esta skill se enfoca exclusivamente en la **calidad semántica, editorial, de privacidad y de estilo**.

## Procedimiento

1. **Seguridad y privacidad (Publicación segura):**
   Comprobar que el contenido sea apto para una base de conocimiento pública. Marcar como bloqueante:
    - Datos personales, nombres de clientes o empresas reales.
    - Capturas de pantalla o textos con información interna confidencial o credenciales.
    - Menciones a casos privados, tickets de soporte o bugs sin resolución oficial.
    - Generalizar los ejemplos (usar datos ficticios y genéricos) sin alterar la utilidad del contenido.

2. **Revisión del título (Pautas de títulos):**
    - Evaluar si expresa claramente la **acción y el contexto** del usuario en el sistema.
    - Verificar el uso de verbos en **infinitivo** cuando corresponda (ej. "Configurar", "Emitir", "Consultar").
    - Identificar si describe un problema concreto y no abstracto.
    - **Regla de "Error":** Comprobar que no se use la palabra "Error" salvo que cite textualmente un mensaje del sistema entre comillas.
    - Eliminar fórmulas redundantes (ej. "Cómo hacer para...") y verificar que no termine en punto final.

3. **Adecuación de categoría y permisos:**
    - Evaluar si la categoría asignada tiene sentido temático con el módulo o proceso explicado (ej. Agro, Ventas, Finanzas, etc.).
    - **AppBuilder / Tipos de Documentos:** Si el procedimiento requiere herramientas avanzadas como AppBuilder o parametrización de Tipos de Documentos, comprobar si se advierte al lector sobre los permisos requeridos. Si no está confirmado, indicarlo como pendiente o sugerencia; no inventarlo.

4. **Calidad de redacción y tono (NLP / Editorial):**
    - Revisar ortografía, gramática, claridad y concisión.
    - Comprobar el tono característico de Finnegans (profesional, directo, accesible).
    - Verificar la coherencia lógica: ¿los pasos explicados realmente resuelven la consulta planteada?
    - Si el texto es ambiguo o confuso, señalarlo con una acción correctiva clara en lugar de asumir interpretaciones.

5. **Estructura según tipo de plantilla:**
    - **Soluciones:** Verificar que la consulta esté planteada en presente, la respuesta explique una causa respaldada y los pasos a seguir estén redactados en infinitivo y en orden cronológico estricto.
    - **Instructivo:** Verificar que el objetivo esté claro desde el inicio y que las instrucciones sigan una secuencia paso a paso fácil de seguir.

6. **Entrega del resultado:**
   El modo predeterminado es emitir el informe de auditoría. Si la persona solicita explícitamente `rewrite=true`, ofrecer además la versión corregida completa lista para publicar.

## Formato de salida

Devolver el informe con la siguiente estructura:

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