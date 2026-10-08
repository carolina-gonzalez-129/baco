# ESTO QUIZAS HAYA QUE MODIFICARLO DSPS SI NOS CONFIRMAN Q PREFIEREN Q USEMOS LA API
# PARA Q EN VEZ DE SER UN MODULO DE CONSULTAS A POSTGRES SEA DE CONSULTAS A LA API DE FINNEGANS DIRECTO

CAMPOS_PERMITIDOS = {
    "titulo": "hash_titulo",
    "texto": "hash_texto",
    "texto_sin_headers": "hash_texto_sin_headers",
}

class BuscadorDuplicados:
    def __init__(self, db):
        self.cur = db

    def evaluar_nuevo_articulo_con_headers(self, titulo: str, texto: str):
        return self.evaluar_coincidencias(titulo, headers=True, texto=texto)

    def evaluar_nuevo_articulo_sin_headers(self, titulo: str, texto: str):
        return self.evaluar_coincidencias(titulo, headers=False, texto=texto)

    def evaluar_coincidencias(self, titulo: str, headers: bool = True, texto: str = None):
        if coincide_titulo := self.evaluar_titulo(titulo):
            return coincide_titulo
        if texto and texto.strip():
            return self.evaluar_texto(texto, headers, titulo)
        return None

    @staticmethod
    def _extraer_url(coincidencia):
        if not coincidencia:
            return None
        return coincidencia["url"] if isinstance(coincidencia, dict) else coincidencia[2]

    def evaluar_titulo(self, titulo: str, limite: int = 5):
        if exactos_titulo := self.buscar_por_titulo(titulo, limite=1):
            link = self._extraer_url(exactos_titulo[0])
            return {
                "mensaje": f"Ya existe un artículo con exactamente este título ({link}), ¿te gustaría actualizarlo?",
                "link": link,
                "coincidencias": exactos_titulo
            }
        if serie := self.buscar_por_serie(titulo, limite=limite):
            base_nombre = serie[0]["base_titulo"] if isinstance(serie[0], dict) else serie[0][3]
            link = self._extraer_url(serie[0])
            return {
                "mensaje": f"Parece una nueva edición de la serie '{base_nombre}' ({link}).",
                "link": link,
                "coincidencias": serie
            }
        if similares := self.buscar_por_titulo_trigrama(titulo, threshold=0.70, limite=limite):
            link = self._extraer_url(similares[0])
            return {
                "mensaje": f"Encontramos títulos muy parecidos. El más similar es {link}, ¿te gustaría actualizar el artículo existente?",
                "link": link,
                "coincidencias": similares
            }
        return None

    # En ambos casos del embedding es quitando el ruido que la estructura de las plantillas podria producir
    # ej las que son de soluciones en teoria siempre tendrian que tener Consulta seguido de Respiuesta pasos a seguir
    # etc, eso puede inducir a falsos positivos solo xq coincida eso, asiq por eso aunque sea con o sin headers
    # siempre se compara sin eso para los embeddings
    def evaluar_texto(self, texto: str, headers: bool, titulo: str, limite: int = 5):
        if headers:
            exactos_texto = self.buscar_por_texto(texto, limite=1)
        else:
            exactos_texto = self.buscar_por_texto_sin_headers(texto, limite=1)
        if exactos_texto:
            link = self._extraer_url(exactos_texto[0])
            return {
                "mensaje": f"Encontramos un texto con exactamente la misma descripción ({link})",
                "link": link,
                "coincidencias": exactos_texto
            }
        if similares_embeddings := self.buscar_en_embeddings(texto, titulo, limite=limite):
            return {
                "mensaje": "Encontramos otros articulos similares que quizas te gustaria consultar :",
                "coincidencias": similares_embeddings
            }
        return None

    def buscar_por_titulo(self, titulo: str, limite: int = 1):
        return self.buscar_exacto("titulo", titulo, limite)

    def buscar_por_texto(self, texto: str, limite: int = 1):
        return self.buscar_exacto("texto", texto, limite)

    # Busqueda exacta, generico es el campo ya que hay dos indices hash_titulo y hash_texto
    # Los indices son b+tree
    def buscar_exacto(self, campo: str, valor: str, limite: int = 5):
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
        self.cur.execute(query, (valor, limite))
        return self.cur.fetchall()

    def buscar_por_serie(self, titulo: str, limite: int = 5):
        if not titulo or not titulo.strip():
            return []
        query = """
                SELECT id, titulo, url, base_titulo
                FROM articulos
                WHERE base_titulo = titulo_base(normalizar_texto(%s))
                  AND base_titulo <> ''
                ORDER BY id DESC
                LIMIT %s;
                """
        self.cur.execute(query, (titulo, limite))
        return self.cur.fetchall()

    # pg_trgm es para determinar similitud entre textos basado en trigram matching
    # es clave usar lo del gin, no olvidar, aca creo q no lo estoy usando asiq deberia
    def buscar_por_titulo_trigrama(self, titulo: str, threshold: float = 0.70, limite: int = 10):
        if not titulo or not titulo.strip():
            return []

        query = """
                SELECT id, titulo, url,
                       similarity(titulo_normalizado, normalizar_texto(%s)) AS score
                FROM articulos
                WHERE titulo_normalizado %% normalizar_texto(%s)
                ORDER BY score DESC, id
                LIMIT %s;
                """
        self.cur.execute(
            "SELECT set_config('pg_trgm.similarity_threshold', %s, true)",
            (str(threshold),),
        )
        self.cur.execute(query, (titulo, titulo, limite))
        return self.cur.fetchall()

    def buscar_por_texto_sin_headers(self, texto: str, limite: int = 1):
        if not texto or not texto.strip():
            return []
        query = """
                SELECT id, titulo, url
                FROM articulos
                WHERE hash_texto_sin_headers = md5(normalizar_texto(limpiar_headers(%s)))
                ORDER BY id
                LIMIT %s;
                """
        self.cur.execute(query, (texto, limite))
        return self.cur.fetchall()

    def buscar_en_embeddings(self, texto: str, titulo: str, umbral: float = 0.80, limite: int = 5):
        if not texto or not texto.strip():
            return []

        from baco.server.services.embeddings import embedding_texto, embedding_titulo
        # LO DE ABAJO ES IMPORTANTE IR CALIBRANDOLO CUANDO GENERE MIS PARES ETIQUETADOS DE DUPLICADOS/NODUPLICADOS/AMBIGUOS
        self.cur.execute("SELECT limpiar_headers(%s);", (texto,))
        row = self.cur.fetchone()
        texto_sin_headers = (row[0] or "") if row else ""
        if not texto_sin_headers.strip():
            return []

        vector_texto_res = embedding_texto([texto_sin_headers])
        vector_texto = vector_texto_res[0] if vector_texto_res else None
        if not vector_texto:
            return []

        vector_titulo_res = embedding_titulo([titulo]) if (titulo and titulo.strip()) else None
        vector_titulo = vector_titulo_res[0] if vector_titulo_res else None

        str_vec_texto = "[" + ",".join(str(f) for f in vector_texto) + "]"

        if vector_titulo:
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
                    LIMIT %s;
                    """
            self.cur.execute(query, (
                str_vec_texto,
                str_vec_titulo,
                str_vec_texto,
                str_vec_titulo,
                umbral,
                limite
            ))
        else:
            query = """
                    WITH candidatos AS (
                        SELECT id FROM articulos
                        ORDER BY embedding_texto <=> %s::vector
                        LIMIT 20
                    ),
                         puntuados AS (
                             SELECT a.id, a.titulo, a.url,
                                    round((1 - (a.embedding_texto <=> %s::vector))::numeric, 3) AS sim_texto,
                                    0.0 AS sim_titulo
                             FROM articulos a
                                      JOIN candidatos c ON a.id = c.id
                         )
                    SELECT id, titulo, url, sim_texto, sim_titulo,
                           sim_texto AS score_total
                    FROM puntuados
                    WHERE sim_texto >= %s
                    ORDER BY score_total DESC
                    LIMIT %s;
                    """
            self.cur.execute(query, (
                str_vec_texto,
                str_vec_texto,
                umbral,
                limite
            ))
        return self.cur.fetchall()
