"""Standardized API response helpers for Lambda handlers."""

import json


def success_response(data, status_code=200):
    """Return a successful API Gateway response.

    Args:
        data: Response body data (dict or list).
        status_code: HTTP status code (default 200).

    Returns:
        dict: API Gateway proxy response.
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
        error_code: Machine-readable error code (e.g. FORBIDDEN, VALIDATION_ERROR).
        status_code: HTTP status code.
        details: Optional dict with additional error context.

    Returns:
        dict: API Gateway proxy response with error body.
    """
    body = {
        "error": message,
        "error_code": error_code,
        "details": details or {},
    }
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
