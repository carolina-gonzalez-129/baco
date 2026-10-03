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

PROFILE = os.getenv("PROFILE")

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
# IMPORTANTE : En principio hay que esperar si Emiliano ocnfirma lo de que
#la capa de servicios se ocupe de validaciones y comprobaciones, de ser asi
#lo de deteccion de duplicados seria tmb de nlp, habria q buscar articulos q sean
#iguales, similares, y opuestos
#Tmb si es asi lo del script validate_article pasaria a la capa de servicios


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
# MCP : Despues pasar tools = tools al agente ,
# IMPORTANTE las tools solo funcionan en este bloque
#Asique para lo de duplicados ver como hacer bien!
# ============================================================
discourse = MCPClient(
    lambda: stdio_client(
        StdioServerParameters(
            command="discourse-mcp",
            args=["--profile", PROFILE],
        )
    )
)
#Las tools el agente solo las va a tener disponibles en este bloque!
with discourse:
    tools = discourse.list_tools_sync()

# ============================================================
# AGENTE BACO
# ============================================================
SYSTEM_PROMPT = """
Sos BACO, asistente de la Base de Conocimiento Finnegans.

Respondé directo a preguntas generales y de conversación.

Si te piden algo que no podés hacer, por ejemplo eliminar artículos,
explicá claramente que no tenés esa función.

Nunca inventes títulos, artículos ni datos de la Base de Conocimiento.
Recordá que el usuario siempre tiene el control final sobre cualquier decisión editorial.

---
SKILL: aplicar_plantillas
Activá la skill "aplicar_plantillas" únicamente cuando el usuario lo pida
explícitamente o cuando la tarea consista en transformar un contenido
usando una plantilla.

Cuando se solicite aplicar una plantilla:
1. Verificá que la solicitud tenga título, categoría, tipo de plantilla (`instructivo` o `soluciones`) y descripción.
2. Si falta alguno, solicitá únicamente ese dato y no apliques la plantilla todavía.
3. Aplicá la skill "aplicar_plantillas" solo cuando estén los cuatro datos.
4. Conservá la información original y no inventes información faltante.
5. Devolvé únicamente el cuerpo estructurado; no repitas los metadatos ni agregues una indicación sobre la plantilla aplicada.

---
SKILL: detectar_duplicados
Activá la skill "detectar_duplicados" cuando se solicite comparar artículos, evaluar si una entrada nueva ya existe en la base, o arbitrar casos ambiguos de similitud.

Al evaluar duplicados:
1. No te guíes por la simple coincidencia léxica de términos de ERP. Evaluá la intención operativa y el impacto en el negocio.
2. Distinguí con rigor entre duplicados reales, variantes paramétricas (ej. distintas jurisdicciones de IIBB como ARBA vs. CABA, países o entes), flujos complementarios u opuestos (ej. compras vs. ventas, primaria vs. secundaria) y subtemas jerárquicos.
3. No tomes acciones destructivas ni intentes fusionar entradas por tu cuenta; tu tarea es diagnosticar y orientar.
4. Entregá siempre el dictamen estructurado indicando dictamen, confianza, análisis de divergencia, riesgo operativo y las opciones concretas para que el usuario tome la decisión final.

---
SKILL: validador
Activá la skill "validador" cuando se solicite auditar, corregir o verificar la calidad editorial, pautas de títulos, estilo o publicación segura de una entrada.
"""


def create_agent(model):
    return Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        plugins=[skills],
    )
# ============================================================
# PRUEBA DE APLICAR-PLANTILLAS
# ============================================================

