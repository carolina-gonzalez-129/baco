"""
Punto de entrada ÚNICO para ingestar artículos en baco_db.

Lo usan los tres caminos de ingesta para que todos se comporten igual:
  - cargar_articulos_postgres.py   (carga desde data/articulos.json)
  - migrar_y_sincronizar_todo.py   (migración maestra desde el JSON)
  - discourse/actualizar_nuevos_articulos.py (sincronización desde la API de Discourse)

Garantías:
  1. Acepta tanto el formato del JSON propio (titulo, categoria_id, texto, url, actualizado)
     como el formato crudo de Discourse (title, category_id, raw/cooked, slug, updated_at).
  2. Actualiza TODOS los campos (incluida la categoría) y solo escribe si algo cambió.
  3. Nunca pisa un artículo con datos más viejos (compara `actualizado`).
  4. Si cambia el título o el texto, pone el embedding correspondiente en NULL para que
     generar_embeddings.py lo recalcule (los hashes ya se regeneran solos por ser STORED).
  5. Sincroniza las relaciones artículo-tags (agrega las nuevas y quita las que ya no están).

No hace commit: la transacción la maneja quien llama.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def discourse_base_url() -> str:
    """URL base de Discourse tomada de DISCOURSE_URL (con o sin esquema)."""
    url = os.getenv("DISCOURSE_URL", "bc-dev.finneg.com").strip().rstrip("/")
    return url if url.startswith("http") else f"https://{url}"


def generar_slug(texto: str) -> str:
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^\w\s-]", "", t).strip().lower().replace(" ", "-")


def html_a_texto(cooked_html: str) -> str:
    """Extrae texto del HTML 'cooked' de Discourse preservando saltos de línea."""
    if not cooked_html:
        return ""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(cooked_html, "html.parser")
    lineas = [l.strip() for l in soup.get_text("\n").splitlines()]
    return "\n".join(l for l in lineas if l)


def parsear_fecha(valor: Any) -> datetime | None:
    """Convierte str ISO-8601 / datetime a datetime con zona horaria (UTC si no trae)."""
    if not valor:
        return None
    if isinstance(valor, datetime):
        dt = valor
    else:
        try:
            dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        except ValueError:
            logger.warning("Fecha inválida ignorada: %r", valor)
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def tag_id_sintetico(slug: str) -> int:
    """ID determinista (y NEGATIVO, para no chocar con los IDs reales de Discourse)
    para tags que llegan solo como string y no existen todavía en la tabla `tags`.

    A diferencia de hash(), md5 da el mismo resultado en cada ejecución.
    """
    return -int(hashlib.md5(slug.encode("utf-8")).hexdigest()[:7], 16)


def _normalizar_tags(tags_raw: Any) -> list[dict] | None:
    """Devuelve lista de {id, name, slug}. id puede ser None (tag solo-string)."""
    if tags_raw is None:
        return None
    tags: list[dict] = []
    for t in tags_raw:
        if isinstance(t, dict):
            name = (t.get("name") or "").strip()
            if not name:
                continue
            tags.append({"id": t.get("id"), "name": name, "slug": t.get("slug") or generar_slug(name)})
        elif isinstance(t, str) and t.strip():
            tags.append({"id": None, "name": t.strip(), "slug": generar_slug(t)})
    return tags


def normalizar_articulo(item: dict, base_url: str | None = None) -> dict | None:
    """Lleva un artículo (formato JSON propio o formato Discourse) al formato canónico.

    Retorna None si no tiene id. Si el item no trae la clave 'tags', `tags` queda en None
    y las relaciones existentes NO se tocan.
    """
    art_id = item.get("id")
    if not art_id:
        return None

    titulo = (item.get("titulo") or item.get("title") or "").strip() or "Sin título"
    categoria_id = item.get("categoria_id", item.get("category_id"))

    texto = item.get("texto") or item.get("raw") or html_a_texto(item.get("cooked") or "")

    url = item.get("url")
    if not url:
        base = base_url or discourse_base_url()
        slug = item.get("slug")
        url = f"{base}/t/{slug}/{art_id}" if slug else f"{base}/t/{art_id}"

    actualizado = parsear_fecha(
        item.get("actualizado") or item.get("updated_at") or item.get("bumped_at") or item.get("created_at")
    )

    tags = _normalizar_tags(item["tags"]) if "tags" in item else None

    return {
        "id": int(art_id),
        "titulo": titulo,
        "categoria_id": categoria_id,
        "url": url,
        "texto": texto or "",
        "actualizado": actualizado,
        "tags": tags,
    }


# ============================================================================
# Upsert
# ============================================================================

SQL_UPSERT_ARTICULO = """
INSERT INTO articulos (id, titulo, categoria_id, url, texto, actualizado)
VALUES (%(id)s, %(titulo)s, %(categoria_id)s, %(url)s, %(texto)s, %(actualizado)s)
ON CONFLICT (id) DO UPDATE SET
    titulo       = EXCLUDED.titulo,
    categoria_id = EXCLUDED.categoria_id,
    url          = EXCLUDED.url,
    texto        = EXCLUDED.texto,
    actualizado  = EXCLUDED.actualizado,
    -- Si cambió el contenido, se invalida el embedding para que generar_embeddings lo recalcule
    embedding_titulo = CASE WHEN articulos.titulo IS DISTINCT FROM EXCLUDED.titulo
                            THEN NULL ELSE articulos.embedding_titulo END,
    embedding_texto  = CASE WHEN articulos.texto IS DISTINCT FROM EXCLUDED.texto
                            THEN NULL ELSE articulos.embedding_texto END
