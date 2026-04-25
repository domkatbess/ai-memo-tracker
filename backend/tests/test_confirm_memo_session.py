"""Unit tests for the confirm_memo_session Lambda handler."""

import json
import time
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from backend.shared.config import AUDIO_BUCKET, AWS_REGION, TABLE_NAME
from backend.shared.dynamodb import memo_pk, memo_sk
from backend.voice.confirm_memo_session import handler
from backend.voice.start_memo_session import FIELD_ORDER


def _make_event(session_id, body=None):
    """Build a minimal API Gateway event with path params and body."""
    return {
        "pathParameters": {"session_id": session_id},
        "body": json.dumps(body) if body is not None else "{}",
    }


def _create_complete_incoming_session(
    table,
    session_id,
    user_id="user-123",
    title="Budget Allocation Q3",
    memo_date="2024-03-15",
    person="Jane Doe",
):
    """Insert a complete incoming voice session into DynamoDB."""
    item = {
        "PK": f"VSESSION#{session_id}",
        "SK": "METADATA",
        "session_id": session_id,
        "user_id": user_id,
        "status": "fields_complete",
        "current_field": None,
        "fields_collected": {
            "title": title,
            "memo_type": "incoming",
            "memo_date": memo_date,
            "person_brought_in": person,
            "person_took_out": None,
        },
        "field_order": FIELD_ORDER,
        "retry_counts": {"title": 0, "memo_type": 0, "memo_date": 0, "person": 0},
        "ttl": int(time.time()) + 3600,
        "entity_type": "VOICE_SESSION",
    }
    table.put_item(Item=item)
    return item


def _create_incomplete_session(table, session_id):
    """Insert an incomplete voice session into DynamoDB."""
    item = {
        "PK": f"VSESSION#{session_id}",
        "SK": "METADATA",
        "session_id": session_id,
        "user_id": "user-123",
        "status": "in_progress",
        "current_field": "memo_date",
        "fields_collected": {
            "title": "Some Title",
            "memo_type": "incoming",
            "memo_date": None,
            "person_brought_in": None,
            "person_took_out": None,
        },
        "field_order": FIELD_ORDER,
        "retry_counts": {"title": 0, "memo_type": 0, "memo_date": 0, "person": 0},
        "ttl": int(time.time()) + 3600,
        "entity_type": "VOICE_SESSION",
    }
    table.put_item(Item=item)
    return item


def _patch_transcribe(text):
    """Patch _transcribe_audio to return the given text."""
    return patch(
        "backend.voice.confirm_memo_session._transcribe_audio",
        return_value=text,
    )


