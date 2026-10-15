import os
import pytest
import psycopg

# Asegurar DISCOURSE_URL para entorno de tests si no está definida
if not os.getenv("DISCOURSE_URL"):
    os.environ["DISCOURSE_URL"] = "https://bc-dev.finneg.com"

from baco.server.db.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD
from baco.server.db.cargar_articulos_postgres import DDL_SCHEMA


class LocalPostgresFallback:
    """Fallback compatible con la API de PostgresContainer cuando Docker no está disponible."""
    def __init__(self, dbname: str = "baco_test_db"):
        self.dbname = dbname

    def get_connection_url(self) -> str:
        pw = f":{DB_PASSWORD}" if DB_PASSWORD else ""
        return f"postgresql://{DB_USER}{pw}@{DB_HOST}:{DB_PORT}/{self.dbname}"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture(scope="session")
def postgres_container():
    """Inicia un contenedor de Docker con PostgreSQL 16 y extensión pgvector para integración y E2E,
    o utiliza fallback transparente a PostgreSQL local con pgvector si Docker no está activo."""
    PostgresContainer = None
    try:
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:
        try:
            from testcontainers.postgres import PostgresContainer
        except ImportError:
            pass

    container = None
    if PostgresContainer is not None:
        try:
            c = PostgresContainer("pgvector/pgvector:pg16")
            c.start()
            container = c
        except Exception:
            container = None

    if container is not None:
        url = container.get_connection_url().replace("+psycopg2", "").replace("+asyncpg", "")
        with psycopg.connect(url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(DDL_SCHEMA)
        yield container
        container.stop()
    else:
        # Fallback a base de datos local
        try:
            with psycopg.connect(
                host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, dbname="postgres", autocommit=True
            ) as admin_conn:
                with admin_conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'baco_test_db';")
                    if not cur.fetchone():
                        cur.execute("CREATE DATABASE baco_test_db;")
        except Exception:
            pass

        fallback = LocalPostgresFallback("baco_test_db")
        url = fallback.get_connection_url()
        with psycopg.connect(url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(DDL_SCHEMA)
        yield fallback


@pytest.fixture
def db_conn(postgres_container):
    """Provee una conexión limpia de PostgreSQL para cada test."""
    url = postgres_container.get_connection_url().replace("+psycopg2", "").replace("+asyncpg", "")
    with psycopg.connect(url) as conn:
        yield conn
        conn.rollback()


@pytest.fixture
def clean_db(db_conn):
    """Fixture que hace TRUNCATE de las tablas entre tests para que no dependan del orden."""
    with db_conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE articulo_tags, articulos, tags, categorias RESTART IDENTITY CASCADE;")
    db_conn.commit()
    yield db_conn
    with db_conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE articulo_tags, articulos, tags, categorias RESTART IDENTITY CASCADE;")
    db_conn.commit()
