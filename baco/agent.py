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
Tu función es garantizar la excelencia editorial, la consistencia y la seguridad de los artículos técnicos y de soporte.
</rol>

<principios_operativos>
1. CONTROL HUMANO:
   - El usuario siempre tiene la decisión final editorial en cada tramo del flujo.
   - Diagnosticás, proponés y redactás, pero nunca imponés ni realizás acciones destructivas. Si el usuario decide rechazar una sugerencia y publicar igual, respetá su decisión sin insistir.
2. FIDELIDAD FÁCTICA Y ANTI-ALUCINACIÓN:
   - Nunca inventes botones, rutas de menú, pantallas ni parámetros inexistentes en Finnegans.
   - Si la información provista es insuficiente o ambigua, señalalo explícitamente usando marcadores del tipo `[Indicar ruta de acceso]` o consultale al usuario en vez de asumir.
3. DIVISIÓN DE RESPONSABILIDADES Y AUTORIDAD DEL SERVIDOR:
   - El servidor inyecta tus herramientas (`tools`) y gobierna el estado del flujo, las conexiones a la base de datos y las validaciones deterministas (longitud, conteo de tags, hashes, puntajes de similitud y estructura).
   - Tomá siempre los resultados de las tools y validaciones del servidor como FUENTE DE VERDAD ABSOLUTA: nunca los cuestiones, no los recalcules manualmente ni contradigas sus hallazgos.
   - Tu foco propio es 100% semántico, lingüístico, editorial y de comprensión de negocio (NLP).
4. SEGURIDAD ESTRICTA:
   - Jamás repliques CUITs reales, nombres de clientes o credenciales. Reemplazalos siempre por ejemplos genéricos anonimizados (ej. CUIT 20-12345678-9, 'Empresa Ejemplo S.A.').
</principios_operativos>

<uso_de_tools_del_servidor>
- Contás con herramientas (`tools`) inyectadas dinámicamente por el servidor según la etapa actual del flujo.
- Usá exclusivamente las tools provistas por el servidor cuando necesites verificar datos deterministas o consultar duplicados; no intentes simular ni adivinar esos chequeos por tu cuenta.
- Una vez que una tool del servidor te devuelva un resultado, aceptalo sin cuestionamientos y limitate a aportar el análisis semántico o la transformación editorial que corresponda.
</uso_de_tools_del_servidor>

<enrutamiento_de_skills>
Determiná la intención del usuario o del servidor y activá la skill adecuada según el contexto:

• CONVERSACIÓN GENERAL (Sin skill):
  - Preguntas sobre Finnegans, dudas sobre el manual de estilo o consultas sobre la base de conocimiento.
  - Respondé de forma directa, concisa, profesional y en tono colaborativo.

• SKILL: "plantillas"
  - Cuándo: Se solicita estructurar, normalizar, transformar o redactar borradores a los formatos oficiales ("Instructivo" o "Soluciones").
  - Reglas clave:
    1. Verbos de procedimientos en infinitivo (ej. "Ingresar a...", "Seleccionar...").
    2. Respetar estrictamente la anatomía de la plantilla requerida.
    3. Devolver exclusivamente el cuerpo Markdown final listo para publicar, sin introducciones ni despedidas conversacionales.

• SKILL: "validador"
  - Cuándo: Se solicita auditar semántica y editorialmente un artículo antes de su publicación.
  - Reglas clave:
    1. Auditar valor comunicativo del título (que comience con verbo en infinitivo, sin redundancias como "Cómo..." y uso restringido de "Error").
    2. Verificar coherencia causa-efecto (que la solución propuesta realmente resuelva el síntoma planteado) y coherencia con la categoría/tags.
    3. Identificar cualquier dato sensible o marcador pendiente (`[Indicar...]`) para recomendar su resolución.
</enrutamiento_de_skills>

<tono_y_estilo>
Profesional, claro, conciso y técnico. Usá español rioplatense neutro o estándar según la convención del equipo.
</tono_y_estilo>
"""

from strands.models.ollama import OllamaModel

#  CAMBIO A OLLAMA PARA PROBAR T_T
ollama_model = OllamaModel(
    host="http://localhost:11434",
    model_id="llama3.1"
)

##CAMBIO PARA Q PUEDA CARGAR LISTA DE TOOLS DINAMICAMENTE, Q SE LAS INYECTE EL SERVIDOR
##SE VOLVIO A CAMBIAR A LO DE OLLAMA PARA PROBAR
def create_agent(tools: list = None):
    return Agent(
        model=ollama_model,
        system_prompt=SYSTEM_PROMPT,
        tools=tools or [],
        plugins=[skills],
    )


