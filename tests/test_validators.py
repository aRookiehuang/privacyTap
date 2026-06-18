from tokentap.privacy.validators import is_valid_cn_id, is_valid_luhn


def test_valid_cn_id_checksum():
    assert is_valid_cn_id("11010519491231002X")


def test_invalid_cn_id_checksum():
    assert not is_valid_cn_id("110105194912310021")


def test_cn_id_rejects_bad_length():
    assert not is_valid_cn_id("11010519491231002")


def test_valid_luhn_card():
    assert is_valid_luhn("4532015112830366")


def test_luhn_accepts_spaces_and_hyphens():
    assert is_valid_luhn("4532-0151 1283-0366")


def test_invalid_luhn_card():
    assert not is_valid_luhn("4532015112830367")


def test_luhn_rejects_non_card_length():
    assert not is_valid_luhn("123456")
