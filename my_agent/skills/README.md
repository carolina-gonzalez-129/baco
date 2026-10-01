# Skills para el Agente Baco 

Esta carpeta contiene dos skills:



- `aplicar-plantillas/`: determina el tipo de contenido y aplica la plantilla correspondiente —Instructivo o Soluciones—.

- `validator/`: valida títulos, redacción, estructura y aptitud de publicación antes de finalizar una entrada.



Cada carpeta representa una skill independiente con su propio `SKILL.md`. `aplicar-plantillas` incluye ambas plantillas y ejemplos en `references/`; `validator` contiene las pautas y recursos de revisión en sus referencias
## Uso independiente

Cada skill funciona de forma independiente y se invoca explícitamente según la tarea: aplicar una plantilla o revisar un texto. `aplicar-plantillas` decide internamente cuál de sus dos formatos corresponde; la concatenación entre skills, si se necesita, pertenece a la lógica del programa y no está configurada dentro de ellas.
