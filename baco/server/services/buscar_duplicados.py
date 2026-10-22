from baco.server.services.reglas_semanticas import son_semanticas_divergentes

CAMPOS_PERMITIDOS = {
    "titulo": "hash_titulo",
    "texto": "hash_texto",
    "texto_sin_headers": "hash_texto_sin_headers",
}

SQL_EMBEDDINGS_CON_TITULO = """
    WITH candidatos AS (
        (SELECT id FROM articulos WHERE embedding_texto IS NOT NULL ORDER BY embedding_texto <=> %s::vector LIMIT %s)
        UNION
        (SELECT id FROM articulos WHERE embedding_titulo IS NOT NULL ORDER BY embedding_titulo <=> %s::vector LIMIT %s)
    ),
    puntuados AS (
        SELECT a.id, a.titulo, a.url, a.titulo_normalizado,
               normalizar_texto(%s) AS consulta_normalizada,
               LEFT(COALESCE(a.texto_normalizado, ''), 1000) AS texto_norm_1000,
               round((1 - (a.embedding_texto <=> %s::vector))::numeric, 3) AS sim_texto,
               round((1 - (a.embedding_titulo <=> %s::vector))::numeric, 3) AS sim_titulo
        FROM articulos a JOIN candidatos c ON a.id = c.id
    )
    SELECT id, titulo, url, titulo_normalizado, consulta_normalizada,
           texto_norm_1000, sim_texto, sim_titulo,
           round((0.8 * sim_texto + 0.2 * sim_titulo)::numeric, 3) AS score_total
    FROM puntuados
    WHERE sim_texto >= 0.90
      AND sim_titulo >= 0.65
      AND ((0.8 * sim_texto + 0.2 * sim_titulo) >= %s OR (sim_texto >= 0.93 AND sim_titulo >= 0.65))
    ORDER BY score_total DESC
    LIMIT %s;
"""

SQL_EMBEDDINGS_SOLO_TEXTO = """
    WITH candidatos AS (
        SELECT id FROM articulos WHERE embedding_texto IS NOT NULL ORDER BY embedding_texto <=> %s::vector LIMIT %s
    ),
    puntuados AS (
        SELECT a.id, a.titulo, a.url, a.titulo_normalizado,
               normalizar_texto(%s) AS consulta_normalizada,
               LEFT(COALESCE(a.texto_normalizado, ''), 1000) AS texto_norm_1000,
               round((1 - (a.embedding_texto <=> %s::vector))::numeric, 3) AS sim_texto,
               0.0 AS sim_titulo
        FROM articulos a JOIN candidatos c ON a.id = c.id
    )
    SELECT id, titulo, url, titulo_normalizado, consulta_normalizada,
           texto_norm_1000, sim_texto, sim_titulo,
           sim_texto AS score_total
    FROM puntuados
    WHERE sim_texto >= %s
    ORDER BY score_total DESC
    LIMIT %s;
"""


def extraer_url(coincidencia):
    if not coincidencia:
        return None
    return coincidencia["url"] if isinstance(coincidencia, dict) else coincidencia[2]


