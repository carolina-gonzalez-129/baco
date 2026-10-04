import os
from pathlib import Path
from dotenv import load_dotenv
import psycopg

# Buscar y cargar el archivo .env desde la raíz del proyecto
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


def get_conn(dbname: str = None, autocommit: bool = False):
    """Retorna una conexión activa a PostgreSQL usando psycopg (v3).

    Args:
        dbname: Nombre de la base de datos (por defecto DB_NAME).
        autocommit: Si es True, habilita autocommit (para CREATE DATABASE, etc.).
    """
    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=dbname or DB_NAME,
        autocommit=autocommit,
    )
