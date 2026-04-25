"""
Lambda handler for adding a note to an existing memo.

POST /memos/{id}/notes
"""

import json
from datetime import datetime, timezone

from backend.shared.dynamodb import get_table, memo_pk, memo_sk, note_sk
from backend.shared.response import (
    error_response,
    success_response,
    NOT_FOUND,
    VALIDATION_ERROR,
)
from backend.shared.validators import validate_required_fields


VALID_SOURCES = ("voice", "text")


def handler(event, context):
    """Add a note to an existing memo record."""
    memo_id = event["pathParameters"]["id"]

    # --- Parse request body ---
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return error_response(
            "Invalid JSON in request body",
            VALIDATION_ERROR,
            status_code=400,
        )

    # --- Validate required fields ---
    required_fields = ["note_text", "created_by", "source"]
    missing = validate_required_fields(body, required_fields)

    if missing:
        return error_response(
            "Missing required fields",
            VALIDATION_ERROR,
            status_code=400,
            details={"missing_fields": missing},
        )

    source = body["source"]

    # --- Validate source value ---
    if source not in VALID_SOURCES:
        return error_response(
            f"Invalid source. Must be one of: {', '.join(VALID_SOURCES)}",
            VALIDATION_ERROR,
            status_code=400,
            details={"invalid_fields": ["source"]},
        )

    table = get_table()

    # --- Check that the memo exists ---
    result = table.get_item(
        Key={"PK": memo_pk(memo_id), "SK": memo_sk()}
    )

    if not result.get("Item"):
        return error_response("Memo not found", NOT_FOUND, status_code=404)

    # --- Build note item ---
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    note_item = {
        "PK": memo_pk(memo_id),
        "SK": note_sk(created_at),
        "memo_id": memo_id,
        "note_text": body["note_text"],
        "created_by": body["created_by"],
        "created_at": created_at,
        "source": source,
        "entity_type": "MEMO_NOTE",
    }

    table.put_item(Item=note_item)

    # --- Build response (exclude DynamoDB key attributes) ---
    response_body = {
        "memo_id": memo_id,
        "note_text": body["note_text"],
        "created_by": body["created_by"],
        "created_at": created_at,
        "source": source,
        "entity_type": "MEMO_NOTE",
    }

    return success_response(response_body, status_code=201)
