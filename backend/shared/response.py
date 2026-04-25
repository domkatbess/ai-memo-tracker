"""Standardized API response helpers for Lambda handlers."""

import json


def success_response(data, status_code=200):
    """Return a successful API Gateway response.

    Args:
        data: Dictionary to serialize as the response body.
        status_code: HTTP status code (default 200).

    Returns:
        API Gateway-compatible response dict.
    """
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(data),
    }


def error_response(message, error_code, status_code, details=None):
    """Return an error API Gateway response.

    Args:
        message: Human-readable error message.
        error_code: Machine-readable error code string.
        status_code: HTTP status code.
        details: Optional dict with additional error details.

    Returns:
        API Gateway-compatible error response dict.
    """
    body = {
        "error": message,
        "error_code": error_code,
        "details": details if details else {},
    }
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
