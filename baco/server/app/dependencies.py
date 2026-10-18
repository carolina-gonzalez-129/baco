from psycopg.rows import dict_row
from baco.agent import create_agent
from baco.server.db.config import get_conn
from baco.server.services.buscar_duplicados import BuscadorDuplicados

def get_buscador_duplicados():
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            yield BuscadorDuplicados(cur)

def get_baco_agent():
    return create_agent()