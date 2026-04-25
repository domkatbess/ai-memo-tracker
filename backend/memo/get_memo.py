"""
Lambda handler for retrieving a single memo record.

GET /memos/{id}

Creates an access log entry each time a memo is viewed.
"""

from datetime import datetime, timezone

from backend.shared.dynamodb import get_table, memo_pk, memo_sk, log_sk
from backend.shared.response import error_response, success_response, NOT_FOUND


# DynamoDB key attributes to strip from the response
_KEY_ATTRIBUTES = {"PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK"}


def handler(event, context):
    """Retrieve a memo by ID and log the access."""
    memo_id = event["pathParameters"]["id"]

    # Extract viewer identity from query string parameters
    params = event.get("queryStringParameters") or {}
    user_id = params.get("user_id", "anonymous")
    user_name = params.get("user_name", "Anonymous")

    table = get_table()

    # --- Fetch memo metadata ---
    result = table.get_item(
        Key={"PK": memo_pk(memo_id), "SK": memo_sk()}
    )

    item = result.get("Item")
    if not item:
        return error_response("Memo not found", NOT_FOUND, status_code=404)

    # --- Create access log entry ---
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    log_entry = {
        "PK": memo_pk(memo_id),
        "SK": log_sk(timestamp, user_id),
        "memo_id": memo_id,
        "user_id": user_id,
        "user_name": user_name,
        "action": "VIEW",
        "timestamp": timestamp,
        "entity_type": "ACCESS_LOG",
    }
    table.put_item(Item=log_entry)

    # --- Build response (exclude DynamoDB key attributes) ---
    response_body = {k: v for k, v in item.items() if k not in _KEY_ATTRIBUTES}

    return success_response(response_body)
