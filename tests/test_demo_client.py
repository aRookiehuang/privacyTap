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


def test_mock_anthropic_exposes_gateway_routes():
    from examples.mock_anthropic_upstream import app

    routes = {
        route.resource.canonical
        for route in app.router.routes()
    }
    assert "/v1/messages" in routes
    assert "/v1/messages/count_tokens" in routes


def test_mock_anthropic_returns_exact_ok_for_protocol_smoke():
    from examples.mock_anthropic_upstream import mock_reply_text

    assert mock_reply_text("Reply with exactly OK") == "OK"
    assert mock_reply_text("hello") == "上游实际收到：hello"
