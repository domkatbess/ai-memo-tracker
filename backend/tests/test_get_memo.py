"""
Tests for the get_memo Lambda handler.
"""

import json
import time

import pytest
from moto import mock_aws

from backend.memo.get_memo import handler
from backend.shared.dynamodb import memo_pk, memo_sk, log_sk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_MEMO_ID = "aaaa-bbbb-cccc-dddd"

SAMPLE_MEMO_ITEM = {
    "PK": memo_pk(SAMPLE_MEMO_ID),
    "SK": memo_sk(),
    "memo_id": SAMPLE_MEMO_ID,
    "title": "Budget Allocation Q3",
    "memo_type": "incoming",
    "memo_date": "2024-03-15",
    "recorded_at": "2024-03-15T10:30:00Z",
    "person_brought_in": "Jane Doe",
    "created_by": "user-100",
    "entity_type": "MEMO",
    "GSI1PK": "TYPE#incoming",
    "GSI1SK": "DATE#2024-03-15",
    "GSI2PK": "PERSON#jane doe",
    "GSI2SK": "DATE#2024-03-15",
}


def _make_event(memo_id: str, user_id: str = "user-1", user_name: str = "Alice") -> dict:
    """Build a minimal API Gateway proxy event for GET /memos/{id}."""
    return {
        "pathParameters": {"id": memo_id},
        "queryStringParameters": {
            "user_id": user_id,
            "user_name": user_name,
        },
    }


def _parse_response(response: dict) -> tuple[int, dict]:
    """Return (status_code, parsed_body) from a Lambda proxy response."""
    return response["statusCode"], json.loads(response["body"])


def _insert_memo(table, item: dict | None = None):
    """Insert a memo item directly into the DynamoDB table."""
    table.put_item(Item=item or SAMPLE_MEMO_ITEM)


# ---------------------------------------------------------------------------
# 1. Successfully retrieve an existing memo returns 200 with all fields
# ---------------------------------------------------------------------------

class TestGetMemoSuccess:
    def test_returns_200_with_all_metadata_fields(self, dynamodb_table):
        _insert_memo(dynamodb_table)
        event = _make_event(SAMPLE_MEMO_ID)

        status, data = _parse_response(handler(event, None))

        assert status == 200
        assert data["memo_id"] == SAMPLE_MEMO_ID
        assert data["title"] == "Budget Allocation Q3"
        assert data["memo_type"] == "incoming"
        assert data["memo_date"] == "2024-03-15"
        assert data["recorded_at"] == "2024-03-15T10:30:00Z"
        assert data["person_brought_in"] == "Jane Doe"
        assert data["created_by"] == "user-100"
        assert data["entity_type"] == "MEMO"

    def test_response_excludes_dynamodb_key_attributes(self, dynamodb_table):
        _insert_memo(dynamodb_table)
        event = _make_event(SAMPLE_MEMO_ID)

        _, data = _parse_response(handler(event, None))

        for key in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK"):
            assert key not in data


# ---------------------------------------------------------------------------
# 2. Retrieving a non-existent memo returns 404
# ---------------------------------------------------------------------------

class TestGetMemoNotFound:
    def test_returns_404_for_nonexistent_memo(self, dynamodb_table):
        event = _make_event("nonexistent-id")

        status, data = _parse_response(handler(event, None))

        assert status == 404
        assert data["error_code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# 3. Access log entry is created when memo is viewed
# ---------------------------------------------------------------------------

class TestAccessLogCreation:
    def test_access_log_entry_created_on_view(self, dynamodb_table):
        _insert_memo(dynamodb_table)
        event = _make_event(SAMPLE_MEMO_ID, user_id="user-42", user_name="Bob")

        handler(event, None)

        # Query for access log entries under this memo
        result = dynamodb_table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
            ExpressionAttributeValues={
                ":pk": memo_pk(SAMPLE_MEMO_ID),
                ":sk_prefix": "LOG#",
            },
        )
        logs = result["Items"]
        assert len(logs) == 1
        assert logs[0]["entity_type"] == "ACCESS_LOG"


# ---------------------------------------------------------------------------
# 4. Access log contains correct user_id, user_name, action, timestamp, memo_id
# ---------------------------------------------------------------------------

class TestAccessLogFields:
    def test_access_log_has_correct_fields(self, dynamodb_table):
        _insert_memo(dynamodb_table)
        event = _make_event(SAMPLE_MEMO_ID, user_id="user-42", user_name="Bob")

        handler(event, None)

        result = dynamodb_table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
            ExpressionAttributeValues={
                ":pk": memo_pk(SAMPLE_MEMO_ID),
                ":sk_prefix": "LOG#",
            },
        )
        log = result["Items"][0]

        assert log["memo_id"] == SAMPLE_MEMO_ID
        assert log["user_id"] == "user-42"
        assert log["user_name"] == "Bob"
        assert log["action"] == "VIEW"
        assert "timestamp" in log
        # Timestamp should be a valid UTC ISO 8601 string
        assert log["timestamp"].endswith("Z")


# ---------------------------------------------------------------------------
# 5. Multiple views create multiple access log entries
# ---------------------------------------------------------------------------

class TestMultipleAccessLogs:
    def test_multiple_views_create_multiple_log_entries(self, dynamodb_table):
        _insert_memo(dynamodb_table)

        # Simulate three views by different users with small delays
        # to ensure distinct timestamps
        users = [
            ("user-1", "Alice"),
            ("user-2", "Bob"),
            ("user-3", "Charlie"),
        ]
        for user_id, user_name in users:
            event = _make_event(SAMPLE_MEMO_ID, user_id=user_id, user_name=user_name)
            status, _ = _parse_response(handler(event, None))
            assert status == 200
            # Small sleep to ensure unique timestamps in sort keys
            time.sleep(0.01)

        result = dynamodb_table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
            ExpressionAttributeValues={
                ":pk": memo_pk(SAMPLE_MEMO_ID),
                ":sk_prefix": "LOG#",
            },
        )
        logs = result["Items"]
        assert len(logs) == 3

        # Verify each user has a log entry
        logged_user_ids = {log["user_id"] for log in logs}
        assert logged_user_ids == {"user-1", "user-2", "user-3"}
