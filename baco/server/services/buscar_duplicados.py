
from baco.server.db.config import get_conn


# Modulo de busqueda determinista
# NOTA: Normalización y hash MD5 están automatizados en PostgreSQL con normalizar_texto()
# y columnas GENERATED ALWAYS AS ... STORED.

#Nivel 1 del pipeline
def buscar_por_titulo(titulo: str):
    return buscar_generico("titulo", titulo, 1)

def buscar_por_texto(texto: str):
    return buscar_generico("texto", texto, 1)


COLUMNAS_PERMITIDAS = {
    "titulo": "hash_titulo",
    "texto": "hash_texto",
}

#Busqueda exacta
def buscar_generico(campo: str, valor: str, limite: int = 5):
    columna = COLUMNAS_PERMITIDAS.get(campo)
    if columna is None:
        raise ValueError("Campo no valido")

    if not valor or not valor.strip():
        return []


    if columna == "hash_titulo":
        query = """
                SELECT id, titulo, url
                FROM articulos
                WHERE hash_titulo = md5(normalizar_texto(%s))
                ORDER BY id
                LIMIT %s \
                """
    else:
        query = """
                SELECT id, titulo, url
                FROM articulos
                WHERE hash_texto = md5(normalizar_texto(%s))
                ORDER BY id
                LIMIT %s \
                """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (valor, limite))
            filas = cur.fetchall()

    return [{"id": i, "titulo": t, "url": u} for i, t, u in filas]

#Nivel 2 del pipeline : solo pvg
