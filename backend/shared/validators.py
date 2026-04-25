"""Common validation functions for request data."""

import re


def check_required_fields(data: dict, fields: list) -> list:
    """Return a list of field names that are missing or empty in data."""
    missing = []
    for field in fields:
        value = data.get(field)
        if not value or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def is_valid_email(email: str) -> bool:
    """Return True if email matches a basic email format."""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def is_valid_iso_date(date_str: str) -> bool:
    """Return True if date_str is a valid ISO 8601 date (YYYY-MM-DD)."""
    pattern = r"^\d{4}-\d{2}-\d{2}$"
    return bool(re.match(pattern, date_str))
