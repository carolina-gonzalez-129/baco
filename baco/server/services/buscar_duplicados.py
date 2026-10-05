import time
t0 = time.perf_counter()

from psycopg import sql
from baco.server.db.config import get_conn

print(f"imports: {(time.perf_counter() - t0):.2f} s")

# Modulo de busqueda determinista
# NOTA: Normalización y hash MD5 están automatizados en PostgreSQL con normalizar_texto()
# y columnas GENERATED ALWAYS AS ... STORED.

def buscar_por_titulo(titulo: str):
    return buscar_generico("titulo", titulo, 1)

def buscar_por_texto(texto: str):
    return buscar_generico("texto", texto, 1)


COLUMNAS_PERMITIDAS = {
    "titulo": "hash_titulo",
    "texto": "hash_texto",
}

def buscar_generico(campo: str, valor: str, limite: int = 5):
    columna = COLUMNAS_PERMITIDAS.get(campo)
    if columna is None:
        raise ValueError("Campo no valido")

    if not valor or not valor.strip():
        return []

    t0 = time.perf_counter()
    # Delegamos normalización y MD5 a PostgreSQL usando la función inmutable normalizar_texto()
    query = sql.SQL("""
                    SELECT id, titulo, url
                    FROM articulos
                    WHERE {col} = md5(normalizar_texto(%s))
                    ORDER BY id
                    LIMIT %s
                    """).format(col=sql.Identifier(columna))

    with get_conn() as conn:
        t2 = time.perf_counter()          # conexión lista
        with conn.cursor() as cur:
            cur.execute(query, (valor, limite))
            filas = cur.fetchall()
        t3 = time.perf_counter()          # query terminada

    print(
        f"conexión: {(t2-t0)*1000:.1f} ms | "
        f"query: {(t3-t2)*1000:.1f} ms"
    )
    return [{"id": i, "titulo": t, "url": u} for i, t, u in filas]

#PRUEBA

if __name__ == "__main__":
    #Buscar algo dsps para medir latencia.

    #HAY QUE ARREGLAR DESPUES LO DE QUE LA CONEXION SEA ALGO QUE SE COMPARTE EN UN POOL PARA QUE
    #NO TARDE TANTO, ES LO QUE MAS TARDA DE TODO.
    print(buscar_generico("titulo","Tablero de análisis de tropa",3))
    print(buscar_generico("titulo","Preguntas Frecuentes",3))