WHERE
    -- Solo escribir si algo cambió (evita reescribir filas y regenerar columnas STORED)
    (articulos.titulo, articulos.categoria_id, articulos.url, articulos.texto, articulos.actualizado)
        IS DISTINCT FROM
    (EXCLUDED.titulo, EXCLUDED.categoria_id, EXCLUDED.url, EXCLUDED.texto, EXCLUDED.actualizado)
    -- Y nunca pisar con una versión más vieja
    AND (articulos.actualizado IS NULL OR EXCLUDED.actualizado >= articulos.actualizado)
RETURNING (xmax = 0) AS insertado;
"""


@dataclass
class ResumenIngesta:
    insertados: int = 0
    actualizados: int = 0
    sin_cambios: int = 0
    omitidos_por_antiguedad: int = 0
    tags_sinteticos_creados: int = 0
    ids_omitidos: list[int] = field(default_factory=list)

    def sumar(self, otro: "ResumenIngesta") -> None:
        self.insertados += otro.insertados
        self.actualizados += otro.actualizados
        self.sin_cambios += otro.sin_cambios
        self.omitidos_por_antiguedad += otro.omitidos_por_antiguedad
        self.tags_sinteticos_creados += otro.tags_sinteticos_creados
        self.ids_omitidos.extend(otro.ids_omitidos)

    def __str__(self) -> str:
        return (
            f"insertados={self.insertados}, actualizados={self.actualizados}, "
            f"sin_cambios={self.sin_cambios}, omitidos_por_antiguedad={self.omitidos_por_antiguedad}, "
            f"tags_sinteticos_creados={self.tags_sinteticos_creados}"
        )


def _resolver_tags(cur, articulos: list[dict], resumen: ResumenIngesta) -> None:
    """Inserta/actualiza tags y completa el id de los tags que llegaron solo como string."""
    con_id: dict[int, tuple[str, str]] = {}
    slugs_sin_id: set[str] = set()
    for art in articulos:
        for t in art["tags"] or []:
            if t["id"] is not None:
                con_id[t["id"]] = (t["name"], t["slug"])
            else:
                slugs_sin_id.add(t["slug"])

    if con_id:
        cur.executemany(
            """
            INSERT INTO tags (id, name, slug) VALUES (%s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, slug = EXCLUDED.slug
            WHERE (tags.name, tags.slug) IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.slug);
            """,
            [(tid, name, slug) for tid, (name, slug) in con_id.items()],
        )

    if not slugs_sin_id:
        return

    cur.execute("SELECT slug, id FROM tags WHERE slug = ANY(%s);", (list(slugs_sin_id),))
    id_por_slug: dict[str, int] = {slug: tid for slug, tid in cur.fetchall()}

    for art in articulos:
        for t in art["tags"] or []:
            if t["id"] is not None:
                continue
            if t["slug"] not in id_por_slug:
                nuevo_id = tag_id_sintetico(t["slug"])
                cur.execute(
                    "INSERT INTO tags (id, name, slug) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING;",
                    (nuevo_id, t["name"], t["slug"]),
                )
                id_por_slug[t["slug"]] = nuevo_id
                resumen.tags_sinteticos_creados += 1
                logger.warning("Tag '%s' sin ID de Discourse: creado con ID sintético %s", t["slug"], nuevo_id)
            t["id"] = id_por_slug[t["slug"]]


def _sincronizar_relaciones_tags(cur, art: dict) -> None:
    if art["tags"] is None:
        return
    tag_ids = sorted({t["id"] for t in art["tags"] if t["id"] is not None})
    cur.execute(
        "DELETE FROM articulo_tags WHERE articulo_id = %s AND NOT (tag_id = ANY(%s));",
        (art["id"], tag_ids),
    )
    if tag_ids:
        cur.executemany(
            """
            INSERT INTO articulo_tags (articulo_id, tag_id) VALUES (%s, %s)
            ON CONFLICT (articulo_id, tag_id) DO NOTHING;
            """,
            [(art["id"], tid) for tid in tag_ids],
        )


def upsert_articulos(conn, articulos: Iterable[dict]) -> ResumenIngesta:
    """Inserta/actualiza artículos YA NORMALIZADOS (ver normalizar_articulo). No hace commit."""
    articulos = [a for a in articulos if a]
    resumen = ResumenIngesta()
    if not articulos:
        return resumen

    with conn.cursor() as cur:
        # 1. Estado actual, para no pisar versiones más nuevas
        cur.execute(
            "SELECT id, actualizado FROM articulos WHERE id = ANY(%s);",
            ([a["id"] for a in articulos],),
        )
        actualizado_db: dict[int, datetime | None] = dict(cur.fetchall())

        vigentes = []
        for art in articulos:
            previo = actualizado_db.get(art["id"])
            if art["id"] in actualizado_db and previo is not None and (
                art["actualizado"] is None or art["actualizado"] < previo
            ):
                resumen.omitidos_por_antiguedad += 1
                resumen.ids_omitidos.append(art["id"])
                continue
            vigentes.append(art)

        # 2. Categorías (FK) y tags
        categorias = {a["categoria_id"] for a in vigentes if a["categoria_id"]}
        if categorias:
            cur.executemany(
                "INSERT INTO categorias (id, nombre) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;",
                [(cid, f"Categoría {cid}") for cid in sorted(categorias)],
            )
        _resolver_tags(cur, vigentes, resumen)

        # 3. Artículos + relaciones con tags
        for art in vigentes:
            cur.execute(SQL_UPSERT_ARTICULO, {k: art[k] for k in
                                              ("id", "titulo", "categoria_id", "url", "texto", "actualizado")})
            fila = cur.fetchone()
            if fila is None:
                resumen.sin_cambios += 1
            elif fila[0]:
                resumen.insertados += 1
            else:
                resumen.actualizados += 1
            _sincronizar_relaciones_tags(cur, art)

    return resumen
