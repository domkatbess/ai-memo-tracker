"""Unit tests for the submit_session_field Lambda handler."""

import json
import time
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from backend.shared.config import AUDIO_BUCKET, AWS_REGION, TABLE_NAME
from backend.voice.start_memo_session import FIELD_ORDER, FIELD_PROMPTS
from backend.voice.submit_session_field import handler


def _make_event(session_id, body=None):
    """Build a minimal API Gateway event with path params and body."""
    return {
        "pathParameters": {"session_id": session_id},
        "body": json.dumps(body) if body is not None else "{}",
    }


def _create_session_item(table, session_id, current_field="title", fields_collected=None, retry_counts=None):
    """Insert a voice session item into DynamoDB for testing."""
    if fields_collected is None:
        fields_collected = {
            "title": None,
            "memo_type": None,
            "memo_date": None,
            "person_brought_in": None,
            "person_took_out": None,
        }
    if retry_counts is None:
        retry_counts = {
            "title": 0,
            "memo_type": 0,
            "memo_date": 0,
            "person": 0,
        }

    item = {
        "PK": f"VSESSION#{session_id}",
        "SK": "METADATA",
        "session_id": session_id,
        "user_id": "user-123",
        "status": "in_progress",
        "current_field": current_field,
        "fields_collected": fields_collected,
        "field_order": FIELD_ORDER,
        "retry_counts": retry_counts,
        "ttl": int(time.time()) + 3600,
        "entity_type": "VOICE_SESSION",
    }
    table.put_item(Item=item)
    return item


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
    """Mock all AWS services needed by submit_session_field."""
    with mock_aws():
        # Create DynamoDB table
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
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Create S3 bucket and upload a test audio file
        s3 = boto3.client("s3", region_name=AWS_REGION)
        s3.create_bucket(Bucket=AUDIO_BUCKET)
        s3.put_object(
            Bucket=AUDIO_BUCKET,
            Key="uploads/test-audio.wav",
            Body=b"fake-audio-data",
        )

        yield {
            "dynamodb": dynamodb,
            "table": table,
            "s3": s3,
        }


def _patch_transcribe_success(text="Budget Allocation Q3"):
    """Return a patch context manager that makes _transcribe_audio return the given text."""
    return patch(
        "backend.voice.submit_session_field._transcribe_audio",
        return_value=text,
    )


def _patch_transcribe_failure():
    """Return a patch context manager that makes _transcribe_audio return None (failure)."""
    return patch(
        "backend.voice.submit_session_field._transcribe_audio",
        return_value=None,
    )


class TestSubmitFieldSuccess:
    """Tests for successful field submission advancing to next field."""

    def test_submit_title_advances_to_memo_type(self, full_aws):
        session_id = "test-session-1"
        _create_session_item(full_aws["table"], session_id, current_field="title")

        with _patch_transcribe_success("Budget Allocation Q3"):
            event = _make_event(session_id, {"audio_key": "uploads/test-audio.wav"})
            result = handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["field_name"] == "title"
        assert body["field_value"] == "Budget Allocation Q3"
        assert body["current_field"] == "memo_type"
        assert body["status"] == "in_progress"
        assert "memo_date" in body["fields_remaining"]
        assert "person" in body["fields_remaining"]
        assert body["next_prompt_audio_url"] is not None

    def test_submit_memo_type_incoming(self, full_aws):
        session_id = "test-session-2"
        _create_session_item(
            full_aws["table"],
            session_id,
            current_field="memo_type",
            fields_collected={
                "title": "Test Memo",
                "memo_type": None,
                "memo_date": None,
                "person_brought_in": None,
                "person_took_out": None,
            },
        )

        with _patch_transcribe_success("incoming"):
            event = _make_event(session_id, {"audio_key": "uploads/test-audio.wav"})
            result = handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["field_name"] == "memo_type"
        assert body["field_value"] == "incoming"
        assert body["current_field"] == "memo_date"
        assert body["status"] == "in_progress"

    def test_session_updated_in_dynamodb(self, full_aws):
        session_id = "test-session-db-check"
        _create_session_item(full_aws["table"], session_id, current_field="title")

        with _patch_transcribe_success("My Memo Title"):
            event = _make_event(session_id, {"audio_key": "uploads/test-audio.wav"})
            handler(event, None)

        item = full_aws["table"].get_item(
            Key={"PK": f"VSESSION#{session_id}", "SK": "METADATA"}
        )["Item"]
        assert item["fields_collected"]["title"] == "My Memo Title"
        assert item["current_field"] == "memo_type"


