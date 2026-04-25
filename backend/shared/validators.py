"""Common validation functions for request data."""

import re

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def check_required_fields(data: dict, required: list[str]) -> list[str]:
    """Return a list of field names that are missing or empty in *data*.

    Args:
        data: The dict to validate.
        required: Field names that must be present and non-empty.

    Returns:
        List of missing/empty field names (empty list means all present).
    """
    missing = []
    for field in required:
        value = data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def validate_email(email: str) -> bool:
    """Return True if *email* matches a basic email format."""
    if not email or not isinstance(email, str):
        return False
    return bool(EMAIL_REGEX.match(email))
