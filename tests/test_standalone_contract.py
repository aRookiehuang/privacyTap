import importlib.util
from pathlib import Path


def test_privacytap_package_exists_and_tokentap_package_is_removed():
    assert importlib.util.find_spec("privacytap") is not None
    assert importlib.util.find_spec("tokentap") is None


def test_repository_has_no_tokentap_source_tree():
    assert not Path("tokentap").exists()


def test_project_metadata_is_standalone():
    metadata = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "privacytap"' in metadata
    assert 'privacytap = "privacytap.cli:main"' in metadata
    assert 'tokentap = ' not in metadata


def test_readme_documents_real_codex_responses_setup():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert 'wire_api = "responses"' in readme
    assert "codex --profile privacytap" in readme
    assert "OPENAI_API_KEY" in readme
    assert "/v1/responses" in readme
