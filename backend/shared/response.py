"""
Standardized API response helpers for Lambda handlers behind API Gateway.
"""

import json

# ---------------------------------------------------------------------------
# Error codes (from design document)
# ---------------------------------------------------------------------------

VALIDATION_ERROR = "VALIDATION_ERROR"
AUTH_FAILED = "AUTH_FAILED"
TOKEN_EXPIRED = "TOKEN_EXPIRED"
FORBIDDEN = "FORBIDDEN"
NOT_FOUND = "NOT_FOUND"
DUPLICATE_EMAIL = "DUPLICATE_EMAIL"
ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
TRANSCRIPTION_FAILED = "TRANSCRIPTION_FAILED"
QUERY_PARSE_FAILED = "QUERY_PARSE_FAILED"
SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
SESSION_INCOMPLETE = "SESSION_INCOMPLETE"
CONFIRMATION_UNCLEAR = "CONFIRMATION_UNCLEAR"
FIELD_RETRY_EXCEEDED = "FIELD_RETRY_EXCEEDED"
SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"

# ---------------------------------------------------------------------------
# CORS headers included in every response
# ---------------------------------------------------------------------------

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
}


def success_response(body: dict, status_code: int = 200) -> dict:
    """Return a well-formed API Gateway proxy response for success cases."""
    return {
        "statusCode": status_code,
        "headers": {**_CORS_HEADERS},
        "body": json.dumps(body),
    }


def error_response(
    message: str,
    error_code: str,
    status_code: int = 400,
    details: dict | None = None,
) -> dict:
    """Return a well-formed API Gateway proxy response for error cases."""
    body: dict = {
        "error": message,
        "error_code": error_code,
    }
    if details is not None:
        body["details"] = details
    return {
        "statusCode": status_code,
        "headers": {**_CORS_HEADERS},
        "body": json.dumps(body),
    }
