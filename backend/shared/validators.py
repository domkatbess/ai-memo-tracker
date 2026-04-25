"""Common validation functions for request data."""

import re

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def check_required_fields(data: dict, required: list[str]) -> list[str]:
    """Check that all required fields are present and non-empty.

    Args:
        data: Dictionary of field values.
        required: List of required field names.

    Returns:
        List of missing field names.
    """
    missing = []
    for field in required:
        value = data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def validate_email(email: str) -> bool:
    """Validate email format.

    Returns:
        True if the email matches a valid format, False otherwise.
    """
    if not email or not isinstance(email, str):
        return False
    return bool(EMAIL_REGEX.match(email))
