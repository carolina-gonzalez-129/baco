import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from baco.server.services.normalizar import normalizar, calcular_hash
from baco.server.db.config import get_conn
# Modulo de busqueda determinista
# IMPORTANTE : TODO LO DE NORMALIZAR Y HASHEAR PARA CONSISTENCIA RESPECTO
# A LO ALMACENADO SE GENERA A PARTIR DE NORMALIZAR.PY


def buscar_titulo(titulo: str, limite: int = 5):
    # recibo un titulo, lo hasheo (internamente se normaliza)
    # y lo busco en el arbol b
    hash_titulo = calcular_hash(titulo)
    if hash_titulo is None:
        return []
    # Me quedo con el titulo y url para despues poder mostrarlas al user como posibles
    with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT titulo, url
                FROM articulos
                WHERE hash_titulo = %s
                ORDER BY id
                LIMIT %s
                """,
                (hash_titulo, limite),
            )

            return [
                {"titulo": t, "url": u}
                for id_, t, u in cur.fetchall()
            ]

#PRUEBA
if __name__ == "__main__":
    print(buscar_titulo("Wazuh no genera reportes - Limpiar indices", 3))