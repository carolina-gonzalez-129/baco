from unittest.mock import MagicMock, patch

from baco.agent import SYSTEM_PROMPT, create_agent
from baco.server.db import config
from baco.server.discourse import client
from baco.server.schemas.articulo import ArticuloSchema, Tag


def test_create_agent_configura_modelo_prompt_tools_y_plugins():
    agente = MagicMock()

    with patch("baco.agent.Agent", return_value=agente) as agent_cls:
        resultado = create_agent(tools=["tool"])

    assert resultado is agente
    kwargs = agent_cls.call_args.kwargs
    assert kwargs["model"] is not None
    assert kwargs["system_prompt"] == SYSTEM_PROMPT
    assert kwargs["tools"] == ["tool"]
    assert kwargs["plugins"]


def test_create_agent_usa_lista_vacia_si_tools_es_none():
    with patch("baco.agent.Agent") as agent_cls:
        create_agent()

    assert agent_cls.call_args.kwargs["tools"] == []


def test_get_conn_usa_psycopg_para_otra_base():
    conexion = MagicMock()
    with patch.object(config, "db_pool", None), \
         patch.object(config.psycopg, "connect", return_value=conexion) as connect:
        resultado = config.get_conn(dbname="postgres", autocommit=True)

    assert resultado is conexion
    connect.assert_called_once()
    assert connect.call_args.kwargs["dbname"] == "postgres"
    assert connect.call_args.kwargs["autocommit"] is True


def test_client_expone_credenciales_y_headers_basicos():
    assert client.BASE.startswith("https://")
    assert client.headers["Content-Type"] == "application/json"
    assert "Api-Key" in client.headers
    assert client.headers["Api-Username"]


def test_discourse_base_url_lanza_error_si_no_esta_definida(monkeypatch):
    from baco.server.db.ingesta import discourse_base_url
    import pytest

    monkeypatch.delenv("DISCOURSE_URL", raising=False)
    with pytest.raises(ValueError, match="DISCOURSE_URL no está configurada"):
        discourse_base_url()


def test_httpx_client_con_discourse_base_url_contiene_host():
    import httpx
    from baco.server.db.ingesta import discourse_base_url
    from baco.server.discourse.client import base_url

    url_base = discourse_base_url()
    assert url_base == base_url()

    with httpx.Client(base_url=url_base) as http_client:
        req = http_client.build_request("GET", "/latest.json")
        assert str(req.url).startswith(url_base)
        assert req.url.host == "bc-dev.finneg.com"


def test_schemas_articulo_y_tag_aplican_defaults():
    tag = Tag(name="ventas")
    articulo = ArticuloSchema(id=1)

    assert tag.id is None
    assert articulo.titulo == "Sin título"
    assert articulo.tags == []
    assert articulo.texto == ""
    assert articulo.raw_extra == {}
