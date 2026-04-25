"""Unit tests for the review_memo_session Lambda handler."""

import json
import time

import boto3
import pytest
from moto import mock_aws

from backend.shared.config import AUDIO_BUCKET, AWS_REGION, TABLE_NAME
from backend.voice.review_memo_session import REVIEW_TEMPLATE, handler
from backend.voice.start_memo_session import FIELD_ORDER


def _make_event(session_id):
    """Build a minimal API Gateway event with path params for review."""
    return {
        "pathParameters": {"session_id": session_id},
    }


def _create_complete_incoming_session(table, session_id, title="Budget Allocation Q3",
                                       memo_date="2024-03-15", person="Jane Doe"):
    """Insert a complete incoming voice session into DynamoDB."""
    item = {
        "PK": f"VSESSION#{session_id}",
        "SK": "METADATA",
        "session_id": session_id,
        "user_id": "user-123",
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


def _create_complete_outgoing_session(table, session_id, title="Outgoing Report",
                                       memo_date="2024-06-01", person="John Smith"):
    """Insert a complete outgoing voice session into DynamoDB."""
    item = {
        "PK": f"VSESSION#{session_id}",
        "SK": "METADATA",
        "session_id": session_id,
        "user_id": "user-456",
        "status": "fields_complete",
        "current_field": None,
        "fields_collected": {
            "title": title,
            "memo_type": "outgoing",
            "memo_date": memo_date,
            "person_brought_in": None,
            "person_took_out": person,
        },
        "field_order": FIELD_ORDER,
        "retry_counts": {"title": 0, "memo_type": 0, "memo_date": 0, "person": 0},
        "ttl": int(time.time()) + 3600,
        "entity_type": "VOICE_SESSION",
    }
    table.put_item(Item=item)
    return item


def _create_incomplete_session(table, session_id, fields_collected=None):
    """Insert an incomplete voice session into DynamoDB."""
    if fields_collected is None:
        fields_collected = {
            "title": "Some Title",
            "memo_type": "incoming",
            "memo_date": None,
            "person_brought_in": None,
            "person_took_out": None,
        }
    item = {
        "PK": f"VSESSION#{session_id}",
        "SK": "METADATA",
        "session_id": session_id,
        "user_id": "user-123",
        "status": "in_progress",
        "current_field": "memo_date",
        "fields_collected": fields_collected,
        "field_order": FIELD_ORDER,
        "retry_counts": {"title": 0, "memo_type": 0, "memo_date": 0, "person": 0},
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
    """Mock all AWS services needed by review_memo_session."""
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

        # Create S3 bucket
        s3 = boto3.client("s3", region_name=AWS_REGION)
        s3.create_bucket(Bucket=AUDIO_BUCKET)

        yield {
            "dynamodb": dynamodb,
            "table": table,
            "s3": s3,
        }


class TestReviewSuccess:
    """Tests for successful review returning 200 with audio URL and collected data."""

    def test_incoming_review_returns_200_with_audio_url_and_data(self, full_aws):
        session_id = "review-incoming-1"
        _create_complete_incoming_session(full_aws["table"], session_id)

        result = handler(_make_event(session_id), None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "review_audio_url" in body
        assert body["review_audio_url"]  # non-empty
        assert body["collected_data"]["title"] == "Budget Allocation Q3"
        assert body["collected_data"]["memo_type"] == "incoming"
        assert body["collected_data"]["memo_date"] == "2024-03-15"
        assert body["collected_data"]["person_brought_in"] == "Jane Doe"
        assert body["collected_data"]["person_took_out"] is None

    def test_outgoing_review_returns_200_with_correct_data(self, full_aws):
        session_id = "review-outgoing-1"
        _create_complete_outgoing_session(full_aws["table"], session_id)

        result = handler(_make_event(session_id), None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "review_audio_url" in body
        assert body["collected_data"]["title"] == "Outgoing Report"
        assert body["collected_data"]["memo_type"] == "outgoing"
        assert body["collected_data"]["memo_date"] == "2024-06-01"
        assert body["collected_data"]["person_brought_in"] is None
        assert body["collected_data"]["person_took_out"] == "John Smith"

    def test_review_audio_url_is_presigned(self, full_aws):
        session_id = "review-presigned"
        _create_complete_incoming_session(full_aws["table"], session_id)

        result = handler(_make_event(session_id), None)
        body = json.loads(result["body"])

        url = body["review_audio_url"]
        assert AUDIO_BUCKET in url
        assert "audio/polly/" in url
        assert "Signature" in url or "X-Amz-Signature" in url

    def test_polly_audio_uploaded_to_s3(self, full_aws):
        session_id = "review-s3-check"
        _create_complete_incoming_session(full_aws["table"], session_id)

        handler(_make_event(session_id), None)

        objects = full_aws["s3"].list_objects_v2(Bucket=AUDIO_BUCKET, Prefix="audio/polly/")
        assert objects["KeyCount"] == 1
        key = objects["Contents"][0]["Key"]
        assert key.startswith("audio/polly/")
        assert key.endswith(".mp3")


class TestReviewTextContent:
    """Tests that the review text contains all field values."""

    def test_incoming_review_text_contains_all_fields(self, full_aws):
        """Verify the review template is populated with all incoming session fields."""
        from backend.voice.review_memo_session import _format_review_text

        fields = {
            "title": "Budget Allocation Q3",
            "memo_type": "incoming",
            "memo_date": "2024-03-15",
            "person_brought_in": "Jane Doe",
            "person_took_out": None,
        }
        text = _format_review_text(fields)

        assert "Budget Allocation Q3" in text
        assert "incoming" in text
        assert "2024-03-15" in text
        assert "Jane Doe" in text
        assert "Person who brought in" in text
        assert "Would you like to save this memo?" in text

    def test_outgoing_review_text_contains_all_fields(self, full_aws):
        """Verify the review template is populated with all outgoing session fields."""
        from backend.voice.review_memo_session import _format_review_text

        fields = {
            "title": "Outgoing Report",
            "memo_type": "outgoing",
            "memo_date": "2024-06-01",
            "person_brought_in": None,
            "person_took_out": "John Smith",
        }
        text = _format_review_text(fields)

        assert "Outgoing Report" in text
        assert "outgoing" in text
        assert "2024-06-01" in text
        assert "John Smith" in text
        assert "Person who took out" in text
        assert "Would you like to save this memo?" in text

    def test_incoming_uses_person_who_brought_in(self, full_aws):
        """Incoming memo review uses 'Person who brought in' label."""
        from backend.voice.review_memo_session import _format_review_text

        fields = {
            "title": "Test",
            "memo_type": "incoming",
            "memo_date": "2024-01-01",
            "person_brought_in": "Alice",
            "person_took_out": None,
        }
        text = _format_review_text(fields)
        assert "Person who brought in: Alice" in text

    def test_outgoing_uses_person_who_took_out(self, full_aws):
        """Outgoing memo review uses 'Person who took out' label."""
        from backend.voice.review_memo_session import _format_review_text

        fields = {
            "title": "Test",
            "memo_type": "outgoing",
            "memo_date": "2024-01-01",
            "person_brought_in": None,
            "person_took_out": "Bob",
        }
        text = _format_review_text(fields)
        assert "Person who took out: Bob" in text


class TestSessionNotFound:
    """Tests for session not found."""

    def test_nonexistent_session_returns_404(self, full_aws):
        result = handler(_make_event("nonexistent-session"), None)

        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert body["error_code"] == "SESSION_NOT_FOUND"
        assert "not found" in body["error"].lower()


class TestSessionIncomplete:
    """Tests for incomplete session returning 400 SESSION_INCOMPLETE."""

    def test_missing_memo_date_returns_400(self, full_aws):
        session_id = "review-incomplete-date"
        _create_incomplete_session(full_aws["table"], session_id, fields_collected={
            "title": "Some Title",
            "memo_type": "incoming",
            "memo_date": None,
            "person_brought_in": "Jane",
            "person_took_out": None,
        })

        result = handler(_make_event(session_id), None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "SESSION_INCOMPLETE"

    def test_missing_title_returns_400(self, full_aws):
        session_id = "review-incomplete-title"
        _create_incomplete_session(full_aws["table"], session_id, fields_collected={
            "title": None,
            "memo_type": "incoming",
            "memo_date": "2024-03-15",
            "person_brought_in": "Jane",
            "person_took_out": None,
        })

        result = handler(_make_event(session_id), None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "SESSION_INCOMPLETE"

    def test_missing_person_for_incoming_returns_400(self, full_aws):
        session_id = "review-incomplete-person-in"
        _create_incomplete_session(full_aws["table"], session_id, fields_collected={
            "title": "Some Title",
            "memo_type": "incoming",
            "memo_date": "2024-03-15",
            "person_brought_in": None,
            "person_took_out": None,
        })

        result = handler(_make_event(session_id), None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "SESSION_INCOMPLETE"

    def test_missing_person_for_outgoing_returns_400(self, full_aws):
        session_id = "review-incomplete-person-out"
        _create_incomplete_session(full_aws["table"], session_id, fields_collected={
            "title": "Some Title",
            "memo_type": "outgoing",
            "memo_date": "2024-03-15",
            "person_brought_in": None,
            "person_took_out": None,
        })

        result = handler(_make_event(session_id), None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "SESSION_INCOMPLETE"

    def test_missing_memo_type_returns_400(self, full_aws):
        session_id = "review-incomplete-type"
        _create_incomplete_session(full_aws["table"], session_id, fields_collected={
            "title": "Some Title",
            "memo_type": None,
            "memo_date": "2024-03-15",
            "person_brought_in": None,
            "person_took_out": None,
        })

        result = handler(_make_event(session_id), None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "SESSION_INCOMPLETE"


class TestValidationErrors:
    """Tests for missing session_id and other validation errors."""

    def test_missing_session_id_returns_400(self, full_aws):
        event = {"pathParameters": {}}
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_no_path_parameters_returns_400(self, full_aws):
        event = {"pathParameters": None}
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_missing_path_parameters_key_returns_400(self, full_aws):
        event = {}
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"
