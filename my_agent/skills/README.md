# Skills para el Agente Baco

Esta carpeta contiene dos skills:

- `aplicar-plantillas/`: determina el tipo de contenido y aplica la plantilla correspondiente —Instructivo o Soluciones—. Contiene las plantillas y ejemplos en `references/`.
- `validator/`: audita títulos, redacción, claridad editorial y publicación segura antes de finalizar una entrada. Contiene las pautas de estilo en `references/`.

Cada carpeta representa una skill independiente con su propio `SKILL.md` y sus recursos de consulta en `references/`.

## Uso independiente

Cada skill funciona de forma independiente y se invoca explícitamente según la tarea: aplicar una plantilla o auditar un texto. `aplicar-plantillas` decide internamente cuál de sus dos formatos corresponde; la concatenación entre skills, si se necesita, pertenece a la lógica del programa y no está configurada dentro de ellas.