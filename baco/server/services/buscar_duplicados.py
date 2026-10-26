from baco.server.services.reglas_semanticas import son_semanticas_divergentes

MIN_CARACTERES_EMBEDDINGS = 400


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

    def filtrar_articulos_series(self, filas: list) -> list:
        if not filas:
            return []
        ids = [self._campo(f, "id", 0) for f in filas if self._campo(f, "id", 0) is not None]
        if not ids:
            return filas
        try:
            query = """
                SELECT id FROM public.articulos
                WHERE id = ANY(%s)
                  AND base_titulo IS NOT NULL
                  AND base_titulo <> ''
                  AND base_titulo <> public.normalizar_texto(titulo);
            """
            self.cur.execute(query, (ids,))
            res = self.cur.fetchall()
            series_ids = {self._campo(r, "id", 0) for r in res}
            return [f for f in filas if self._campo(f, "id", 0) not in series_ids]
        except Exception:
            return filas

    def evaluar_texto(
        self,
        texto: str,
        headers: bool,
        titulo: str,
        limite: int = 5,
        excluir_series: bool = False,
        min_longitud_embeddings: int = MIN_CARACTERES_EMBEDDINGS,
    ):
        exactos = self.buscar_por_texto(texto, limite=limite)
        if excluir_series and exactos:
            exactos = self.filtrar_articulos_series(exactos)
        if exactos := self._filtrar_divergentes(exactos, titulo, texto=texto):
            return self._hallazgo(
                "Ya existe un artículo con exactamente la misma descripción, ¿te gustaría mejorarlo?", exactos
            )

        texto_limpio = (texto or "").strip()
        if len(texto_limpio) >= min_longitud_embeddings:
            if similares := self.buscar_en_embeddings(texto, titulo, umbral=0.85, limite=limite):
                if excluir_series and similares:
                    similares = self.filtrar_articulos_series(similares)
                if similares:
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
        if campo not in {"titulo", "texto"}:
            return []
        query = "SELECT id_articulo AS id, titulo_articulo AS titulo, url_articulo AS url FROM duplicados.buscar_exacto(%s, %s, %s);"
        self.cur.execute(query, (valor, campo, limite))
        return self.cur.fetchall()

    def obtener_articulo(self, articulo_id: int) -> dict | None:
        if not articulo_id:
            return None
        query = """
            SELECT id_articulo AS id, titulo_articulo AS titulo, url_articulo AS url, 
                   texto_articulo AS texto, categoria_id, tags 
            FROM duplicados.obtener_articulo(%s);
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
            SELECT id_articulo AS id, titulo_articulo AS titulo, url_articulo AS url, base_titulo 
            FROM duplicados.similares_series(%s, %s);
        """
        self.cur.execute(query, (titulo, limite))
        return self.cur.fetchall()

    def buscar_por_titulo_trigrama(self, titulo: str, threshold: float = 0.70, limite: int = 10):
        if not titulo or not titulo.strip():
            return []
        query = """
            SELECT id_articulo AS id, titulo_articulo AS titulo, url_articulo AS url, score 
            FROM duplicados.similares_trigramas(%s, %s::numeric, %s);
        """
        self.cur.execute(query, (titulo, threshold, limite * 2))
        return self._filtrar_divergentes(self.cur.fetchall(), titulo, limite=limite)


    def buscar_en_embeddings(self, texto: str, titulo: str, umbral: float = 0.85, limite: int = 5, k_vecinos: int = 5):
        if not texto or not texto.strip():
            return []

        from baco.server.services.embeddings import embedding_texto, embedding_titulo
        self.cur.execute("SELECT public.limpiar_headers(%s);", (texto,))
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
            query = """
                SELECT id_articulo AS id, titulo_articulo AS titulo, url_articulo AS url,
                       titulo_normalizado, consulta_normalizada, texto_norm_1000,
                       sim_texto, sim_titulo, score_total
                FROM duplicados.similares_embeddings_con_titulo(%s::public.vector, %s::public.vector, %s, %s::numeric, %s);
            """
            self.cur.execute(query, (str_vec_txt, str_vec_tit, titulo, umbral, limite * 3))
        else:
            query = """
                SELECT id_articulo AS id, titulo_articulo AS titulo, url_articulo AS url,
                       titulo_normalizado, consulta_normalizada, texto_norm_1000,
                       sim_texto, sim_titulo, score_total
                FROM duplicados.similares_embeddings_solo_texto(%s::public.vector, %s, %s::numeric, %s);
            """
            self.cur.execute(query, (str_vec_txt, titulo, umbral, limite * 3))

        return self._filtrar_divergentes(self.cur.fetchall(), titulo, texto=texto, limite=limite)
