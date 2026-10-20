import asyncio
from typing import Optional, List
from fastmcp import FastMCP
from psycopg.rows import dict_row
from baco.server.db.config import get_conn
from baco.server.services.buscar_duplicados import BuscadorDuplicados
from baco.server.services.validar_articulo import validar_texto_y_estructura_post_duplicados
from baco.server.schemas.articulo import ArticuloSchema, Tag
from baco.server.schemas.duplicados import BuscarDuplicadosToolOutput, ArticuloSimilarTool
from baco.server.schemas.validacion import ValidarFormatoToolOutput, HallazgoTool

mcp = FastMCP(name="baco-mcp")


###FALTA MUCHISIMO PARA TENER ESTO BIEN, NO SE SI ESTA BUENO QUE UN AGENTE EJECUTE TOOLS DIRECTAMENTE SOBRE EL MODULO
#DE BUSCAR_DUPLICADOS, QUIZAS ESTARIA BUENO IMPLEMENTAR UNA FACADE QUE LO HAGA Y NO EL DIRECTO
#Quizas se podria usar directamente al orquestador pero eso requeriria que ellos tengan prendido el servidor
#Quizas conviene crear un archivo similar a prueba orquestador, y que las tools lo usen
#para no lidiar directamente con abrir el pool de conexiones mni

def _buscar_duplicados_db(
    titulo: Optional[str] = None,
    borrador: Optional[str] = None,
    limite: int = 3
) -> BuscarDuplicadosToolOutput:
    titulo_limpio = (titulo or "").strip()
    borrador_limpio = (borrador or "").strip()
    if not titulo_limpio and not borrador_limpio:
        return BuscarDuplicadosToolOutput(
            decision_sugerida="crear_nuevo",
            hay_duplicados=False,
            mensaje="No se proporcionó ni título ni borrador para contrastar.",
            url_principal=None,
            articulos_similares=[]
        )

    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            buscador = BuscadorDuplicados(cur)
            resultado = buscador.evaluar_coincidencias(
                titulo=titulo_limpio,
                headers=True,
                texto=borrador_limpio if borrador_limpio else None,
                limite=limite
            )

    articulos = []
    for c in resultado.get("coincidencias", []):
        if c.get("id") and c.get("titulo"):
            articulos.append(
                ArticuloSimilarTool(
                    id=c["id"],
                    titulo=c["titulo"],
                    url=c.get("url", f"https://bc.finneg.com/t/{c['id']}"),
                    score=c.get("score_total")
                )
            )

    hay_duplicados = bool(resultado.get("encontrado"))
    decision_sugerida = "proponer_mejora_existente" if (hay_duplicados or len(articulos) > 0) else "crear_nuevo"

    return BuscarDuplicadosToolOutput(
        decision_sugerida=decision_sugerida,
        hay_duplicados=hay_duplicados,
        mensaje=resultado.get("mensaje", ""),
        url_principal=resultado.get("link"),
        articulos_similares=articulos
    )


@mcp.tool(
    name="buscar_duplicados",
    description=(
        "Herramienta de SOLO LECTURA. Busca artículos duplicados o semánticamente similares "
        "en la Base de Conocimiento a partir de un título, un borrador o ambos. "
        "Devuelve artículos similares existentes y una recomendación ('crear_nuevo' o 'proponer_mejora_existente') "
        "para que el agente decida si redacta un artículo nuevo o propone mejorar uno existente."
    )
)
async def buscar_duplicados(
    titulo: Optional[str] = None,
    borrador: Optional[str] = None,
    limite: int = 3
) -> BuscarDuplicadosToolOutput:
    """Busca artículos similares por título o borrador (solo lectura) para decidir si crear nuevo o mejorar existente.

    Args:
        titulo: Título propuesto para el artículo (opcional si se provee borrador).
        borrador: Texto o cuerpo del borrador a contrastar (opcional si se provee título).
        limite: Cantidad máxima de coincidencias sugeridas (por defecto 3).
    """
    limite_acotado = max(1, min(limite, 3))
    return await asyncio.to_thread(_buscar_duplicados_db, titulo, borrador, limite_acotado)


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