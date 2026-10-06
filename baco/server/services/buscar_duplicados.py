from baco.server.db.config import get_conn
#ESTO SERA CON HEADERS ej consulta pasos a seguir etc


def evaluar_nuevo_articulo_con_headers(titulo:str,texto:str=None):
    return evaluar_coincidencias(titulo,texto,True)

def evaluar_nuevo_articulo_sin_headers(titulo:str,texto:str=None):
    return evaluar_coincidencias(titulo,texto,False)

def evaluar_coincidencias(titulo:str,texto:str,headers:bool):
    with get_conn() as conn:
        with conn.cursor() as cur:
            if coincide_titulo := evaluar_titulo(titulo,cur):
                return coincide_titulo
            if texto and texto.strip():
                return evaluar_texto(texto,headers,titulo,cur)
    return None


def evaluar_titulo(titulo:str,cur):
    if exactos_titulo := buscar_por_titulo(titulo,cur):
        return {
            "mensaje": "Ya existe un artículo con exactamente este título, te gustaria actualizarlo?.",
            "coincidencias": exactos_titulo
        }
    if serie:= buscar_por_serie(titulo,cur):
        return {
            "mensaje": f"Parece una nueva edición de la serie '{serie[0]['base_titulo']}'.",
            "coincidencias": serie
        }
    if similares :=buscar_por_titulo_trigrama(titulo,0.70,cur):
        return{
            "mensaje": "Encontramos títulos muy parecidos, te gustaria actualizarlo?.",
            "coincidencias": similares
        }
    return None

    #En ambos casos del embedding es quitando el ruido que la estructura de las plantillas podria producir
    #ej las que son de soluciones en teoria siempre tendrian que tener Consulta seguido de Respiuesta pasos a seguir
    #etc, eso puede inducir a falsos positivos solo xq coincida eso, asiq por eso aunque sea con o sin headers
    #siempre se compara sin eso para los embeddings
def evaluar_texto(texto:str, headers:bool,titulo,cur):
    if headers:
        exactos_texto = buscar_por_texto(texto,cur)
    else:
        exactos_texto=buscar_por_texto_sin_headers(texto,cur)
    if exactos_texto:
        return {
            "mensaje": "Encontramos un texto con exactamente la misma descripcion",
            "coincidencias": exactos_texto
        }
    if similares_embeddings :=buscar_en_embeddings(texto,titulo,cur):
        return{
            "mensaje": "Encontramos otros articulos similares que quizas te gustaria consultar :",
            "coincidencias": similares_embeddings
        }

#VER DE ESTE CONFIGURARLO PARA QUE RECIBA EL CUR DEL SERVIDOR APENAS SE INICIA-!
def buscar_por_titulo(titulo: str, cur):
    return buscar_generico("titulo", titulo, cur, 1)

def buscar_por_texto(texto: str, cur):
    return buscar_generico("texto", texto, cur, 1)

CAMPOS_PERMITIDOS = {
    "titulo": "hash_titulo",
    "texto": "hash_texto",
    "texto_sin_headers": "hash_texto_sin_headers",
}

#Busqueda exacta, generico es el campo ya que hay dos indices hash_titulo y hash_texto
#Los indices son b+tree
def buscar_generico(campo: str, valor: str, cur, limite: int = 5):
    if not valor or not valor.strip():
        return []
    columna = CAMPOS_PERMITIDOS.get(campo)
    if not columna:
        raise ValueError("Campo no permitido")
    query = f"""
        SELECT id, titulo, url
        FROM articulos
        WHERE {columna} = md5(normalizar_texto(%s))
        ORDER BY id
        LIMIT %s
    """
    cur.execute(query, (valor, limite))
    return cur.fetchall()



def buscar_por_serie(titulo: str, cur, limite=5):
    query = """
            SELECT id, titulo, url, base_titulo
            FROM articulos
            WHERE base_titulo = titulo_base(normalizar_texto(%s))
              AND base_titulo <> ''
            ORDER BY id DESC
            LIMIT %s; \
            """
    cur.execute(query, (titulo, limite))
    return cur.fetchall()

#pg_trgm es para determinar similitud entre textos basado en trigram matching
#es clave usar lo del gin, no olvidar, aca creo q no lo estoy usando asiq deberia
def buscar_por_titulo_trigrama(titulo: str, threshold: float = 0.70, cur=None):
    query = """
            SELECT id, titulo, url,
                   similarity(titulo_normalizado, normalizar_texto(%s)) AS score
            FROM articulos
            WHERE titulo_normalizado %% normalizar_texto(%s)
            ORDER BY score DESC, id ASC
            LIMIT 10; \
            """
    cur.execute(
        "SELECT set_config('pg_trgm.similarity_threshold', %s, true)",
        (str(threshold),),
    )
    cur.execute(query, (titulo, titulo))
    return cur.fetchall()

def buscar_por_texto_sin_headers(texto: str, cur, limite: int = 1):
    if not texto or not texto.strip():
        return []
    query = """
            SELECT id, titulo, url
            FROM articulos
            WHERE hash_texto_sin_headers = md5(normalizar_texto(limpiar_headers(%s)))
            ORDER BY id
            LIMIT %s; \
            """
    cur.execute(query, (texto, limite))
    return cur.fetchall()



def buscar_en_embeddings(texto: str, titulo: str, cur):
    if not texto or not texto.strip():
        return []
    from baco.server.services.embeddings import embedding_texto, embedding_titulo
    umbral = 0.80
    limite = 5
    cur.execute("SELECT limpiar_headers(%s);", (texto,))
    texto_sin_headers = cur.fetchone()[0]
    vector_texto = embedding_texto([texto_sin_headers])[0]
    vector_titulo = embedding_titulo([titulo if titulo else ""])[0]
    str_vec_texto = "[" + ",".join(str(f) for f in vector_texto) + "]"
    str_vec_titulo = "[" + ",".join(str(f) for f in vector_titulo) + "]"
    query = """
            WITH candidatos AS (
                (SELECT id FROM articulos
                 ORDER BY embedding_texto <=> %s::vector
                 LIMIT 20)
                UNION
                (SELECT id FROM articulos
                 ORDER BY embedding_titulo <=> %s::vector
                 LIMIT 20)
            ),
                 puntuados AS (
                     SELECT a.id, a.titulo, a.url,
                            round((1 - (a.embedding_texto <=> %s::vector))::numeric, 3) AS sim_texto,
                            round((1 - (a.embedding_titulo <=> %s::vector))::numeric, 3) AS sim_titulo
                     FROM articulos a
                              JOIN candidatos c ON a.id = c.id
                 )
            SELECT id, titulo, url, sim_texto, sim_titulo,
                   round((0.7 * sim_texto + 0.3 * sim_titulo)::numeric, 3) AS score_total
            FROM puntuados
            WHERE (0.7 * sim_texto + 0.3 * sim_titulo) >= %s
            ORDER BY score_total DESC
            LIMIT %s; \
            """
    cur.execute(query, (
        str_vec_texto,
        str_vec_titulo,
        str_vec_texto,
        str_vec_titulo,
        umbral,
        limite
    ))
    return cur.fetchall()