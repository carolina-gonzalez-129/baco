#Limites de titulo
TITULO_MIN = 15  # Alineado con Discourse
TITULO_MAX = 255  # El percentil 99 igual tiene 176, pero es para alinearse con Discourse

# Limites de texto
TEXTO_MIN = 20    # Alineado con Discourse
TEXTO_MAX = 6687  # Percentil 95 del largo de texto en la tabla de artículos (Octubre 2026)

#Limites y reglas de tags
TAGS_MIN = 2      # Min de etiquetas requeridas por artículo
TAGS_MAX = 5      # limite habitual permitido en discourse
TAGS_PLANTILLAS_PERMITIDAS = ("instructivo", "soluciones")

#AGREGAR UN MENU DESPLEGABLE PARA QUE SI NO SE PUDO INFERIR SE PUEDA SELECCIONAR VIENDOLAS X NOMBRE!
# Valores por Defecto
CATEGORIA_ID_DEFAULT = 1  # Categoría por defecto para artículos nuevos sin categoría previa
