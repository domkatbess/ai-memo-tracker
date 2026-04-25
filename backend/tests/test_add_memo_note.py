"""
Tests for the add_memo_note Lambda handler.
"""

import json
import re

import pytest
from moto import mock_aws

from backend.memo.add_memo_note import handler
from backend.shared.dynamodb import memo_pk, memo_sk, note_sk


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

# ISO 8601 UTC timestamp pattern: YYYY-MM-DDTHH:MM:SSZ
ISO_8601_UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _make_event(memo_id: str, body: dict) -> dict:
    """Build a minimal API Gateway proxy event for POST /memos/{id}/notes."""
    return {
        "pathParameters": {"id": memo_id},
        "body": json.dumps(body),
    }


def _parse_response(response: dict) -> tuple[int, dict]:
    """Return (status_code, parsed_body) from a Lambda proxy response."""
    return response["statusCode"], json.loads(response["body"])


def _insert_memo(table, item: dict | None = None):
    """Insert a memo item directly into the DynamoDB table."""
    table.put_item(Item=item or SAMPLE_MEMO_ITEM)


# ---------------------------------------------------------------------------
# 1. Successfully add a text note to an existing memo returns 201
# ---------------------------------------------------------------------------

class TestAddTextNote:
    def test_returns_201_with_note_data(self, dynamodb_table):
        _insert_memo(dynamodb_table)
        body = {
            "note_text": "Discussed with department head about budget.",
            "created_by": "user-42",
            "source": "text",
        }
        event = _make_event(SAMPLE_MEMO_ID, body)

        status, data = _parse_response(handler(event, None))

        assert status == 201
        assert data["memo_id"] == SAMPLE_MEMO_ID
        assert data["note_text"] == body["note_text"]
        assert data["created_by"] == body["created_by"]
        assert data["source"] == "text"
        assert data["entity_type"] == "MEMO_NOTE"


# ---------------------------------------------------------------------------
# 2. Successfully add a voice note to an existing memo returns 201
# ---------------------------------------------------------------------------

class TestAddVoiceNote:
    def test_returns_201_with_voice_source(self, dynamodb_table):
        _insert_memo(dynamodb_table)
        body = {
            "note_text": "Transcribed voice note about the memo.",
            "created_by": "user-55",
            "source": "voice",
        }
        event = _make_event(SAMPLE_MEMO_ID, body)

        status, data = _parse_response(handler(event, None))

        assert status == 201
        assert data["source"] == "voice"
        assert data["note_text"] == body["note_text"]
        assert data["created_by"] == body["created_by"]


# ---------------------------------------------------------------------------
# 3. Adding note to non-existent memo returns 404
# ---------------------------------------------------------------------------

class TestNoteOnNonExistentMemo:
    def test_returns_404_for_nonexistent_memo(self, dynamodb_table):
        body = {
            "note_text": "Some note",
            "created_by": "user-1",
            "source": "text",
        }
        event = _make_event("nonexistent-id", body)

        status, data = _parse_response(handler(event, None))

        assert status == 404
        assert data["error_code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# 4. Missing note_text returns 400 with missing_fields
# ---------------------------------------------------------------------------

class TestMissingNoteText:
    def test_returns_400_when_note_text_missing(self, dynamodb_table):
        _insert_memo(dynamodb_table)
        body = {
            "created_by": "user-1",
            "source": "text",
        }
        event = _make_event(SAMPLE_MEMO_ID, body)

        status, data = _parse_response(handler(event, None))

        assert status == 400
        assert data["error_code"] == "VALIDATION_ERROR"
        assert "note_text" in data["details"]["missing_fields"]


# ---------------------------------------------------------------------------
# 5. Missing created_by returns 400 with missing_fields
# ---------------------------------------------------------------------------

class TestMissingCreatedBy:
    def test_returns_400_when_created_by_missing(self, dynamodb_table):
        _insert_memo(dynamodb_table)
        body = {
            "note_text": "Some note",
            "source": "text",
        }
        event = _make_event(SAMPLE_MEMO_ID, body)

        status, data = _parse_response(handler(event, None))

        assert status == 400
        assert data["error_code"] == "VALIDATION_ERROR"
        assert "created_by" in data["details"]["missing_fields"]


# ---------------------------------------------------------------------------
# 6. Missing source returns 400 with missing_fields
# ---------------------------------------------------------------------------

class TestMissingSource:
    def test_returns_400_when_source_missing(self, dynamodb_table):
        _insert_memo(dynamodb_table)
        body = {
            "note_text": "Some note",
            "created_by": "user-1",
        }
        event = _make_event(SAMPLE_MEMO_ID, body)

        status, data = _parse_response(handler(event, None))

        assert status == 400
        assert data["error_code"] == "VALIDATION_ERROR"
        assert "source" in data["details"]["missing_fields"]


# ---------------------------------------------------------------------------
# 7. Note stored in DynamoDB with correct PK/SK pattern
# ---------------------------------------------------------------------------

class TestNoteStoredCorrectly:
    def test_note_stored_with_correct_pk_sk(self, dynamodb_table):
        _insert_memo(dynamodb_table)
        body = {
            "note_text": "Important observation.",
            "created_by": "user-10",
            "source": "text",
        }
        event = _make_event(SAMPLE_MEMO_ID, body)

        handler(event, None)

        # Query for note items under this memo
        result = dynamodb_table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
            ExpressionAttributeValues={
                ":pk": memo_pk(SAMPLE_MEMO_ID),
                ":sk_prefix": "NOTE#",
            },
        )
        notes = result["Items"]
        assert len(notes) == 1

        note = notes[0]
        assert note["PK"] == f"MEMO#{SAMPLE_MEMO_ID}"
        assert note["SK"].startswith("NOTE#")
        assert note["memo_id"] == SAMPLE_MEMO_ID
        assert note["note_text"] == "Important observation."
        assert note["created_by"] == "user-10"
        assert note["source"] == "text"
        assert note["entity_type"] == "MEMO_NOTE"


# ---------------------------------------------------------------------------
# 8. Note contains created_at timestamp in UTC ISO 8601 format
# ---------------------------------------------------------------------------

class TestNoteTimestamp:
    def test_created_at_is_utc_iso_8601(self, dynamodb_table):
        _insert_memo(dynamodb_table)
        body = {
            "note_text": "Timestamped note.",
            "created_by": "user-7",
            "source": "voice",
        }
        event = _make_event(SAMPLE_MEMO_ID, body)

        status, data = _parse_response(handler(event, None))

        assert status == 201
        assert "created_at" in data
        assert ISO_8601_UTC_PATTERN.match(data["created_at"]), (
            f"created_at '{data['created_at']}' does not match UTC ISO 8601 format"
        )


# ---------------------------------------------------------------------------
# 9. Invalid source value (not "voice" or "text") returns 400
# ---------------------------------------------------------------------------

class TestInvalidSource:
    def test_returns_400_for_invalid_source(self, dynamodb_table):
        _insert_memo(dynamodb_table)
        body = {
            "note_text": "Some note",
            "created_by": "user-1",
            "source": "email",
        }
        event = _make_event(SAMPLE_MEMO_ID, body)

        status, data = _parse_response(handler(event, None))

        assert status == 400
        assert data["error_code"] == "VALIDATION_ERROR"
        assert "source" in data["details"]["invalid_fields"]
