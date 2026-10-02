VERIFICAR QUE LA VERSIÓN DE PYTHON SEA CORRECTA, tener un virtual enviroment tmb! y q este acrtivo
pip install strands-agents
pip install google-genai


IMPORTANTE : Cuando emiliano confirme si quieren que la capa de servicios sea mas determinista hay que alli hacer las validaciones de la skill validator(el script pasa alli), y lo de duplicados interceptaria una buena parte de casos de duplicados (alli se haria eso de comparar primero normalizando el titulo, slug de discourse, rapidfuzz, hash, palabras clave, y or ultimo lo de coseno entre vectores con transformers, primero quizas exigiendo q el texto tenga un nro de 200 caracteres a 400 max o irlo recalibrando)
entonces la skill de duplicados se quedaria con una cota de casos mas ambiguos que pasaron esos filtros, y habria que buscar por lo menos 2 pares de articulos del siguiente tipo
1) identicos 2) similares 3) totalmente distintos, para q esten de ejemplo, y darle reglas precisas, las skills serian entonces todas nlp.
