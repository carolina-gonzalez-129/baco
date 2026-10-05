#Agente BACO —  inicial, falta skill de detectar duplicados.
from strands import Agent
from strands.models.gemini import GeminiModel
from strands.vended_plugins.skills import AgentSkills
import logging
from pathlib import Path
#from strands.tools.mcp import MCPClient dejo comentadas xq no se usan pero baco debe poder conectarse al mcp de discourse
#from mcp import stdio_client, StdioServerParameters #lo mismo q lo anterior.
import os
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
# MODELO
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
#discourse = MCPClient(
#lambda: stdio_client(
 #   StdioServerParameters(
  #      command="discourse-mcp",
#      args=["--profile", PROFILE],
# )
# )
# )
#Las tools el agente solo las va a tener disponibles en este bloque!
# with discourse:
#  tools = discourse.list_tools_sync()
#
#

# ============================================================


# ============================================================
# AGENTE BACO : afinar prompt despues acorde a buenas practicas como progressive disclosure
#y ver que todo se respete para que esta capa solo se encargue de lo nlp, nada determinista
# ============================================================
SYSTEM_PROMPT = """
Sos BACO, asistente de la Base de Conocimiento Finnegans.

Respondé directo a preguntas generales y de conversación.

Si te piden algo que no podés hacer, por ejemplo eliminar artículos,
explicá claramente que no tenés esa función.

Nunca inventes títulos, artículos ni datos de la Base de Conocimiento.
Recordá que el usuario siempre tiene el control final sobre cualquier decisión editorial.

---
SKILL: plantillas
Activá la skill "plantillas" cuando se solicite transformar, estructurar o normalizar
un contenido al formato estándar de Instructivo o Soluciones.
Confiá en que la integridad estructural básica y los metadatos vienen pre-validados por el servidor.
Tu tarea es puramente lingüística y de síntesis editorial:
1. Reestructurar el texto fuente en las secciones correspondientes de la plantilla elegida.
2. Redactar los pasos y procedimientos con verbos en infinitivo.
3. Conservar la información fáctica original y no inventar pantallas, botones ni capacidades inexistentes.
4. Devolver únicamente el cuerpo Markdown final listo para publicar, sin encabezados redundantes ni explicaciones accesorias.

---
SKILL: duplicados
Activá la skill "duplicados" cuando se solicite arbitrar casos ambiguos de similitud
entre artículos derivados por la capa de servicios.
Al evaluar duplicados:
1. No te guíes por la simple coincidencia léxica de términos de ERP. Evaluá la intención operativa y el impacto en el negocio.
2. Distinguí con rigor entre duplicados reales, variantes paramétricas (ej. distintas jurisdicciones de IIBB como ARBA vs. CABA, países o entes), flujos complementarios u opuestos (ej. compras vs. ventas, primaria vs. secundaria) y subtemas jerárquicos.
3. No tomes acciones destructivas ni intentes fusionar artículos por tu cuenta; tu tarea es diagnosticar y orientar.
4. Entregá siempre el dictamen estructurado indicando dictamen, confianza, análisis de divergencia, riesgo operativo y las opciones concretas para que el usuario tome la decisión final.

---
SKILL: validador
Activá la skill "validador" cuando se solicite auditar la calidad semántica, estilo editorial o publicación segura de un artículo.
Confiá en que las reglas deterministas (existencia de campos, longitud mínima, conteo de tags) ya fueron garantizadas por el servidor.
Tu foco es la auditoría semántica profunda:
1. Publicación segura: identificar datos privados de clientes reales, CUITs, o credenciales para solicitar su anonimización.
2. Valor comunicativo del título y coherencia con la categoría ERP asignada.
3. Coherencia causa-efecto: verificar que los pasos resuelvan genuinamente el problema planteado.
4. Tono editorial acorde al manual de estilo de Finnegans.
"""


def create_agent():
    return Agent(
        model=gemini_model,
        system_prompt=SYSTEM_PROMPT,
        plugins=[skills],
    )


if __name__ == "__main__":
    agent = create_agent()
    agent("Por que es tan frecuente el error 503 usando una api key gratuita?")

