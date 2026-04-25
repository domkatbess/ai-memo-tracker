"""
Common validation helpers used across Lambda handlers.
"""

import re
from datetime import datetime


def validate_required_fields(data: dict, required_fields: list[str]) -> list[str]:
    """Return a list of field names that are missing or empty in *data*."""
    missing = []
    for field in required_fields:
        value = data.get(field)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            missing.append(field)
    return missing


def validate_email(email: str) -> bool:
    """Return True if *email* looks like a valid email address."""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def validate_iso_date(date_str: str) -> bool:
    """Return True if *date_str* is a valid ISO 8601 date (YYYY-MM-DD)."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False
