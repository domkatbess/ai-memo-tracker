"""
Tests for the create_memo Lambda handler.
"""

import json
import uuid
from datetime import datetime, timezone

import pytest
from moto import mock_aws

from backend.memo.create_memo import handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(body: dict) -> dict:
    """Build a minimal API Gateway proxy event with the given body."""
    return {"body": json.dumps(body)}


def _parse_response(response: dict) -> tuple[int, dict]:
    """Return (status_code, parsed_body) from a Lambda proxy response."""
    return response["statusCode"], json.loads(response["body"])


def _incoming_memo_body(**overrides) -> dict:
    """Return a valid incoming memo request body."""
    base = {
        "title": "Budget Allocation Q3",
        "memo_type": "incoming",
        "memo_date": "2024-03-15",
        "person_brought_in": "Jane Doe",
    }
    base.update(overrides)
    return base


def _outgoing_memo_body(**overrides) -> dict:
    """Return a valid outgoing memo request body."""
    base = {
        "title": "Policy Update Notice",
        "memo_type": "outgoing",
        "memo_date": "2024-06-01",
        "person_took_out": "John Smith",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. Successful creation of incoming memo with all fields
# ---------------------------------------------------------------------------

class TestCreateIncomingMemo:
    def test_returns_201_with_all_fields(self, dynamodb_table):
        body = _incoming_memo_body(created_by="user-123")
        event = _make_event(body)

        status, data = _parse_response(handler(event, None))

        assert status == 201
        assert data["title"] == "Budget Allocation Q3"
        assert data["memo_type"] == "incoming"
        assert data["memo_date"] == "2024-03-15"
        assert data["person_brought_in"] == "Jane Doe"
        assert data["created_by"] == "user-123"
        assert data["entity_type"] == "MEMO"
        assert "memo_id" in data
        assert "recorded_at" in data

    def test_item_stored_in_dynamodb(self, dynamodb_table):
        body = _incoming_memo_body()
        event = _make_event(body)

        _, data = _parse_response(handler(event, None))

        # Verify item exists in DynamoDB
        result = dynamodb_table.get_item(
            Key={"PK": f"MEMO#{data['memo_id']}", "SK": "METADATA"}
        )
        item = result["Item"]
        assert item["title"] == "Budget Allocation Q3"
        assert item["GSI1PK"] == "TYPE#incoming"
        assert item["GSI1SK"] == "DATE#2024-03-15"
        assert item["GSI2PK"] == "PERSON#jane doe"
        assert item["GSI2SK"] == "DATE#2024-03-15"


# ---------------------------------------------------------------------------
# 2. Successful creation of outgoing memo with all fields
# ---------------------------------------------------------------------------

class TestCreateOutgoingMemo:
    def test_returns_201_with_all_fields(self, dynamodb_table):
        body = _outgoing_memo_body(created_by="user-456")
        event = _make_event(body)

        status, data = _parse_response(handler(event, None))

        assert status == 201
        assert data["title"] == "Policy Update Notice"
        assert data["memo_type"] == "outgoing"
        assert data["memo_date"] == "2024-06-01"
        assert data["person_took_out"] == "John Smith"
        assert data["created_by"] == "user-456"
        assert data["entity_type"] == "MEMO"

    def test_gsi2_uses_person_took_out_lowercased(self, dynamodb_table):
        body = _outgoing_memo_body()
        event = _make_event(body)

        _, data = _parse_response(handler(event, None))

        result = dynamodb_table.get_item(
            Key={"PK": f"MEMO#{data['memo_id']}", "SK": "METADATA"}
        )
        item = result["Item"]
        assert item["GSI2PK"] == "PERSON#john smith"


# ---------------------------------------------------------------------------
# 3. Missing required fields returns 400 with missing_fields
# ---------------------------------------------------------------------------

class TestMissingRequiredFields:
    def test_missing_title(self, dynamodb_table):
        body = _incoming_memo_body()
        del body["title"]
        event = _make_event(body)

        status, data = _parse_response(handler(event, None))

        assert status == 400
        assert data["error_code"] == "VALIDATION_ERROR"
        assert "title" in data["details"]["missing_fields"]

    def test_missing_memo_type(self, dynamodb_table):
        body = _incoming_memo_body()
        del body["memo_type"]
        event = _make_event(body)

        status, data = _parse_response(handler(event, None))

        assert status == 400
        assert "memo_type" in data["details"]["missing_fields"]

    def test_missing_memo_date(self, dynamodb_table):
        body = _incoming_memo_body()
        del body["memo_date"]
        event = _make_event(body)

        status, data = _parse_response(handler(event, None))

        assert status == 400
        assert "memo_date" in data["details"]["missing_fields"]

    def test_missing_multiple_fields(self, dynamodb_table):
        body = {"person_brought_in": "Jane Doe"}
        event = _make_event(body)

        status, data = _parse_response(handler(event, None))

        assert status == 400
        missing = data["details"]["missing_fields"]
        assert "title" in missing
        assert "memo_type" in missing
        assert "memo_date" in missing

    def test_empty_string_title_treated_as_missing(self, dynamodb_table):
        body = _incoming_memo_body(title="   ")
        event = _make_event(body)

        status, data = _parse_response(handler(event, None))

        assert status == 400
        assert "title" in data["details"]["missing_fields"]


# ---------------------------------------------------------------------------
# 4. Missing person_brought_in for incoming memo returns 400
# ---------------------------------------------------------------------------

class TestMissingPersonBroughtIn:
    def test_incoming_without_person_brought_in(self, dynamodb_table):
        body = {
            "title": "Test Memo",
            "memo_type": "incoming",
            "memo_date": "2024-01-01",
        }
        event = _make_event(body)

        status, data = _parse_response(handler(event, None))

        assert status == 400
        assert "person_brought_in" in data["details"]["missing_fields"]

    def test_incoming_with_empty_person_brought_in(self, dynamodb_table):
        body = _incoming_memo_body(person_brought_in="")
        event = _make_event(body)

        status, data = _parse_response(handler(event, None))

        assert status == 400
        assert "person_brought_in" in data["details"]["missing_fields"]


# ---------------------------------------------------------------------------
# 5. Missing person_took_out for outgoing memo returns 400
# ---------------------------------------------------------------------------

class TestMissingPersonTookOut:
    def test_outgoing_without_person_took_out(self, dynamodb_table):
        body = {
            "title": "Test Memo",
            "memo_type": "outgoing",
            "memo_date": "2024-01-01",
        }
        event = _make_event(body)

        status, data = _parse_response(handler(event, None))

        assert status == 400
        assert "person_took_out" in data["details"]["missing_fields"]

    def test_outgoing_with_empty_person_took_out(self, dynamodb_table):
        body = _outgoing_memo_body(person_took_out="")
        event = _make_event(body)

        status, data = _parse_response(handler(event, None))

        assert status == 400
        assert "person_took_out" in data["details"]["missing_fields"]


# ---------------------------------------------------------------------------
# 6. Invalid memo_type returns 400
# ---------------------------------------------------------------------------

class TestInvalidMemoType:
    def test_invalid_memo_type(self, dynamodb_table):
        body = _incoming_memo_body(memo_type="internal")
        event = _make_event(body)

        status, data = _parse_response(handler(event, None))

        assert status == 400
        assert data["error_code"] == "VALIDATION_ERROR"
        assert "memo_type" in data["details"]["invalid_fields"]


# ---------------------------------------------------------------------------
# 7. Invalid memo_date format returns 400
# ---------------------------------------------------------------------------

class TestInvalidMemoDate:
    def test_invalid_date_format(self, dynamodb_table):
        body = _incoming_memo_body(memo_date="15-03-2024")
        event = _make_event(body)

        status, data = _parse_response(handler(event, None))

        assert status == 400
        assert "memo_date" in data["details"]["invalid_fields"]

    def test_non_date_string(self, dynamodb_table):
        body = _incoming_memo_body(memo_date="not-a-date")
        event = _make_event(body)

        status, data = _parse_response(handler(event, None))

        assert status == 400
        assert "memo_date" in data["details"]["invalid_fields"]


# ---------------------------------------------------------------------------
# 8. Verify memo_id is a valid UUID
# ---------------------------------------------------------------------------

class TestMemoIdIsUUID:
    def test_memo_id_is_valid_uuid(self, dynamodb_table):
        body = _incoming_memo_body()
        event = _make_event(body)

        _, data = _parse_response(handler(event, None))

        # Should not raise
        parsed = uuid.UUID(data["memo_id"])
        assert str(parsed) == data["memo_id"]

    def test_each_memo_gets_unique_id(self, dynamodb_table):
        ids = set()
        for _ in range(5):
            body = _incoming_memo_body()
            event = _make_event(body)
            _, data = _parse_response(handler(event, None))
            ids.add(data["memo_id"])
        assert len(ids) == 5


# ---------------------------------------------------------------------------
# 9. Verify recorded_at is a valid UTC ISO 8601 timestamp
# ---------------------------------------------------------------------------

class TestRecordedAtTimestamp:
    def test_recorded_at_is_valid_utc_iso8601(self, dynamodb_table):
        body = _incoming_memo_body()
        event = _make_event(body)

        _, data = _parse_response(handler(event, None))

        recorded_at = data["recorded_at"]
        # Should end with Z (UTC)
        assert recorded_at.endswith("Z")
        # Should parse without error
        dt = datetime.strptime(recorded_at, "%Y-%m-%dT%H:%M:%SZ")
        assert dt.year >= 2024

    def test_recorded_at_is_close_to_now(self, dynamodb_table):
        body = _incoming_memo_body()
        event = _make_event(body)

        before = datetime.now(timezone.utc).replace(microsecond=0)
        _, data = _parse_response(handler(event, None))
        after = datetime.now(timezone.utc).replace(microsecond=0)

        recorded = datetime.strptime(
            data["recorded_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)

        assert before <= recorded <= after