@pytest.fixture
def aws_env(monkeypatch):
    """Set fake AWS credentials for moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", AWS_REGION)


@pytest.fixture
def full_aws(aws_env):
    """Mock all AWS services needed by confirm_memo_session."""
    with mock_aws():
        # Create DynamoDB table with GSIs
        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        table = dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Create S3 bucket
        s3 = boto3.client("s3", region_name=AWS_REGION)
        s3.create_bucket(Bucket=AUDIO_BUCKET)

        yield {
            "dynamodb": dynamodb,
            "table": table,
            "s3": s3,
        }


class TestConfirmedYes:
    """Tests for confirmed ('yes') creating memo and returning 201."""

    def test_confirmed_returns_201_with_memo_id(self, full_aws):
        session_id = "confirm-yes-1"
        _create_complete_incoming_session(full_aws["table"], session_id)

        with _patch_transcribe("yes"):
            event = _make_event(session_id, {"audio_key": "uploads/confirm.wav"})
            result = handler(event, None)

        assert result["statusCode"] == 201
        body = json.loads(result["body"])
        assert body["status"] == "saved"
        assert "memo_id" in body
        assert body["memo_id"]  # non-empty
        assert "confirmation_audio_url" in body
        assert body["confirmation_audio_url"]

    def test_confirmed_memo_stored_in_dynamodb(self, full_aws):
        session_id = "confirm-yes-db"
        _create_complete_incoming_session(
            full_aws["table"],
            session_id,
            title="Budget Allocation Q3",
            memo_date="2024-03-15",
            person="Jane Doe",
        )

        with _patch_transcribe("yes"):
            event = _make_event(session_id, {"audio_key": "uploads/confirm.wav"})
            result = handler(event, None)

        body = json.loads(result["body"])
        new_memo_id = body["memo_id"]

        # Verify memo exists in DynamoDB
        memo_item = full_aws["table"].get_item(
            Key={"PK": memo_pk(new_memo_id), "SK": memo_sk()}
        ).get("Item")

        assert memo_item is not None
        assert memo_item["title"] == "Budget Allocation Q3"
        assert memo_item["memo_type"] == "incoming"
        assert memo_item["memo_date"] == "2024-03-15"
        assert memo_item["person_brought_in"] == "Jane Doe"
        assert memo_item["created_by"] == "user-123"
        assert memo_item["entity_type"] == "MEMO"
        assert "recorded_at" in memo_item
        assert "GSI1PK" in memo_item
        assert "GSI2PK" in memo_item

    def test_session_status_updated_to_saved(self, full_aws):
        session_id = "confirm-yes-status"
        _create_complete_incoming_session(full_aws["table"], session_id)

        with _patch_transcribe("yes"):
            event = _make_event(session_id, {"audio_key": "uploads/confirm.wav"})
            handler(event, None)

        # Verify session status updated
        session_item = full_aws["table"].get_item(
            Key={"PK": f"VSESSION#{session_id}", "SK": "METADATA"}
        ).get("Item")

        assert session_item["status"] == "saved"

    def test_confirmed_with_phrase_containing_yes(self, full_aws):
        session_id = "confirm-yes-phrase"
        _create_complete_incoming_session(full_aws["table"], session_id)

        with _patch_transcribe("yes please save it"):
            event = _make_event(session_id, {"audio_key": "uploads/confirm.wav"})
            result = handler(event, None)

        assert result["statusCode"] == 201
        body = json.loads(result["body"])
        assert body["status"] == "saved"


class TestRejectedNo:
    """Tests for rejected ('no') returning 200 with collected_data and options."""

    def test_rejected_returns_200_with_collected_data(self, full_aws):
        session_id = "confirm-no-1"
        _create_complete_incoming_session(full_aws["table"], session_id)

        with _patch_transcribe("no"):
            event = _make_event(session_id, {"audio_key": "uploads/confirm.wav"})
            result = handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["status"] == "rejected"
        assert "collected_data" in body
        assert body["collected_data"]["title"] == "Budget Allocation Q3"
        assert body["collected_data"]["memo_type"] == "incoming"
        assert body["collected_data"]["memo_date"] == "2024-03-15"
        assert body["collected_data"]["person_brought_in"] == "Jane Doe"
        assert body["options"] == ["re-record", "cancel"]
        assert "prompt_audio_url" in body
        assert body["prompt_audio_url"]


class TestUnclearResponse:
    """Tests for unclear response returning 422 CONFIRMATION_UNCLEAR."""

    def test_unclear_returns_422_with_error_code(self, full_aws):
        session_id = "confirm-unclear-1"
        _create_complete_incoming_session(full_aws["table"], session_id)

        with _patch_transcribe("maybe I think so"):
            event = _make_event(session_id, {"audio_key": "uploads/confirm.wav"})
            result = handler(event, None)

        assert result["statusCode"] == 422
        body = json.loads(result["body"])
        assert body["error"] == "Could not understand confirmation"
        assert body["error_code"] == "CONFIRMATION_UNCLEAR"
        assert "prompt_audio_url" in body
        assert body["prompt_audio_url"]


class TestSessionNotFound:
    """Tests for session not found returning 404."""

    def test_nonexistent_session_returns_404(self, full_aws):
        with _patch_transcribe("yes"):
            event = _make_event("nonexistent-session", {"audio_key": "uploads/confirm.wav"})
            result = handler(event, None)

        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert body["error_code"] == "SESSION_NOT_FOUND"


class TestValidationErrors:
    """Tests for missing audio_key and session_id."""

    def test_missing_audio_key_returns_400(self, full_aws):
        session_id = "confirm-no-audio"
        _create_complete_incoming_session(full_aws["table"], session_id)

        event = _make_event(session_id, {})
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_missing_session_id_returns_400(self, full_aws):
        event = {
            "pathParameters": {},
            "body": json.dumps({"audio_key": "uploads/confirm.wav"}),
        }
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_no_path_parameters_returns_400(self, full_aws):
        event = {
            "pathParameters": None,
            "body": json.dumps({"audio_key": "uploads/confirm.wav"}),
        }
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"


class TestSessionIncomplete:
    """Tests for incomplete session returning 400."""

    def test_incomplete_session_returns_400(self, full_aws):
        session_id = "confirm-incomplete"
        _create_incomplete_session(full_aws["table"], session_id)

        with _patch_transcribe("yes"):
            event = _make_event(session_id, {"audio_key": "uploads/confirm.wav"})
            result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "SESSION_INCOMPLETE"
