import os
from pathlib import Path

from dotenv import load_dotenv

# Carga el .env de la raíz del proyecto antes de leer límites configurables
# (este módulo puede importarse antes que los que ya llaman a load_dotenv).
for _p in Path(__file__).resolve().parents:
    if (_p / ".env").exists():
        load_dotenv(_p / ".env")
        break

TITULO_MIN = 15
TITULO_MAX = 255
TEXTO_MIN = 20
# Quizas estaria bueno mas adelante que a la cota de texto max skills lo obtenga viendo los p 90, 95, y 99
#haciendo un join de la tabla de cant_caracteres con la tabla de artículos para usar la columna texto_sin_headers
# Cota máxima de texto para usar skills. Configurable con BACO_TEXTO_MAX en el .env.
TEXTO_MAX = int(os.getenv("BACO_TEXTO_MAX", "6687"))
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