class BuscadorDuplicados:
    def __init__(self, db):
        self.cur = db

    @staticmethod
    def _extraer_url(coincidencia):
        return extraer_url(coincidencia)

    @staticmethod
    def _campo(fila, clave: str, idx: int, min_len: int = 0, default=""):
        if isinstance(fila, dict):
            return fila.get(clave, default)
        return fila[idx] if len(fila) > max(idx, min_len) else default

    def _hallazgo(self, mensaje: str, coincidencias: list) -> dict:
        return {
            "mensaje": mensaje,
            "link": self._extraer_url(coincidencias[0]),
            "coincidencias": coincidencias,
        }

    def _filtrar_divergentes(self, filas: list, titulo: str, texto: str = None, limite: int = None) -> list:
        if not filas or not titulo or not titulo.strip():
            return filas[:limite] if limite else filas
        filtrados = []
        for f in filas:
            cand_raw = self._campo(f, "titulo", 1)
            cand_norm = self._campo(f, "titulo_normalizado", 3, min_len=4, default=cand_raw)
            cons_norm = self._campo(f, "consulta_normalizada", 4, min_len=4, default=titulo)
            cand_txt = self._campo(f, "texto_norm_1000", 5, min_len=8, default="")
            if not son_semanticas_divergentes(
                cand_norm, cons_norm, cand_raw, titulo, cand_texto=cand_txt, cons_texto=texto
            ):
                filtrados.append(f)
            if limite and len(filtrados) >= limite:
                break
        return filtrados

    def evaluar_nuevo_articulo_con_headers(self, titulo: str, texto: str, limite: int = 5):
        return self.evaluar_coincidencias(titulo, headers=True, texto=texto, limite=limite)

    def evaluar_nuevo_articulo_sin_headers(self, titulo: str, texto: str, limite: int = 5):
        return self.evaluar_coincidencias(titulo, headers=False, texto=texto, limite=limite)

    def evaluar_coincidencias(self, titulo: str, headers: bool = True, texto: str = None, limite: int = 5):
        if coincide_titulo := self.evaluar_titulo(titulo, limite=limite):
            return {"encontrado": True, **coincide_titulo}
        if not texto or not texto.strip():
            return {
                "encontrado": False,
                "requiere_texto": True,
                "mensaje": "El título no está duplicado. Indicá el texto para verificar el contenido.",
            }
        if coincide_texto := self.evaluar_texto(texto, headers, titulo, limite=limite):
            return {"encontrado": True, **coincide_texto}
        return {
            "encontrado": False,
            "requiere_texto": False,
            "mensaje": "No se encontraron duplicados, ofrecer publicar!",
        }

    def evaluar_titulo(self, titulo: str, limite: int = 5):
        if exactos := self.buscar_por_titulo(titulo, limite=1):
            return self._hallazgo("Ya existe un artículo con exactamente este título, ¿te gustaría mejorarlo?", exactos)
        if serie := self.buscar_por_serie(titulo, limite=limite):
            base = self._campo(serie[0], "base_titulo", 3)
            return self._hallazgo(
                f"El título parece pertenecer a la serie '{base}', ¿te gustaría actualizar la última entrada?", serie
            )
        if similares := self.buscar_por_titulo_trigrama(titulo, threshold=0.70, limite=limite):
            return self._hallazgo("Encontramos un artículo muy similar, ¿te gustaría mejorarlo?", similares)
        return None

    def evaluar_texto(self, texto: str, headers: bool, titulo: str, limite: int = 5):
        exactos = (
            self.buscar_por_texto(texto, limite=limite)
            if headers
            else self.buscar_por_texto_sin_headers(texto, limite=limite)
        )
        if exactos := self._filtrar_divergentes(exactos, titulo, texto=texto):
            return self._hallazgo(
                "Ya existe un artículo con exactamente la misma descripción, ¿te gustaría mejorarlo?", exactos
            )
        if similares := self.buscar_en_embeddings(texto, titulo, limite=limite):
            return self._hallazgo(
                "Ya existe un artículo que explica prácticamente lo mismo, ¿te gustaría mejorarlo?", similares
            )
        return None

    def buscar_por_titulo(self, titulo: str, limite: int = 1):
        return self.buscar_exacto("titulo", titulo, limite)

    def buscar_por_texto(self, texto: str, limite: int = 1):
        return self.buscar_exacto("texto", texto, limite)

    def buscar_exacto(self, campo: str, valor: str, limite: int = 5):
        if not valor or not valor.strip():
            return []
        columna = CAMPOS_PERMITIDOS.get(campo)
        if not columna:
            raise ValueError("Campo no permitido")
        query = f"SELECT id, titulo, url FROM articulos WHERE {columna} = md5(normalizar_texto(%s)) ORDER BY id LIMIT %s"
        self.cur.execute(query, (valor, limite))
        return self.cur.fetchall()

    def obtener_articulo(self, articulo_id: int) -> dict | None:
        if not articulo_id:
            return None
        query = """
            SELECT a.id, a.titulo, a.url, a.texto, a.categoria_id,
                   COALESCE(
                       (SELECT array_agg(t.name ORDER BY t.name)
                        FROM articulo_tags at
                        JOIN tags t ON t.id = at.tag_id
                        WHERE at.articulo_id = a.id),
                       ARRAY[]::varchar[]
                   ) AS tags
            FROM articulos a
            WHERE a.id = %s
        """
        self.cur.execute(query, (articulo_id,))
        fila = self.cur.fetchone()
        if not fila:
            return None
        if isinstance(fila, dict):
            return fila
        return {
            "id": fila[0],
            "titulo": fila[1],
            "url": fila[2],
            "texto": fila[3] if len(fila) > 3 else "",
            "categoria_id": fila[4] if len(fila) > 4 else None,
            "tags": list(fila[5]) if len(fila) > 5 and fila[5] else [],
        }

    def buscar_por_serie(self, titulo: str, limite: int = 5):
        if not titulo or not titulo.strip():
            return []
        query = """
            SELECT id, titulo, url, base_titulo
            FROM articulos
            WHERE base_titulo = titulo_base(normalizar_texto(%s))
              AND base_titulo <> ''
              AND titulo_base(normalizar_texto(%s)) <> normalizar_texto(%s)
            ORDER BY id DESC
            LIMIT %s;
        """
        self.cur.execute(query, (titulo, titulo, titulo, limite))
        return self.cur.fetchall()

    def buscar_por_titulo_trigrama(self, titulo: str, threshold: float = 0.70, limite: int = 10):
        if not titulo or not titulo.strip():
            return []
        query = """
            SELECT id, titulo, url, titulo_normalizado,
                   normalizar_texto(%s) AS consulta_normalizada,
                   similarity(titulo_normalizado, normalizar_texto(%s)) AS score
            FROM articulos
            WHERE titulo_normalizado %% normalizar_texto(%s)
            ORDER BY score DESC, id
            LIMIT %s;
        """
        self.cur.execute("SELECT set_config('pg_trgm.similarity_threshold', %s, true)", (str(threshold),))
        self.cur.execute(query, (titulo, titulo, titulo, limite * 2))
        return self._filtrar_divergentes(self.cur.fetchall(), titulo, limite=limite)

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

    def buscar_en_embeddings(self, texto: str, titulo: str, umbral: float = 0.92, limite: int = 5, k_vecinos: int = 5):
        if not texto or not texto.strip():
            return []

        from baco.server.services.embeddings import embedding_texto, embedding_titulo
        self.cur.execute("SELECT limpiar_headers(%s);", (texto,))
        row = self.cur.fetchone()
        texto_sin_headers = ((list(row.values())[0] if isinstance(row, dict) else row[0]) or "") if row else ""
        if not texto_sin_headers.strip():
            return []

        vec_txt = embedding_texto(texto_sin_headers)
        if not vec_txt:
            return []
        str_vec_txt = "[" + ",".join(str(f) for f in vec_txt) + "]"

        vec_tit = embedding_titulo(titulo) if (titulo and titulo.strip()) else None
        if vec_tit:
            str_vec_tit = "[" + ",".join(str(f) for f in vec_tit) + "]"
            params = (str_vec_txt, k_vecinos, str_vec_tit, k_vecinos, titulo, str_vec_txt, str_vec_tit, umbral, limite * 3)
            self.cur.execute(SQL_EMBEDDINGS_CON_TITULO, params)
        else:
            params = (str_vec_txt, k_vecinos, titulo, str_vec_txt, umbral, limite * 3)
            self.cur.execute(SQL_EMBEDDINGS_SOLO_TEXTO, params)

        return self._filtrar_divergentes(self.cur.fetchall(), titulo, texto=texto, limite=limite)
