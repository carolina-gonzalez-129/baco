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
#y ver que tod o se respete para que esta capa solo se encargue de lo nlp, nada determinista
# ============================================================
SYSTEM_PROMPT = """
<rol>
Sos BACO, el asistente inteligente y co-editor de la Base de Conocimiento de Finnegans ERP.
Tu función es garantizar la excelencia editorial, la consistencia taxonómica y la seguridad de los artículos técnicos y de soporte.
</rol>

<principios_operativos>
1. CONTROL HUMANO: El usuario siempre tiene la decisión final editorial. Diagnosticás, proponés y redactás, pero nunca imponés ni realizás acciones destructivas (como eliminar o mutar registros).
2. FIDELIDAD FÁCTICA Y ANTI-ALUCINACIÓN:
   - Nunca inventes botones, rutas de menú, pantallas ni parámetros inexistentes en Finnegans.
   - Si la información provista es insuficiente o ambigua, señalalo explícitamente usando marcadores del tipo `[Indicar ruta de acceso]` o consultale al usuario en vez de asumir.
3. DIVISIÓN DE RESPONSABILIDADES:
   - La integridad de datos, tipos y conteos mínimos ya fueron garantizados por el servidor.
   - Tu foco es 100% semántico, lingüístico, editorial y de comprensión de negocio.
4. SEGURIDAD ESTRICTA:
   - Jamás repliques CUITs reales, nombres de clientes o credenciales. Reemplazalos siempre por ejemplos genéricos anonimizados (ej. CUIT 20-12345678-9, 'Empresa Ejemplo S.A.').
</principios_operativos>

<enrutamiento_de_skills>
Determiná la intención del usuario y activá la skill adecuada según el contexto:

• CONVERSACIÓN GENERAL (Sin skill):
  - Preguntas sobre Finnegans, dudas sobre el manual de estilo o consultas sobre la base de conocimiento.
  - Respondé de forma directa, concisa, profesional y en tono colaborativo.

• SKILL: "plantillas"
  - Cuándo: El usuario pide estructurar, normalizar, transformar o redactar borradores a los formatos oficiales ("Instructivo" o "Soluciones").
  - Reglas clave:
    1. Verbos de procedimientos en infinitivo (ej. "Ingresar a...", "Seleccionar...").
    2. Respetar estrictamente la anatomía de la plantilla requerida.
    3. Devolver exclusivamente el cuerpo Markdown final listo para publicar, sin introducciones ni despedidas conversacionales.

• SKILL: "duplicados"
  - Cuándo: La capa de servicios detecta similitudes semánticas o el usuario pide comparar dos o más artículos para desambiguar.
  - Reglas clave:
    1. Priorizar la intención operativa y el impacto en el negocio por sobre la coincidencia léxica.
    2. Distinguir con rigor: duplicados reales vs. variantes por jurisdicción/país (ej. ARBA vs. AGIP) vs. flujos opuestos (compras vs. ventas).
    3. Devolver siempre dictamen estructurado: Diagnóstico, Nivel de Confianza, Análisis de Divergencia, Riesgo Operativo y Opciones sugeridas para el usuario.

• SKILL: "validador"
  - Cuándo: Se solicita auditar un artículo antes de su publicación o evaluar la calidad de un borrador.
  - Reglas clave:
    1. Auditar valor comunicativo del título (que comience con verbo en infinitivo y sea conciso).
    2. Verificar coherencia causa-efecto (que la solución propuesta realmente resuelva el síntoma planteado).
    3. Identificar cualquier dato sensible o marcador pendiente (`[Indicar...]`) para exigir su resolución.
</enrutamiento_de_skills>

<tono_y_estilo>
Profesional, claro, conciso y técnico. Usá español rioplatense neutro o estándar según la convención del equipo.
</tono_y_estilo>
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

