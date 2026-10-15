import os
import logging
from pathlib import Path
from dotenv import load_dotenv
import psycopg
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

_current_dir = Path(__file__).resolve().parent
for p in [_current_dir, *_current_dir.parents]:
    env_file = p / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        break
else:
    load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME", "baco_db")
CONN_INFO = f"host={DB_HOST} port={DB_PORT} user={DB_USER} password={DB_PASSWORD} dbname={DB_NAME}"

# quizas preguntar a emiliano si quiere q sean mas, x defecto sino son 100 conexiones
#postgres sugiere q el nro optimo es CPU cores * 2 + effective spindle count
##el nro optimo deberiamos definirlo con ellos, y modificar acá.
db_pool = ConnectionPool(
    conninfo=CONN_INFO,
    min_size=2,
    max_size=20,
    open=False,
    check=ConnectionPool.check_connection
)
# el me permite obtenerlas y el servidor abre el pool para que pueda tomarlas (tmb lo cierra)
# PERO NO ES PARA TODAS PORQ MUCHOS SCRIPTS USAN CONEXIONES SIN SER PROVISTAS X EL SERVIDOR!!

def get_conn(dbname: str = None, autocommit: bool = False):
    target_db = dbname or DB_NAME
    if not autocommit and target_db == DB_NAME:
        if db_pool is not None and not db_pool.closed:
            return db_pool.connection()
        logger.warning("Pool cerrado: usando conexión directa a %s", target_db)
    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=target_db,
        autocommit=autocommit,
    )
