TITULO_MIN = 15
TITULO_MAX = 255
TEXTO_MIN = 20
# Quizas estaria bueno mas adelante que a la cota de texto max skills lo obtenga viendo los p 90, 95, y 99
#haciendo un join de la tabla de cant_caracteres con la tabla de artículos para usar la columna texto_sin_headers
TEXTO_MAX = 6928
TAGS_MIN = 2
TAGS_MAX = 5
TAGS_PLANTILLAS_PERMITIDAS = ("instructivo", "soluciones")

CATEGORIA_ID_DEFAULT = 1


PERMITIR_SUBIDA_RECURSOS: bool = True
RECURSO_MAX_BYTES: int = 10 * 1024 * 1024
MAX_RECURSOS_TOTAL_BYTES: int = 50 * 1024 * 1024
MAX_RECURSOS_POR_SESION: int = 20
MAX_BLOQUES_TEXTO: int = MAX_RECURSOS_POR_SESION + 1


##ES DE TODA LA TABLA, SIN DISCRIMINAR pero no lo
TEXTO_MAX_PERCENTIL_99 = 16777

BUFFER_CARACTERES_PROMPT_XML: int = 500

## P98 TABLA 51 % 6828,  P99 9561 P 100 69569
## P98 TABLA 49 % 15291, P99 19908 P100 67682