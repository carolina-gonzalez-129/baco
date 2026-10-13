##EVALUAR SINO SI ELLOS QUIEREN OTRA COSA, ESTOY USANDO EL PATRON AGENT AS MCP TOOL
#MEJORAR SCHEMAS!
#INTERNAMENTE YA VA A TENER SUS SKILLS
from fastmcp import FastMCP
from strands import tool
from contextlib import contextmanager
from baco.agent import create_agent
from baco.server.schemas.articulo import ArticuloSchema
from baco.server.services.validar_articulo import validar_texto_y_estructura_post_duplicados

mcp = FastMCP(name="baco-mcp")
##MEJORAR MUCHISIMO LOS SCHEMAS, ESTA MUY POBRE AUN!
#HACER Q NO RETENGA LA MEMORIA MAS ALLA DE LA SESION Y ASEGURARSE DE Q TIENE ALGUN TIPO DE PERSISTENCIA


@tool
def buscar_duplicados_tool(titulo: str, texto: str | None = None, limite: int = 3) -> dict:
    """Busca si existen artículos duplicados evaluando título y texto semántico."""
    from baco.server.app.api import get_buscador_duplicados
    with contextmanager(get_buscador_duplicados)() as buscador:
        return buscador.evaluar_coincidencias(titulo, True, texto, limite)
@tool
def validar_post_duplicados_tool(titulo: str, texto: str, tags: list[str] = []) -> dict:
    """Valida reglas estructurales como longitud y cantidad de tags."""
    art = ArticuloSchema(id=0, titulo=titulo, texto=texto, tags=[{"name": t} for t in tags])
    return validar_texto_y_estructura_post_duplicados(art)

def get_baco_agent():
    return create_agent(tools=[buscar_duplicados_tool, validar_post_duplicados_tool])

@mcp.tool()
def consultar_agente_baco(prompt: str) -> str:
    """Agente experto BACO: analiza duplicados, valida reglas editoriales y estructura artículos para Finnegans."""
    baco = get_baco_agent()
    respuesta = baco(prompt)
    return str(respuesta)

mcp_http_app = mcp.http_app(path="/mcp")