class TestAllFieldsCollected:
    """Tests for when all fields are collected and status is fields_complete."""

    def test_last_field_returns_fields_complete(self, full_aws):
        session_id = "test-session-complete"
        _create_session_item(
            full_aws["table"],
            session_id,
            current_field="person",
            fields_collected={
                "title": "Budget Memo",
                "memo_type": "incoming",
                "memo_date": "2024-03-15",
                "person_brought_in": None,
                "person_took_out": None,
            },
        )

        with _patch_transcribe_success("Jane Doe"):
            event = _make_event(session_id, {"audio_key": "uploads/test-audio.wav"})
            result = handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["field_name"] == "person"
        assert body["field_value"] == "Jane Doe"
        assert body["current_field"] is None
        assert body["next_prompt_audio_url"] is None
        assert body["fields_remaining"] == []
        assert body["status"] == "fields_complete"

    def test_person_field_stored_as_person_brought_in_for_incoming(self, full_aws):
        session_id = "test-session-incoming-person"
        _create_session_item(
            full_aws["table"],
            session_id,
            current_field="person",
            fields_collected={
                "title": "Budget Memo",
                "memo_type": "incoming",
                "memo_date": "2024-03-15",
                "person_brought_in": None,
                "person_took_out": None,
            },
        )

        with _patch_transcribe_success("Jane Doe"):
            event = _make_event(session_id, {"audio_key": "uploads/test-audio.wav"})
            handler(event, None)

        item = full_aws["table"].get_item(
            Key={"PK": f"VSESSION#{session_id}", "SK": "METADATA"}
        )["Item"]
        assert item["fields_collected"]["person_brought_in"] == "Jane Doe"
        assert item["fields_collected"]["person_took_out"] is None

    def test_person_field_stored_as_person_took_out_for_outgoing(self, full_aws):
        session_id = "test-session-outgoing-person"
        _create_session_item(
            full_aws["table"],
            session_id,
            current_field="person",
            fields_collected={
                "title": "Budget Memo",
                "memo_type": "outgoing",
                "memo_date": "2024-03-15",
                "person_brought_in": None,
                "person_took_out": None,
            },
        )

        with _patch_transcribe_success("John Smith"):
            event = _make_event(session_id, {"audio_key": "uploads/test-audio.wav"})
            handler(event, None)

        item = full_aws["table"].get_item(
            Key={"PK": f"VSESSION#{session_id}", "SK": "METADATA"}
        )["Item"]
        assert item["fields_collected"]["person_took_out"] == "John Smith"
        assert item["fields_collected"]["person_brought_in"] is None


class TestTranscriptionFailureRetry:
    """Tests for transcription failure with retry available."""

    def test_transcription_failure_first_retry_reprompts(self, full_aws):
        session_id = "test-session-retry"
        _create_session_item(full_aws["table"], session_id, current_field="title")

        with _patch_transcribe_failure():
            event = _make_event(session_id, {"audio_key": "uploads/test-audio.wav"})
            result = handler(event, None)

        assert result["statusCode"] == 422
        body = json.loads(result["body"])
        assert body["error"] == "Transcription failed"
        assert body["error_code"] == "TRANSCRIPTION_FAILED"
        assert body["retry_count"] == 1
        assert body["max_retries"] == 2
        assert "prompt_audio_url" in body

    def test_retry_count_incremented_in_dynamodb(self, full_aws):
        session_id = "test-session-retry-db"
        _create_session_item(full_aws["table"], session_id, current_field="title")

        with _patch_transcribe_failure():
            event = _make_event(session_id, {"audio_key": "uploads/test-audio.wav"})
            handler(event, None)

        item = full_aws["table"].get_item(
            Key={"PK": f"VSESSION#{session_id}", "SK": "METADATA"}
        )["Item"]
        assert int(item["retry_counts"]["title"]) == 1


