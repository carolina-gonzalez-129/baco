#Agente BACO —  inicial, falta skill de detectar duplicados.
import time
from strands import Agent
from strands.models.gemini import GeminiModel
from strands.vended_plugins.skills import AgentSkills
import logging
from pathlib import Path
from strands.tools.mcp import MCPClient
from mcp import stdio_client, StdioServerParameters
import os
import dotenv
from dotenv import load_dotenv

load_dotenv()



BASE_DIR = Path(__file__).resolve().parent
SKILLS_DIR = BASE_DIR / "skills"

profile = os.getenv("PROFILE")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

logger = logging.getLogger(__name__)
"""
  lo use para ir trackeando como se ejecutaba, primero se cargó el modelo, dsps registro las tools, el system prompt
  
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
"""

# ============================================================
# MODELO : IMPORTANTE : La free tier nos esta dando problemas
# para poder chequear la pata de skills que sean intensivas en
#procesamiento del lenguaje, por eso estamos en duda sobre si testearlas por ejemplo en un ide agentico o qué.
#Vamos a tener 2 skills que son muy LLM heavy, la de aplicar plantillas y la de validar formato
#Y una que no precisa de tanto LLM, la de detectar duplicados
# probablemente hagamos una mezcla de cosas para la de duplicados, como normalizar datos al principio
#comparar por titulo y/o categoria entonces usando hash, de forma asíncrona como nos habia indicado Emiliano
# y despues procedamos a hacer una comparación en embeddings, osea se convierte texto a un vector numerico
# para hacer la comparacion con lo de coseno entre vectores
#No hace falta saber todo, pero una noción general es de que
# dos vectores (por ejemplo en R2) son similares si tienen valores escalares parecidos
#por ejemplo soy Carolina y carolina Soy tienen ambos [1,1]
# y si fuesen en R3 x ej me llamo carolina [0, 1, 1] y carolina me llamo [1, 0, 1]
# pero como ya habiamos visto -1 significaria que son lo opuesto (casi imposible) ,
# entonces los valores posibles
#seran entre  0 y 1, para 0 siendo disimiles y 1 siendo el mismo vector.
#quizas haya que recalibrar el scoring o tener varios umbrales ej mayor a 0.80 posible duplicado, entre 0.75 y 0.80 muy relacionado, y menor a 0.75 contenido distinto
#Una representacion visual para hacerlo mas ameno seria imaginar por ejemplo dos rectas
#si van en direcciones opuestas es -1, si van en la misma direccion es 1, si son perpendiculares es 0
#las desviaciones me darian la mayor disimilitud o similitud

# Respecto al flujo del programa imaginaba que primero baco podria aplicar lo de deteccion xq es lo mas barato para la empresa
#usar una skill que depende mas de scripts en python
#Despues podria aplicar la plantilla correspondiente (si es de soluciones con su formato, idem lo de instructivo)
#y por ultimo aplicar la de validar formato con las pautas de redaccion, lo de los buenos titulos, y toda la documentacion pertinente

##Como la primer skill que voy a aprobar es intensiva en procesamiento de lenguaje voy
#a intentar paliar los 503, pero quizas los 429 aun me den antes de que pueda probarla :'c
# ============================================================

gemini_api_key = os.getenv("GEMINI_API_KEY")
gemini_model = GeminiModel(
    model_id="gemini-3.8-flash",
    client_args={"api_key": gemini_api_key}
)

# ============================================================
# SKILLS
# ============================================================

skills = AgentSkills(
    skills=str(SKILLS_DIR),
    strict=True,
)





# ============================================================
# AGENTE BACO
# ============================================================
SYSTEM_PROMPT = """
Sos BACO, asistente de una Base de Conocimiento.

Respondé directo a preguntas generales y de conversación.

Si te piden algo que no podés hacer, por ejemplo eliminar artículos,
explicá claramente que no tenés esa función.

Nunca inventes títulos, artículos ni datos de la Base de Conocimiento.

Activá la skill "aplicar-plantillas" únicamente cuando el usuario lo pida
explícitamente o cuando la tarea consista en transformar un contenido
usando una plantilla.

Cuando se solicite aplicar una plantilla:
1. Identificá el tipo de plantilla correspondiente.
2. Aplicá la skill "aplicar-plantillas".
3. Conservá la información original.
4. No inventes información faltante.
5. Devolvé el resultado final claramente separado del contenido original.
"""


def create_agent(model):
    return Agent(
        model=model,
        plugins=[skills],
    )


# ============================================================
# PRUEBAS : Vamos a probar lo de plantillas, de aplicar la de soluciones o instructivo
#Son operaciones costosas en procesamiento de lenguaje pero ni llama ni ningun modelo local las ejecuta bien
#entonces si cambio a otro modelo q no sea openai, claude, o gemini, puedo ver falencias donde no las hay

# ============================================================
def run_with_gemini_retry(
        prompt: str,
        max_wait_seconds: int = 60,
        retry_interval_seconds: int = 10,
):
    started_at = time.monotonic()
    last_error = None
    attempt = 0

    while True:
        elapsed = time.monotonic() - started_at

        if elapsed >= max_wait_seconds:
            break

        attempt += 1

        try:
            logger.info(
                "Ejecutando consulta con Gemini. Intento %s",
                attempt,
            )

            primary_agent = create_agent(gemini_model)
            return primary_agent(prompt)

        except Exception as error:
            last_error = error
            remaining = max_wait_seconds - (
                    time.monotonic() - started_at
            )

            if remaining <= 0:
                break

            wait_seconds = min(
                retry_interval_seconds,
                remaining,
            )

            logger.warning(
                "Gemini falló en el intento %s "
                "(%s: %s). Reintentando en %s segundos. "
                "Tiempo restante: %.1f segundos.",
                attempt,
                type(error).__name__,
                error,
                wait_seconds,
                remaining,
            )

            time.sleep(wait_seconds)

    logger.error(
        "Gemini no estuvo disponible durante %s segundos.",
        max_wait_seconds,
    )

    if last_error is not None:
        raise RuntimeError(
            "No se pudo completar la consulta con Gemini "
            "dentro del tiempo máximo de espera."
        ) from last_error

    raise TimeoutError(
        "Se agotó el tiempo máximo de espera para Gemini."
    )


def print_result(result):
    print(result)


# ============================================================
# PRUEBA DE APLICAR-PLANTILLAS
# ============================================================

with open("prueba.plantillas1", "r", encoding="utf-8") as file:
    contenido = file.read()

plantilla_prompt = f"""
Aplicá la skill "aplicar-plantillas" al siguiente contenido.

Determiná si corresponde utilizar la plantilla de solución o la plantilla
de instructivo. Si no podés determinarlo con seguridad, indicá cuál sería
la información faltante.

No inventes datos y no elimines información relevante.

Contenido de prueba:
--------------------
{contenido}
--------------------

Devolvé únicamente el contenido transformado y, al final, una breve
indicación de la plantilla aplicada.
"""

print("\n" + "=" * 50)
print("🤖 CONSULTA  — APLICAR PLANTILLAS")
print("=" * 50)

try:
    result = run_with_gemini_retry(
        plantilla_prompt,
        max_wait_seconds=120,
        retry_interval_seconds=10,
    )
    print_result(result)

except Exception as error:
    logger.error(
        "La consulta no pudo completarse con Gemini: %s",
        error,
    )
    print(
        "\nNo fue posible completar la consulta con Gemini "
        "dentro de los 60 segundos."
    )
