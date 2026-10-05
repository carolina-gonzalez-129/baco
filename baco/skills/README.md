# Skills para el Agente Baco

Esta carpeta contiene tres skills:

- `plantillas/`: transforma y normaliza el texto aplicando la plantilla correspondiente —Instructivo o Soluciones—. Contiene las plantillas y ejemplos en `references/`.
- `validador/`: audita títulos, redacción, calidad semántica y publicación segura antes de finalizar un artículo. Contiene las pautas de estilo en `references/`.
- `duplicados/`: arbitra casos ambiguos de duplicación mediante análisis semántico profundo para que el usuario tome la decisión final fundamentada. Contiene los criterios y casos en `references/` y `tests/`.

Cada carpeta representa una skill independiente con su propio `SKILL.md` y sus recursos de consulta en `references/`.

## Uso independiente y enfoque NLP

Cada skill funciona con un enfoque puramente lingüístico y editorial (NLP), asumiendo que la validación estructural básica (existencia de campos, longitud mínima, conteo de tags) es resuelta previamente por la capa de servicios del servidor. La orquestación y decisión final corresponden siempre a la lógica del usuario y de la aplicación.