class TestTranscriptionFailureExceeded:
    """Tests for transcription failure with retries exceeded."""

    def test_retries_exceeded_returns_field_retry_exceeded(self, full_aws):
        session_id = "test-session-exceeded"
        _create_session_item(
            full_aws["table"],
            session_id,
            current_field="title",
            retry_counts={"title": 1, "memo_type": 0, "memo_date": 0, "person": 0},
        )

        with _patch_transcribe_failure():
            event = _make_event(session_id, {"audio_key": "uploads/test-audio.wav"})
            result = handler(event, None)

        assert result["statusCode"] == 422
        body = json.loads(result["body"])
        assert body["error"] == "Maximum retries exceeded for field"
        assert body["error_code"] == "FIELD_RETRY_EXCEEDED"
        assert body["details"]["field"] == "title"
        assert "cancel" in body["details"]["options"]
        assert "manual_input" in body["details"]["options"]


class TestPersonFieldPrompt:
    """Tests for correct person field prompt based on memo_type."""

    def test_incoming_memo_uses_brought_in_prompt(self, full_aws):
        session_id = "test-session-person-incoming"
        _create_session_item(
            full_aws["table"],
            session_id,
            current_field="memo_date",
            fields_collected={
                "title": "Test Memo",
                "memo_type": "incoming",
                "memo_date": None,
                "person_brought_in": None,
                "person_took_out": None,
            },
        )

        polly_calls = []
        original_generate = None

        def capture_generate_prompt(prompt_text):
            polly_calls.append(prompt_text)
            return original_generate(prompt_text)

        with _patch_transcribe_success("March 15, 2024"):
            # Patch _generate_prompt_audio to capture the prompt text
            import backend.voice.submit_session_field as mod
            original_generate = mod._generate_prompt_audio

            with patch.object(mod, "_generate_prompt_audio", side_effect=capture_generate_prompt):
                event = _make_event(session_id, {"audio_key": "uploads/test-audio.wav"})
                result = handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["current_field"] == "person"

        # Verify the prompt used the "brought in" text
        assert len(polly_calls) > 0
        assert polly_calls[0] == FIELD_PROMPTS["person_brought_in"]

    def test_outgoing_memo_uses_took_out_prompt(self, full_aws):
        session_id = "test-session-person-outgoing"
        _create_session_item(
            full_aws["table"],
            session_id,
            current_field="memo_date",
            fields_collected={
                "title": "Test Memo",
                "memo_type": "outgoing",
                "memo_date": None,
                "person_brought_in": None,
                "person_took_out": None,
            },
        )

        polly_calls = []
        original_generate = None

        def capture_generate_prompt(prompt_text):
            polly_calls.append(prompt_text)
            return original_generate(prompt_text)

        with _patch_transcribe_success("March 15, 2024"):
            import backend.voice.submit_session_field as mod
            original_generate = mod._generate_prompt_audio

            with patch.object(mod, "_generate_prompt_audio", side_effect=capture_generate_prompt):
                event = _make_event(session_id, {"audio_key": "uploads/test-audio.wav"})
                result = handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["current_field"] == "person"

        # Verify the prompt used the "took out" text
        assert len(polly_calls) > 0
        assert polly_calls[0] == FIELD_PROMPTS["person_took_out"]


class TestSessionNotFound:
    """Tests for session not found."""

    def test_nonexistent_session_returns_404(self, full_aws):
        event = _make_event("nonexistent-session", {"audio_key": "uploads/test-audio.wav"})
        result = handler(event, None)

        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert body["error_code"] == "SESSION_NOT_FOUND"


class TestValidationErrors:
    """Tests for invalid/missing audio_key."""

    def test_missing_audio_key_returns_400(self, full_aws):
        session_id = "test-session-no-audio"
        _create_session_item(full_aws["table"], session_id)

        event = _make_event(session_id, {})
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"
        assert "audio_key" in body["error"]

    def test_empty_audio_key_returns_400(self, full_aws):
        session_id = "test-session-empty-audio"
        _create_session_item(full_aws["table"], session_id)

        event = _make_event(session_id, {"audio_key": ""})
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_whitespace_audio_key_returns_400(self, full_aws):
        session_id = "test-session-ws-audio"
        _create_session_item(full_aws["table"], session_id)

        event = _make_event(session_id, {"audio_key": "   "})
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_invalid_json_body_returns_400(self, full_aws):
        event = {
            "pathParameters": {"session_id": "test-session"},
            "body": "not-json",
        }
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_missing_session_id_returns_400(self, full_aws):
        event = {
            "pathParameters": {},
            "body": json.dumps({"audio_key": "uploads/test.wav"}),
        }
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_no_path_parameters_returns_400(self, full_aws):
        event = {
            "pathParameters": None,
            "body": json.dumps({"audio_key": "uploads/test.wav"}),
        }
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"
