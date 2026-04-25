"""Lambda handler for creating a new memo record in DynamoDB."""

import json
import uuid
from datetime import datetime, timezone

import boto3

from backend.shared.config import AWS_REGION
from backend.shared.dynamodb import (
    get_table,
    memo_pk,
    memo_sk,
    gsi1_type_pk,
    gsi1_date_sk,
    gsi2_person_pk,
)
from backend.shared.response import error_response, success_response

VALID_MEMO_TYPES = ("incoming", "outgoing")


def handler(event, context):
    """Create a new memo record in DynamoDB."""
    try:
        body = json.loads(event.get("body", "{}"))
    except (json.JSONDecodeError, TypeError):
        return error_response(
            message="Invalid JSON in request body",
            error_code="VALIDATION_ERROR",
            status_code=400,
        )

    # Check universally required fields
    required = ("title", "memo_type", "memo_date")
    missing = [f for f in required if not body.get(f)]
    if missing:
        return error_response(
            message="Missing required fields",
            error_code="VALIDATION_ERROR",
            status_code=400,
            details={"missing_fields": missing},
        )

    memo_type = body["memo_type"]
    memo_date = body["memo_date"]

    # Validate memo_type
    if memo_type not in VALID_MEMO_TYPES:
        return error_response(
            message=f"Invalid memo_type. Must be one of: {', '.join(VALID_MEMO_TYPES)}",
            error_code="VALIDATION_ERROR",
            status_code=400,
            details={"invalid_fields": ["memo_type"]},
        )

    # Validate memo_date format
    from backend.shared.validators import is_valid_iso_date

    if not is_valid_iso_date(memo_date):
        return error_response(
            message="Invalid memo_date format. Expected ISO 8601 date (YYYY-MM-DD)",
            error_code="VALIDATION_ERROR",
            status_code=400,
            details={"invalid_fields": ["memo_date"]},
        )

    # Validate conditional person fields
    person_brought_in = body.get("person_brought_in", "")
    person_took_out = body.get("person_took_out", "")

    if memo_type == "incoming" and not person_brought_in:
        return error_response(
            message="Missing required fields",
            error_code="VALIDATION_ERROR",
            status_code=400,
            details={"missing_fields": ["person_brought_in"]},
        )

    if memo_type == "outgoing" and not person_took_out:
        return error_response(
            message="Missing required fields",
            error_code="VALIDATION_ERROR",
            status_code=400,
            details={"missing_fields": ["person_took_out"]},
        )

    # Build memo record
    new_memo_id = str(uuid.uuid4())
    recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    title = body["title"]
    created_by = body.get("created_by", "")

    # Determine person name for GSI2
    person_name = person_brought_in if memo_type == "incoming" else person_took_out

    item = {
        "PK": memo_pk(new_memo_id),
        "SK": memo_sk(),
        "memo_id": new_memo_id,
        "title": title,
        "memo_type": memo_type,
        "memo_date": memo_date,
        "recorded_at": recorded_at,
        "person_brought_in": person_brought_in,
        "person_took_out": person_took_out,
        "created_by": created_by,
        "entity_type": "MEMO",
        "GSI1PK": gsi1_type_pk(memo_type),
        "GSI1SK": gsi1_date_sk(memo_date),
        "GSI2PK": gsi2_person_pk(person_name.lower()),
        "GSI2SK": gsi1_date_sk(memo_date),
    }

    table = get_table()
    table.put_item(Item=item)

    return success_response(
        {
            "memo_id": new_memo_id,
            "title": title,
            "memo_type": memo_type,
            "memo_date": memo_date,
            "recorded_at": recorded_at,
            "person_brought_in": person_brought_in,
            "person_took_out": person_took_out,
            "created_by": created_by,
            "entity_type": "MEMO",
        },
        status_code=201,
    )
