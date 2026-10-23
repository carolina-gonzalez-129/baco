import os
import subprocess
import sys
import pytest
import psycopg
import psycopg_pool
from psycopg.errors import InsufficientPrivilege, ReadOnlySqlTransaction

import baco.server.db.config as cfg


def test_db_ro_pool_esta_configurado_correctamente():
    """El pool de solo lectura debe existir, tener tamaño 2-10 y check_connection activado."""
    pool = cfg.crear_ro_pool()
    assert pool is not None
    assert pool.min_size == 2
    assert pool.max_size == 10
    assert pool.check is not None


def test_escritura_via_get_ro_conn_falla_con_error_de_permisos():
    """Cualquier intento de INSERT, UPDATE o DELETE a través de get_ro_conn() debe ser

    rechazado de inmediato por PostgreSQL (InsufficientPrivilege o ReadOnlySqlTransaction).
    """
    try:
        pool = cfg.crear_ro_pool()
        pool.open(wait=True)
        cfg.db_ro_pool = pool
        try:
            with cfg.get_ro_conn() as conn:
                with conn.cursor() as cur:
                    # 1. Probar INSERT
                    with pytest.raises((InsufficientPrivilege, ReadOnlySqlTransaction)):
                        cur.execute("INSERT INTO tags (name) VALUES ('tag_prohibido_test');")
                    conn.rollback()

                    # 2. Probar UPDATE
                    with pytest.raises((InsufficientPrivilege, ReadOnlySqlTransaction)):
                        cur.execute("UPDATE articulos SET titulo = 'Hack' WHERE id = 1;")
                    conn.rollback()

                    # 3. Probar DELETE
                    with pytest.raises((InsufficientPrivilege, ReadOnlySqlTransaction)):
                        cur.execute("DELETE FROM articulos WHERE id = 1;")
                    conn.rollback()

                    # 4. Verificar que la sesión de PostgreSQL tiene transaction_read_only = on
                    cur.execute("SHOW transaction_read_only;")
                    ro_setting = cur.fetchone()[0]
                    assert ro_setting == "on"
        finally:
            pool.close()
    except (psycopg.OperationalError, psycopg_pool.PoolTimeout):
        pytest.skip("Base de datos PostgreSQL local no alcanzable en este entorno.")


def test_fail_fast_sin_db_ro_user():
    """Verifica que si falta DB_RO_USER, baco.server.db.config lanza RuntimeError al arrancar."""
    cmd = [
        sys.executable,
        "-c",
        (
            "import os, importlib\n"
            "os.environ['DB_RO_USER'] = ''\n"
            "try:\n"
            "    import baco.server.db.config\n"
            "    print('NO_FALLO')\n"
            "except RuntimeError as e:\n"
            "    print('FAIL_FAST_OK')\n"
        ),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert "FAIL_FAST_OK" in res.stdout


def test_fail_fast_sin_db_ro_password():
    """Verifica que si falta DB_RO_PASSWORD, baco.server.db.config lanza RuntimeError al arrancar."""
    cmd = [
        sys.executable,
        "-c",
        (
            "import os, importlib\n"
            "os.environ['DB_RO_PASSWORD'] = ''\n"
            "try:\n"
            "    import baco.server.db.config\n"
            "    print('NO_FALLO')\n"
            "except RuntimeError as e:\n"
            "    print('FAIL_FAST_OK')\n"
        ),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert "FAIL_FAST_OK" in res.stdout


def test_consumidores_usan_get_ro_conn_y_no_psycopg_connect_suelto():
    """Verifica estáticamente que dependencies.py y mcp_server.py usen get_ro_conn."""
    import inspect
    from baco.server.app import dependencies, mcp_server

    src_dep = inspect.getsource(dependencies)
    src_mcp = inspect.getsource(mcp_server)

    assert "get_ro_conn" in src_dep
    assert "get_ro_conn" in src_mcp
    assert "psycopg.connect(" not in src_dep
