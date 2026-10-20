from psycopg.rows import dict_row
from baco.agent import create_agent
from baco.server.db.config import get_ro_conn
from baco.server.services.buscar_duplicados import BuscadorDuplicados
get_conn = get_ro_conn

def get_buscador_duplicados():
    conn_fn = get_conn if get_conn is not get_ro_conn else get_ro_conn
    with conn_fn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            yield BuscadorDuplicados(cur)


def get_baco_agent():
    return create_agent()
