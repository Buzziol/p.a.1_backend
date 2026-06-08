import re
from datetime import datetime


DATE_YEAR_ERROR = "Informe uma data valida com ano de 4 digitos."
DATETIME_YEAR_ERROR = "Data/hora invalida. Use um ano com 4 digitos."

_LONG_YEAR_RE = re.compile(r"\d{5,}")
_ISO_YEAR_PREFIX_RE = re.compile(r"^\s*\d{4}(?!\d)")


def _has_four_digit_iso_year(value):
    text = str(value).strip()
    return bool(_ISO_YEAR_PREFIX_RE.match(text)) and not _LONG_YEAR_RE.search(text)


def parse_iso_date(value, field_name):
    if value in (None, ""):
        return None, None
    if not _has_four_digit_iso_year(value):
        return None, f"{field_name}: {DATE_YEAR_ERROR}"
    try:
        return datetime.fromisoformat(str(value)).date(), None
    except (TypeError, ValueError):
        return None, f"{field_name} deve estar no formato ISO YYYY-MM-DD"


def parse_iso_datetime(value, field_name):
    if value in (None, ""):
        return None, None
    if not _has_four_digit_iso_year(value):
        return None, f"{field_name}: {DATETIME_YEAR_ERROR}"
    try:
        return datetime.fromisoformat(str(value)), None
    except (TypeError, ValueError):
        return None, f"{field_name} deve estar no formato ISO YYYY-MM-DD ou YYYY-MM-DDTHH:MM"
