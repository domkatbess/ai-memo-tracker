"""
Lambda handler for creating a new memo record.

POST /memos
"""

import json
import uuid
from datetime import datetime, timezone

from backend.shared.dynamodb import (
    get_table,
    memo_pk,
    memo_sk,
    gsi1_type_pk,
    gsi1_date_sk,
    gsi2_person_pk,
)
from backend.shared.response import error_response, success_response, VALIDATION_ERROR
from backend.shared.validators import validate_required_fields, validate_iso_date


VALID_MEMO_TYPES = ("incoming", "outgoing")


def handler(event, context):
    """Create a new memo record in DynamoDB."""
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return error_response(
            "Invalid JSON in request body",
            VALIDATION_ERROR,
            status_code=400,
        )

    # --- Validate universally required fields ---
    required_fields = ["title", "memo_type", "memo_date"]
    missing = validate_required_fields(body, required_fields)

    if missing:
        return error_response(
            "Missing required fields",
            VALIDATION_ERROR,
            status_code=400,
            details={"missing_fields": missing},
        )

    memo_type = body["memo_type"]
    memo_date = body["memo_date"]

    # --- Validate memo_type ---
    if memo_type not in VALID_MEMO_TYPES:
        return error_response(
            f"Invalid memo_type. Must be one of: {', '.join(VALID_MEMO_TYPES)}",
            VALIDATION_ERROR,
            status_code=400,
            details={"invalid_fields": ["memo_type"]},
        )

    # --- Validate memo_date format ---
    if not validate_iso_date(memo_date):
        return error_response(
            "Invalid memo_date format. Expected ISO 8601 date (YYYY-MM-DD)",
            VALIDATION_ERROR,
            status_code=400,
            details={"invalid_fields": ["memo_date"]},
        )

    # --- Validate conditional person fields ---
    conditional_missing = []
    if memo_type == "incoming":
        if not body.get("person_brought_in") or (
            isinstance(body.get("person_brought_in"), str)
            and body["person_brought_in"].strip() == ""
        ):
            conditional_missing.append("person_brought_in")
    elif memo_type == "outgoing":
        if not body.get("person_took_out") or (
            isinstance(body.get("person_took_out"), str)
            and body["person_took_out"].strip() == ""
        ):
            conditional_missing.append("person_took_out")

    if conditional_missing:
        return error_response(
            "Missing required fields",
            VALIDATION_ERROR,
            status_code=400,
            details={"missing_fields": conditional_missing},
        )

    # --- Build memo item ---
    memo_id = str(uuid.uuid4())
    recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Determine the person name for GSI2
    person_name = (
        body.get("person_brought_in")
        if memo_type == "incoming"
        else body.get("person_took_out")
    )

    item = {
        "PK": memo_pk(memo_id),
        "SK": memo_sk(),
        "memo_id": memo_id,
        "title": body["title"],
        "memo_type": memo_type,
        "memo_date": memo_date,
        "recorded_at": recorded_at,
        "person_brought_in": body.get("person_brought_in"),
        "person_took_out": body.get("person_took_out"),
        "created_by": body.get("created_by"),
        "entity_type": "MEMO",
        "GSI1PK": gsi1_type_pk(memo_type),
        "GSI1SK": gsi1_date_sk(memo_date),
        "GSI2PK": gsi2_person_pk(person_name),
        "GSI2SK": gsi1_date_sk(memo_date),
    }

    # Remove None values to keep DynamoDB item clean
    item = {k: v for k, v in item.items() if v is not None}

    table = get_table()
    table.put_item(Item=item)

    # Build response body (exclude DynamoDB key attributes)
    response_body = {
        "memo_id": memo_id,
        "title": body["title"],
        "memo_type": memo_type,
        "memo_date": memo_date,
        "recorded_at": recorded_at,
        "person_brought_in": body.get("person_brought_in"),
        "person_took_out": body.get("person_took_out"),
        "created_by": body.get("created_by"),
        "entity_type": "MEMO",
    }
    response_body = {k: v for k, v in response_body.items() if v is not None}

    return success_response(response_body, status_code=201)
