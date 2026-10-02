# Skills para el Agente Baco

Esta carpeta contiene tres skills:

- `aplicar-plantillas/`: determina el tipo de contenido y aplica la plantilla correspondiente —Instructivo o Soluciones—. Contiene las plantillas y ejemplos en `references/`.
- `validator/`: audita títulos, redacción, claridad editorial y publicación segura antes de finalizar una entrada. Contiene las pautas de estilo en `references/`.
- `detectar-duplicados/`: arbitra casos ambiguos de duplicación mediante análisis semántico profundo para que el usuario tome la decisión final fundamentada. Contiene los criterios y casos en `references/` y `tests/`.

Cada carpeta representa una skill independiente con su propio `SKILL.md` y sus recursos de consulta en `references/`.

## Uso independiente

Cada skill funciona de forma independiente y se invoca según la tarea requerida: estructurar una plantilla, auditar la redacción o evaluar duplicados en zonas de ambigüedad. La orquestación y decisión final corresponden siempre a la lógica del usuario y de la aplicación.