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
mcp_http_app = mcp.http_app(path="/mcp", stateless_http=True)
