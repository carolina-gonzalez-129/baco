import time
t0 = time.perf_counter()

from psycopg import sql
from baco.server.services.normalizar import normalizar, calcular_hash
from baco.server.db.config import get_conn

print(f"imports: {(time.perf_counter() - t0):.2f} s")

# Modulo de busqueda determinista
# IMPORTANTE : TODO LO DE NORMALIZAR Y HASHEAR PARA CONSISTENCIA RESPECTO
# A LO ALMACENADO SE GENERA A PARTIR DE NORMALIZAR.PY
#EMBEDDINGS NO NORMALIZAR
#1) buscar_generico(texto), si pasa va a pg_trgm con gin, si pasa se evalua el texto (la descripcion)
# aplicando los mismos pasos, si pasa se le calcula el embedding a ambos con sentence transformers xq no tenemos un modelo fijado
#y se hace una comparacion ponderada donde el titulo pese mas, de los embeddings.

#USAR PG_TRGM CON GIN
#Y por ultimo embeddings de ponderacion de ambos, ir calibrando empiricamente el peso
#TMB tener en cuenta lo de que ya puedan haberme mandado categoria m  para mas adelante


COLUMNAS_PERMITIDAS = {
    "titulo": "hash_titulo",
    "texto": "hash_texto",
}

def buscar_generico(campo: str, valor: str, limite: int = 5):
    columna = COLUMNAS_PERMITIDAS.get(campo)
    if columna is None:
        raise ValueError("Campo no valido")

    t0 = time.perf_counter()
    hash_valor = calcular_hash(valor)
    t1 = time.perf_counter()

    query = sql.SQL("""
                    SELECT id, titulo, url
                    FROM articulos
                    WHERE {col} = %s
                    ORDER BY id
                    LIMIT %s
                    """).format(col=sql.Identifier(columna))

    with get_conn() as conn:
        t2 = time.perf_counter()          # conexión lista
        with conn.cursor() as cur:
            cur.execute(query, (hash_valor, limite))
            filas = cur.fetchall()
        t3 = time.perf_counter()          # query terminada

    print(
        f"hash: {(t1-t0)*1000:.1f} ms | "
        f"conexión: {(t2-t1)*1000:.1f} ms | "
        f"query: {(t3-t2)*1000:.1f} ms"
    )
    return [{"id": i, "titulo": t, "url": u} for i, t, u in filas]

#PARA REDUCIR LATENCIA
def comparar_por_embeddings(titulo, texto):
    from baco.server.services.embeddings import embedding_texto
    #Y titulo tmb
    ...

#PRUEBA

if __name__ == "__main__":
    #Buscar algo dsps para medir latencia.

    #HAY QUE ARREGLAR DESPUES LO DE QUE LA CONEXION SEA ALGO QUE SE COMPARTE EN UN POOL PARA QUE
    #NO TARDE TANTO, ES LO QUE MAS TARDA DE TODO.
    print(buscar_generico("titulo","Tablero de análisis de tropa",3))
print(buscar_generico("titulo","Preguntas Frecuentes",3))
