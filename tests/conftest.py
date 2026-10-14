import pytest
import psycopg
try:
    from testcontainers.community.postgres import PostgresContainer
except ImportError:
    from testcontainers.postgres import PostgresContainer
from baco.server.db.cargar_articulos_postgres import DDL_SCHEMA


@pytest.fixture(scope="session")
def postgres_container():
    """Inicia un contenedor de Docker con PostgreSQL 16 y extensión pgvector para integración y E2E."""
    with PostgresContainer("pgvector/pgvector:pg16") as postgres:
        url = postgres.get_connection_url().replace("+psycopg2", "").replace("+asyncpg", "")
        with psycopg.connect(url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(DDL_SCHEMA)
        yield postgres


@pytest.fixture
def db_conn(postgres_container):
    """Provee una conexión limpia de PostgreSQL para cada test."""
    url = postgres_container.get_connection_url().replace("+psycopg2", "").replace("+asyncpg", "")
    with psycopg.connect(url) as conn:
        yield conn
        conn.rollback()
