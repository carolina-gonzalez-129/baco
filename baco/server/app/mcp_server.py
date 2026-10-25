import asyncio
from typing import Optional, List
from fastmcp import FastMCP
from psycopg.rows import dict_row
from baco.server.db.config import get_ro_conn
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.validar_articulo import validar_texto_y_estructura_post_duplicados
from baco.server.schemas.articulo import ArticuloSchema, Tag
from baco.server.schemas.duplicados import BuscarDuplicadosToolOutput, ArticuloSimilarTool
from baco.server.schemas.validacion import ValidarFormatoToolOutput, HallazgoTool

mcp = FastMCP(name="baco-mcp")


 #Elimine t odo xq no me convence q las tools abran un pool de conexiones a la db
# para tener un cursor e inyectarlo
 #a nbuscar duplicados,
# mas xq el user q puede hacerlo es baco_readonly q se levanta al levantar el servidor pero se usa en la parte rest
# me da cosa q pueda haber problemas de circularidad, de ultima se podria crear un helper que tmb use ese rol por fuera de api.py
# y q el ejecute, las tools solo lo llamen.



 #recordar q van a ser solo dos tools atómicas por requerimento de emiliano
 #buscar_duplicados y validar_formato
 #cuando ya esten bien falta corregir los schemas ya creados, dsps quizas metodos como \list o discovery, idk


#tool buscar duplicados
# tool validar formato
@mcp.tool(
    name="validar_formato",
    description=(
        "Herramienta de SOLO LECTURA en memoria. Valida la estructura determinista, longitud mínima, "
        "presencia de tags obligatorios y filtros de privacidad (CUITs reales, emails o URLs de prueba) "
        "sobre el borrador de un artículo antes de publicar. Devuelve el diagnóstico y el borrador sanitizado."
    )
)
def validar_formato(
    titulo: str,
    texto: str,
    tags: Optional[List[str]] = None,
    categoria_id: Optional[int] = None
) -> ValidarFormatoToolOutput:
    """Audita reglas deterministas de formato, privacidad y estructura sobre el artículo.

    Args:
        titulo: Título del artículo.
        texto: Cuerpo completo del borrador en Markdown.
        tags: Lista de nombres de etiquetas o tags asignados (se recomiendan al menos 2).
        categoria_id: ID numérico de la categoría de Discourse (opcional).
    """
    tags_objetos = [Tag(name=t.strip()) for t in (tags or []) if t.strip()]
    articulo = ArticuloSchema(
        id=0,
        titulo=titulo,
        texto=texto,
        tags=tags_objetos,
        categoria_id=categoria_id
    )
    resultado = validar_texto_y_estructura_post_duplicados(articulo)

    hallazgos = [
        HallazgoTool(
            severidad=f.get("severity", "Ajuste"),
            campo=f.get("field", "texto"),
            descripcion=f.get("description", ""),
            accion=f.get("action", "")
        )
        for f in resultado.get("findings", [])
    ]

    es_valido = resultado.get("status") != "Pendiente"

    return ValidarFormatoToolOutput(
        valido=es_valido,
        status=resultado.get("status", "Pendiente"),
        titulo_sanitizado=resultado.get("titulo_sanitizado"),
        texto_sanitizado=resultado.get("texto_sanitizado"),
        hallazgos=hallazgos,
        longitud_texto=resultado.get("longitud_texto", 0),
        tags_count=resultado.get("tags_count", 0)
    )


mcp_http_app = mcp.http_app(path="/mcp", stateless_http=True)
