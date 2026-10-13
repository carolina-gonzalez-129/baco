#Queda por definir si tengo q usar tools o q
from fastmcp import FastMCP
from baco.agent import create_agent

mcp = FastMCP(name="baco-mcp")

def get_baco_agent():
    return create_agent()

@mcp.tool()
def consultar_agente_baco(prompt: str) -> str:
    """Co-editor experto BACO: audita pautas editoriales, normaliza estilo a verbos en infinitivo
    y estructura artículos técnicos bajo las plantillas oficiales de Finnegans (Instructivo / Soluciones)."""
    baco = create_agent()
    respuesta = baco(prompt)
    return str(respuesta)

mcp_http_app = mcp.http_app(path="/mcp")