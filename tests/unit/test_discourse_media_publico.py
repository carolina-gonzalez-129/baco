import pytest
from unittest.mock import MagicMock, patch
import httpx
from baco.server.services.discourse_media import (
    consultar_articulo_bc_publico,
    cooked_a_markdown_con_medios,
)
from baco.server.services.orquestador.validaciones import cargar_datos_articulo


def test_cooked_a_markdown_con_medios_conserva_imagenes_y_adjuntos():
    cooked = """
    <p>Paso 1: Abrir ventas.</p>
    <div class="lightbox-wrapper">
      <a class="lightbox" href="/uploads/default/original/2X/a/abc.png">
        <img src="/uploads/optimized/abc.png" alt="Pantalla de Ventas" />
      </a>
    </div>
    <p>Descargar plantilla:</p>
    <p><a class="attachment" href="/uploads/default/original/2X/b/guia.pdf">Guia_Ventas.pdf</a></p>
    <iframe src="https://www.youtube.com/embed/xyz123"></iframe>
    """
    md = cooked_a_markdown_con_medios(cooked, base_url="https://bc.finneg.com")
    assert "![Pantalla de Ventas](https://bc.finneg.com/uploads/default/original/2X/a/abc.png)" in md
    assert "[Guia_Ventas.pdf|attachment](https://bc.finneg.com/uploads/default/original/2X/b/guia.pdf)" in md
    assert "https://www.youtube.com/embed/xyz123" in md
    assert "Paso 1: Abrir ventas." in md


def test_consultar_articulo_bc_publico_ok():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "id": 2414,
        "category_id": 21,
        "tags": [{"name": "soluciones", "slug": "soluciones"}, "facturacion"],
        "post_stream": {
            "posts": [
                {
                    "cooked": "<p>Consulta de facturación</p><a class='lightbox' href='/img.png'><img alt='captura'/></a>"
                }
            ]
        },
    }
    client = MagicMock(spec=httpx.Client)
    client.get.return_value = mock_resp

    texto, cat, tags = consultar_articulo_bc_publico(2414, client=client)
    assert cat == 21
    assert "soluciones" in tags
    assert "facturacion" in tags
    assert "![captura](https://bc.finneg.com/img.png)" in texto


def test_consultar_articulo_bc_publico_404_no_explota_y_retorna_nulos():
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    client = MagicMock(spec=httpx.Client)
    client.get.return_value = mock_resp

    texto, cat, tags = consultar_articulo_bc_publico(99999, client=client)
    assert texto is None
    assert cat is None
    assert tags == []


def test_consultar_articulo_bc_publico_error_red_captura_excepcion():
    client = MagicMock(spec=httpx.Client)
    client.get.side_effect = httpx.ConnectError("Timeout de conexión")

    texto, cat, tags = consultar_articulo_bc_publico(123, client=client)
    assert texto is None
    assert cat is None
    assert tags == []


@pytest.mark.anyio
async def test_cargar_datos_articulo_prioriza_db_y_usa_fallback_bc():
    buscador = MagicMock()
    # Caso 1: En DB local no está el texto (vacío)
    buscador.obtener_articulo.return_value = {"id": 2414, "texto": "", "categoria_id": None, "tags": []}

    with patch("baco.server.services.discourse_media.consultar_articulo_bc_publico") as mock_bc:
        mock_bc.return_value = ("Contenido con ![img](url)", 15, ["instructivo", "ventas"])
        txt, cat, tags = await cargar_datos_articulo(buscador, 2414)
        assert txt == "Contenido con ![img](url)"
        assert cat == 15
        assert tags == ["instructivo", "ventas"]


def test_cooked_a_markdown_con_medios_conserva_docs_diapositivas_y_videos():
    cooked = """
    <p>Para ver el procedimiento general, consultar el <a href="https://docs.google.com/document/d/1X2Y3Z/edit">Documento de Procedimiento</a>.</p>
    <p>También están disponibles las diapositivas de capacitación:</p>
    <p><a href="https://docs.google.com/presentation/d/4A5B6C/edit">Presentación Ventas 2026</a></p>
    <aside class="onebox allowlistedgeneric" data-onebox-src="https://docs.google.com/document/d/789">
      <article class="onebox-body">
        <h3><a href="https://docs.google.com/document/d/789">Instructivo Facturación</a></h3>
      </article>
    </aside>
    <div class="lazyYT" data-youtube-id="xyz987" data-youtube-title="Tutorial Facturación"></div>
    <video controls><source src="/uploads/default/original/demo.mp4" type="video/mp4"></video>
    <iframe src="https://docs.google.com/presentation/d/embed_pres/embed"></iframe>
    <iframe src="https://www.youtube.com/embed/embed_yt"></iframe>
    """
    md = cooked_a_markdown_con_medios(cooked, base_url="https://bc.finneg.com")
    assert "[Documento de Procedimiento](https://docs.google.com/document/d/1X2Y3Z/edit)" in md
    assert "[Presentación Ventas 2026](https://docs.google.com/presentation/d/4A5B6C/edit)" in md
    assert "[Instructivo Facturación](https://docs.google.com/document/d/789)" in md
    assert "https://www.youtube.com/watch?v=xyz987" in md
    assert "https://bc.finneg.com/uploads/default/original/demo.mp4" in md
    assert "https://docs.google.com/presentation/d/embed_pres/embed" in md
    assert "https://www.youtube.com/embed/embed_yt" in md
