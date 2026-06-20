import pytest

from privacytap.privacy.models import EntityType
from privacytap.privacy.streaming import StreamingRestorer
from privacytap.privacy.vault import RequestVault


@pytest.mark.parametrize("split_at", range(1, len("[EMAIL_1]")))
def test_placeholder_restores_across_every_split(split_at):
    vault = RequestVault()
    placeholder = vault.get_or_create(
        EntityType.EMAIL, "alice@example.com"
    )
    restorer = StreamingRestorer(vault)
    output = (
        restorer.feed("text:0", placeholder[:split_at])
        + restorer.feed("text:0", placeholder[split_at:])
        + restorer.finish("text:0")
    )
    assert output == "alice@example.com"


def test_parallel_tool_calls_keep_independent_buffers():
    vault = RequestVault()
    placeholder = vault.get_or_create(
        EntityType.STUDENT_ID, "2023123456"
    )
    restorer = StreamingRestorer(vault)
    left = restorer.feed("call:a", placeholder[:5])
    right = restorer.feed("call:b", "safe")
    left += restorer.feed("call:a", placeholder[5:])
    left += restorer.finish("call:a")
    right += restorer.finish("call:b")
    assert left == "2023123456"
    assert right == "safe"


def test_finish_releases_non_placeholder_tail():
    vault = RequestVault()
    vault.get_or_create(EntityType.PHONE, "13800138000")
    restorer = StreamingRestorer(vault)
    assert restorer.feed("text:0", "hello [PH") == "hello "
    assert restorer.finish("text:0") == "[PH"


def test_no_placeholders_passes_text_immediately():
    restorer = StreamingRestorer(RequestVault())
    assert restorer.feed("text:0", "hello") == "hello"
    assert restorer.finish("text:0") == ""
