import httpx
import pytest
import respx

from baco.server.discourse.common import (
    ErrorAPIDiscourse,
    RecursoNoDisponible,
    descargar_articulo,
    pedir,
)

BASE = "https://discourse.test"


@pytest.fixture(autouse=True)
def sin_sleep(monkeypatch):
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)


@respx.mock
@pytest.mark.parametrize("status", [404, 410])
def test_pedir_404_410_no_reintenta_y_lanza_recurso_no_disponible(status):
    route = respx.get(f"{BASE}/t/1.json").respond(status)
    with httpx.Client(base_url=BASE) as client:
        with pytest.raises(RecursoNoDisponible) as exc:
            pedir(client, "/t/1.json")
    assert str(status) in str(exc.value)
    assert route.call_count == 1


@respx.mock
@pytest.mark.parametrize("status", [400, 401, 403, 422])
def test_pedir_otros_4xx_no_reintentan_y_no_son_recurso_no_disponible(status):
    route = respx.get(f"{BASE}/x").respond(status)
    with httpx.Client(base_url=BASE) as client:
        with pytest.raises(ErrorAPIDiscourse) as exc:
            pedir(client, "/x")
    assert not isinstance(exc.value, RecursoNoDisponible)
    assert route.call_count == 1


@respx.mock
def test_pedir_5xx_sigue_reintentando():
    route = respx.get(f"{BASE}/y").respond(500)
    with httpx.Client(base_url=BASE) as client:
        with pytest.raises(ErrorAPIDiscourse):
            pedir(client, "/y")
    assert route.call_count == 5


@respx.mock
def test_descargar_articulo_de_tema_borrado_devuelve_none_en_vez_de_abortar(monkeypatch):
    monkeypatch.setenv("DISCOURSE_URL", BASE)
    respx.get(f"{BASE}/t/555.json").respond(404)
    with httpx.Client(base_url=BASE) as client:
        assert descargar_articulo(client, 555) is None


def test_validar_credenciales_discourse_falla_si_key_vacia(monkeypatch):
    from baco.server.discourse.common import validar_credenciales_discourse
    monkeypatch.setenv("DISCOURSE_API_KEY", "")
    monkeypatch.setenv("DISCOURSE_API_USERNAME", "admin")
    with pytest.raises(ErrorAPIDiscourse, match="DISCOURSE_API_KEY no está configurada"):
        validar_credenciales_discourse()


def test_validar_credenciales_discourse_falla_si_username_vacio(monkeypatch):
    from baco.server.discourse.common import validar_credenciales_discourse
    monkeypatch.setenv("DISCOURSE_API_KEY", "algun_token")
    monkeypatch.setenv("DISCOURSE_API_USERNAME", "")
    with pytest.raises(ErrorAPIDiscourse, match="DISCOURSE_API_USERNAME no está configurada"):
        validar_credenciales_discourse()


def test_validar_credenciales_discourse_valido(monkeypatch):
    from baco.server.discourse.common import validar_credenciales_discourse
    monkeypatch.setenv("DISCOURSE_API_KEY", "token_valido")
    monkeypatch.setenv("DISCOURSE_API_USERNAME", "system")
    # No debe levantar excepción
    validar_credenciales_discourse()

