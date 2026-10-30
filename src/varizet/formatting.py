"""Display helpers. Money stays ``int`` rial in code; these only format it for people."""

from __future__ import annotations

_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
#: U+066C ARABIC THOUSANDS SEPARATOR, the Persian grouping mark.
PERSIAN_GROUP_SEPARATOR = "٬"


def to_persian_digits(text: str) -> str:
    return text.translate(_PERSIAN_DIGITS)


def format_rial(amount: int, *, persian_digits: bool = True, unit: bool = False) -> str:
    """``8500430`` → ``'۸٬۵۰۰٬۴۳۰'`` (or ``'8,500,430'`` with ``persian_digits=False``).
    ``unit=True`` appends ``ریال`` / ``IRR``."""
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise TypeError("amount must be an int number of rial")
    grouped = f"{amount:,}"
    if persian_digits:
        grouped = to_persian_digits(grouped.replace(",", PERSIAN_GROUP_SEPARATOR))
    if unit:
        grouped += " ریال" if persian_digits else " IRR"
    return grouped
