import sys
from pathlib import Path
from psycopg import sql

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from baco.server.services.normalizar import normalizar, calcular_hash
from baco.server.db.config import get_conn
# Modulo de busqueda determinista
# IMPORTANTE : TODO LO DE NORMALIZAR Y HASHEAR PARA CONSISTENCIA RESPECTO
# A LO ALMACENADO SE GENERA A PARTIR DE NORMALIZAR.PY
#EMBEDDINGS NO NORMALIZAR
#USAR PG_TRGM CON GIN
#Y por ultimo embeddings de ponderacion de ambos, ir calibrando empiricamente el peso
#TMB tener en cuenta lo de que ya puedan haberme mandado categoria m  para mas adelante


COLUMNAS_PERMITIDAS = {
    "titulo": "hash_titulo",
    "texto": "hash_texto",
}
#Para poder usarlo tanto en texto como en titulo
def buscar_generico(campo:str, valor:str, limite: int = 5):
    #Lo busco en un arbol b+ que se creo haciendo indexing, lo hasheo con calcular_hash, e internamente se normaliza
    columna = COLUMNAS_PERMITIDAS.get(campo)
    if columna is None:
        raise ValueError("Campo no valido")
    hash_valor=calcular_hash(valor)
    query = sql.SQL("""
                    SELECT id, titulo, url
                    FROM articulos
                    WHERE {col} = %s
                    ORDER BY id
                    LIMIT %s
                    """).format(col=sql.Identifier(columna))

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(query, (hash_valor, limite))
        return [
            {"id": i, "titulo": t, "url": u}
            for i, t, u in cur.fetchall()
        ]


#PRUEBA
if __name__ == "__main__":
    print(buscar_generico("titulo","Tablero de análisis de tropa",5))
    print(buscar_generico("texto","Consulta\n:\nAl intentar obtener COE para un certificado 1116A de compra de granos aparece un aviso de error.\njava.lang.numberformatexception: For imput string: \"______\"\nimage\n950×752 52.9 KB\nRespuesta:\nEsto sucede porque en la transacción del Análisis de grano vinculado al traslado el campo “Nro. Boletín” tiene cargado un dato que no suma el total de caracteres requeridos por el campo.\nPasos a seguir\n:\nDirigirse a la medicion de granos vinculada al traslado y tomar una de las siguientes acciones:\nDejar vacío el campo Nro. Boletín y guardar el cambio.\nCompletar todos los caracteres del campo y guardar el campo.\nimage\n1016×746 80.9 KB\nLuego de esto se puede volver al certificado y obtener COE.",5))
