"""
Tests for the get_access_log Lambda handler.
"""

import json

import pytest
from moto import mock_aws

from backend.memo.get_access_log import handler
from backend.shared.dynamodb import memo_pk, log_sk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_MEMO_ID = "memo-1111-2222-3333"


def _make_event(memo_id: str, role: str = "superuser", include_claims: bool = True) -> dict:
    """Build a minimal API Gateway proxy event for GET /memos/{id}/access-log."""
    event = {
        "pathParameters": {"id": memo_id},
        "requestContext": {
            "authorizer": {
                "claims": {},
            },
        },
    }
    if include_claims and role is not None:
        event["requestContext"]["authorizer"]["claims"]["custom:role"] = role
    return event


def _make_event_missing_role(memo_id: str) -> dict:
    """Build an event where custom:role is absent from claims."""
    return {
        "pathParameters": {"id": memo_id},
        "requestContext": {
            "authorizer": {
                "claims": {},
            },
        },
    }


def _parse_response(response: dict) -> tuple[int, dict]:
    """Return (status_code, parsed_body) from a Lambda proxy response."""
    return response["statusCode"], json.loads(response["body"])


def _insert_log_entry(table, memo_id: str, user_id: str, user_name: str,
                       action: str, timestamp: str):
    """Insert an access log item directly into the DynamoDB table."""
    table.put_item(Item={
        "PK": memo_pk(memo_id),
        "SK": log_sk(timestamp, user_id),
        "memo_id": memo_id,
        "user_id": user_id,
        "user_name": user_name,
        "action": action,
        "timestamp": timestamp,
        "entity_type": "ACCESS_LOG",
    })


# ---------------------------------------------------------------------------
# 1. Superuser can retrieve access logs — returns 200
# ---------------------------------------------------------------------------

class TestSuperuserCanRetrieveAccessLogs:
    def test_returns_200_with_access_logs(self, dynamodb_table):
        _insert_log_entry(
            dynamodb_table, SAMPLE_MEMO_ID,
            user_id="user-1", user_name="Alice",
            action="VIEW", timestamp="2024-03-15T10:00:00Z",
        )
        event = _make_event(SAMPLE_MEMO_ID, role="superuser")

        status, data = _parse_response(handler(event, None))

        assert status == 200
        assert data["count"] == 1
        assert len(data["access_logs"]) == 1
        log = data["access_logs"][0]
        assert log["memo_id"] == SAMPLE_MEMO_ID
        assert log["user_id"] == "user-1"
        assert log["user_name"] == "Alice"
        assert log["action"] == "VIEW"
        assert log["timestamp"] == "2024-03-15T10:00:00Z"
        assert log["entity_type"] == "ACCESS_LOG"


# ---------------------------------------------------------------------------
# 2. Non-superuser gets 403 FORBIDDEN
# ---------------------------------------------------------------------------

class TestNonSuperuserForbidden:
    def test_regular_user_gets_403(self, dynamodb_table):
        event = _make_event(SAMPLE_MEMO_ID, role="regular_user")

        status, data = _parse_response(handler(event, None))

        assert status == 403
        assert data["error_code"] == "FORBIDDEN"

    def test_unknown_role_gets_403(self, dynamodb_table):
        event = _make_event(SAMPLE_MEMO_ID, role="admin")

        status, data = _parse_response(handler(event, None))

        assert status == 403
        assert data["error_code"] == "FORBIDDEN"


# ---------------------------------------------------------------------------
# 3. Access logs returned in descending timestamp order
# ---------------------------------------------------------------------------

class TestDescendingTimestampOrder:
    def test_logs_returned_in_descending_order(self, dynamodb_table):
        timestamps = [
            "2024-03-15T08:00:00Z",
            "2024-03-15T10:00:00Z",
            "2024-03-15T12:00:00Z",
        ]
        for i, ts in enumerate(timestamps):
            _insert_log_entry(
                dynamodb_table, SAMPLE_MEMO_ID,
                user_id=f"user-{i}", user_name=f"User{i}",
                action="VIEW", timestamp=ts,
            )

        event = _make_event(SAMPLE_MEMO_ID, role="superuser")
        status, data = _parse_response(handler(event, None))

        assert status == 200
        assert data["count"] == 3
        returned_timestamps = [log["timestamp"] for log in data["access_logs"]]
        # Should be descending: 12:00, 10:00, 08:00
        assert returned_timestamps == sorted(returned_timestamps, reverse=True)


# ---------------------------------------------------------------------------
# 4. Empty access log returns 200 with empty array
# ---------------------------------------------------------------------------

class TestEmptyAccessLog:
    def test_returns_200_with_empty_array(self, dynamodb_table):
        event = _make_event(SAMPLE_MEMO_ID, role="superuser")

        status, data = _parse_response(handler(event, None))

        assert status == 200
        assert data["access_logs"] == []
        assert data["count"] == 0


# ---------------------------------------------------------------------------
# 5. Response excludes DynamoDB key attributes (PK, SK)
# ---------------------------------------------------------------------------

class TestExcludeKeyAttributes:
    def test_pk_and_sk_not_in_response(self, dynamodb_table):
        _insert_log_entry(
            dynamodb_table, SAMPLE_MEMO_ID,
            user_id="user-1", user_name="Alice",
            action="VIEW", timestamp="2024-03-15T10:00:00Z",
        )
        event = _make_event(SAMPLE_MEMO_ID, role="superuser")

        _, data = _parse_response(handler(event, None))

        for log in data["access_logs"]:
            assert "PK" not in log
            assert "SK" not in log


# ---------------------------------------------------------------------------
# 6. Multiple log entries returned correctly
# ---------------------------------------------------------------------------

class TestMultipleLogEntries:
    def test_multiple_entries_returned_with_correct_count(self, dynamodb_table):
        entries = [
            ("user-1", "Alice", "VIEW", "2024-03-15T09:00:00Z"),
            ("user-2", "Bob", "VIEW", "2024-03-15T10:00:00Z"),
            ("user-3", "Charlie", "SEARCH_RESULT", "2024-03-15T11:00:00Z"),
            ("user-1", "Alice", "VIEW", "2024-03-15T12:00:00Z"),
        ]
        for user_id, user_name, action, ts in entries:
            _insert_log_entry(
                dynamodb_table, SAMPLE_MEMO_ID,
                user_id=user_id, user_name=user_name,
                action=action, timestamp=ts,
            )

        event = _make_event(SAMPLE_MEMO_ID, role="superuser")
        status, data = _parse_response(handler(event, None))

        assert status == 200
        assert data["count"] == 4
        assert len(data["access_logs"]) == 4

        # Verify all user_ids are present
        user_ids = [log["user_id"] for log in data["access_logs"]]
        assert "user-1" in user_ids
        assert "user-2" in user_ids
        assert "user-3" in user_ids


# ---------------------------------------------------------------------------
# 7. Missing role in claims returns 403
# ---------------------------------------------------------------------------

class TestMissingRoleForbidden:
    def test_missing_role_returns_403(self, dynamodb_table):
        event = _make_event_missing_role(SAMPLE_MEMO_ID)

        status, data = _parse_response(handler(event, None))

        assert status == 403
        assert data["error_code"] == "FORBIDDEN"
