"""Unit tests for tokentap config."""

from tokentap.config import PROVIDERS


class TestProvidersConfig:
    """Tests for the PROVIDERS configuration dict."""

    def test_minimax_provider_exists(self):
        assert "minimax" in PROVIDERS

    def test_minimax_host(self):
        assert PROVIDERS["minimax"]["host"] == "api.minimax.io"

    def test_minimax_base_url(self):
        assert PROVIDERS["minimax"]["base_url"] == "https://api.minimax.io"

    def test_minimax_env_vars(self):
        assert "OPENAI_BASE_URL" in PROVIDERS["minimax"]["env_vars"]

    def test_minimax_path_prefix(self):
        assert PROVIDERS["minimax"]["path_prefix"] == "minimax"

    def test_minimax_proxy_path(self):
        assert PROVIDERS["minimax"]["proxy_path"] == "/minimax/v1"

    def test_all_providers_have_host(self):
        for name, config in PROVIDERS.items():
            assert "host" in config, f"Provider {name} missing 'host'"

    def test_all_providers_have_base_url(self):
        for name, config in PROVIDERS.items():
            assert "base_url" in config, f"Provider {name} missing 'base_url'"

    def test_all_providers_have_env_vars(self):
        for name, config in PROVIDERS.items():
            assert "env_vars" in config, f"Provider {name} missing 'env_vars'"
            assert len(config["env_vars"]) > 0

    def test_intercepted_hosts_includes_minimax(self):
        from tokentap.config import INTERCEPTED_HOSTS

        assert "api.minimax.io" in INTERCEPTED_HOSTS

    def test_provider_count(self):
        assert len(PROVIDERS) == 4  # anthropic, openai, gemini, minimax
