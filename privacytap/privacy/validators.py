import re


CN_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
CN_ID_CHECK_CODES = "10X98765432"


def digits_only(value: str) -> str:
    return re.sub(r"[\s-]", "", value)


def is_valid_cn_id(value: str) -> bool:
    normalized = value.strip().upper()
    if not re.fullmatch(r"\d{17}[\dX]", normalized):
        return False
    total = sum(
        int(char) * weight
        for char, weight in zip(normalized[:17], CN_ID_WEIGHTS)
    )
    return CN_ID_CHECK_CODES[total % 11] == normalized[-1]


def is_valid_luhn(value: str) -> bool:
    normalized = digits_only(value)
    if not normalized.isdigit() or not 16 <= len(normalized) <= 19:
        return False
    total = 0
    parity = len(normalized) % 2
    for index, char in enumerate(normalized):
        digit = int(char)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0
