"""
Lambda handler for retrieving access log entries for a memo.

GET /memos/{id}/access-log

Superuser-only endpoint. Returns access log entries in descending
timestamp order.
"""

from backend.shared.dynamodb import get_table, memo_pk
from backend.shared.response import error_response, success_response, FORBIDDEN


# DynamoDB key attributes to strip from the response
_KEY_ATTRIBUTES = {"PK", "SK"}


def handler(event, context):
    """Return access log entries for a memo (superuser only)."""
    # --- Enforce superuser-only access ---
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
    )
    role = claims.get("custom:role")

    if role != "superuser":
        return error_response(
            "Only superusers can view access logs",
            FORBIDDEN,
            status_code=403,
        )

    memo_id = event["pathParameters"]["id"]
    table = get_table()

    # --- Query access log entries (descending by timestamp) ---
    result = table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
        ExpressionAttributeValues={
            ":pk": memo_pk(memo_id),
            ":sk_prefix": "LOG#",
        },
        ScanIndexForward=False,
    )

    items = result.get("Items", [])

    # Strip DynamoDB key attributes from each entry
    access_logs = [
        {k: v for k, v in item.items() if k not in _KEY_ATTRIBUTES}
        for item in items
    ]

    return success_response({
        "access_logs": access_logs,
        "count": len(access_logs),
    })
