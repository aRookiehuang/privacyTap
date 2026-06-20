from examples.demo_client import get_proxy_url


def test_demo_client_uses_configurable_proxy_url(monkeypatch):
    monkeypatch.setenv(
        "PRIVACYTAP_PROXY_URL",
        "http://127.0.0.1:18081/v1/chat/completions",
    )
    assert (
        get_proxy_url()
        == "http://127.0.0.1:18081/v1/chat/completions"
    )


def test_demo_client_has_local_default(monkeypatch):
    monkeypatch.delenv("PRIVACYTAP_PROXY_URL", raising=False)
    assert (
        get_proxy_url()
        == "http://127.0.0.1:8080/v1/chat/completions"
    )


def test_mock_responses_upstream_exposes_responses_route():
    from examples.mock_responses_upstream import app

    routes = {
        route.resource.canonical
        for route in app.router.routes()
    }
    assert "/v1/responses" in routes
