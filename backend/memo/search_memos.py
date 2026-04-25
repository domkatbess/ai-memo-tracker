"""
Lambda handler for searching memo records.

GET /memos?title=...&date_from=...&date_to=...&memo_type=...&person_name=...
"""

from boto3.dynamodb.conditions import Key, Attr

from backend.shared.dynamodb import get_table, gsi1_type_pk, gsi1_date_sk, gsi2_person_pk
from backend.shared.response import success_response


# DynamoDB key attributes to strip from the response
_KEY_ATTRIBUTES = {"PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK"}


def _strip_keys(item: dict) -> dict:
    """Remove DynamoDB key attributes from an item."""
    return {k: v for k, v in item.items() if k not in _KEY_ATTRIBUTES}


def handler(event, context):
    """Search memos by title, date range, memo type, or person name."""
    params = event.get("queryStringParameters") or {}

    title = params.get("title")
    date_from = params.get("date_from")
    date_to = params.get("date_to")
    memo_type = params.get("memo_type")
    person_name = params.get("person_name")

    table = get_table()

    # --- Search by person_name (with optional date range) via GSI2 ---
    if person_name:
        key_condition = Key("GSI2PK").eq(gsi2_person_pk(person_name))
        if date_from and date_to:
            key_condition = key_condition & Key("GSI2SK").between(
                gsi1_date_sk(date_from), gsi1_date_sk(date_to)
            )
        result = table.query(IndexName="GSI2", KeyConditionExpression=key_condition)
        memos = [_strip_keys(item) for item in result["Items"]]
        return success_response({"memos": memos, "count": len(memos)})

    # --- Search by memo_type (with optional date range) via GSI1 ---
    if memo_type:
        key_condition = Key("GSI1PK").eq(gsi1_type_pk(memo_type))
        if date_from and date_to:
            key_condition = key_condition & Key("GSI1SK").between(
                gsi1_date_sk(date_from), gsi1_date_sk(date_to)
            )
        result = table.query(IndexName="GSI1", KeyConditionExpression=key_condition)
        memos = [_strip_keys(item) for item in result["Items"]]
        return success_response({"memos": memos, "count": len(memos)})

    # --- Search by title (scan with case-insensitive contains filter) ---
    if title:
        title_lower = title.lower()
        # DynamoDB `contains` is case-sensitive, so we scan for MEMO entities
        # and apply the case-insensitive filter in Python.
        scan_kwargs = {
            "FilterExpression": Attr("entity_type").eq("MEMO"),
        }
        items = _full_scan(table, scan_kwargs)
        items = [
            item for item in items if title_lower in item.get("title", "").lower()
        ]
        memos = [_strip_keys(item) for item in items]
        return success_response({"memos": memos, "count": len(memos)})

    # --- Search by date range only (scan with filter) ---
    if date_from and date_to:
        scan_kwargs = {
            "FilterExpression": Attr("entity_type").eq("MEMO")
            & Attr("memo_date").between(date_from, date_to),
        }
        items = _full_scan(table, scan_kwargs)
        memos = [_strip_keys(item) for item in items]
        return success_response({"memos": memos, "count": len(memos)})

    # --- No parameters: return all memos ---
    scan_kwargs = {
        "FilterExpression": Attr("entity_type").eq("MEMO"),
    }
    items = _full_scan(table, scan_kwargs)
    memos = [_strip_keys(item) for item in items]
    return success_response({"memos": memos, "count": len(memos)})


def _full_scan(table, scan_kwargs: dict) -> list[dict]:
    """Perform a full table scan handling pagination."""
    items = []
    result = table.scan(**scan_kwargs)
    items.extend(result["Items"])
    while "LastEvaluatedKey" in result:
        scan_kwargs["ExclusiveStartKey"] = result["LastEvaluatedKey"]
        result = table.scan(**scan_kwargs)
        items.extend(result["Items"])
    return items
