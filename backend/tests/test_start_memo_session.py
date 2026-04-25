"""Unit tests for the start_memo_session Lambda handler."""

import json
import time
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from backend.shared.config import AUDIO_BUCKET, AWS_REGION, TABLE_NAME
from backend.voice.start_memo_session import FIELD_PROMPTS, handler


def _make_event(body=None):
    """Build a minimal API Gateway event with the given body dict."""
    return {"body": json.dumps(body) if body is not None else "{}"}


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
    """Mock all AWS services needed by start_memo_session."""
    with mock_aws():
        # Create DynamoDB table
        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        dynamodb.create_table(
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
            "s3": s3,
        }


class TestStartMemoSessionSuccess:
    """Tests for successful session creation."""

    def test_returns_201_with_session_fields(self, full_aws):
        event = _make_event({"user_id": "user-123"})
        result = handler(event, None)

        assert result["statusCode"] == 201

        body = json.loads(result["body"])
        assert "session_id" in body
        assert "prompt_audio_url" in body
        assert body["current_field"] == "title"
        assert body["fields_remaining"] == ["memo_type", "memo_date", "person"]

    def test_session_id_is_valid_uuid(self, full_aws):
        import uuid

        event = _make_event({"user_id": "user-123"})
        result = handler(event, None)
        body = json.loads(result["body"])

        # Should not raise
        uuid.UUID(body["session_id"])

    def test_prompt_audio_url_is_presigned(self, full_aws):
        event = _make_event({"user_id": "user-123"})
        result = handler(event, None)
        body = json.loads(result["body"])

        url = body["prompt_audio_url"]
        assert AUDIO_BUCKET in url
        assert "audio/polly/" in url
        assert "Signature" in url or "X-Amz-Signature" in url

    def test_dynamodb_item_created_with_correct_keys(self, full_aws):
        event = _make_event({"user_id": "user-456"})
        result = handler(event, None)
        body = json.loads(result["body"])
        session_id = body["session_id"]

        table = full_aws["dynamodb"].Table(TABLE_NAME)
        item = table.get_item(
            Key={"PK": f"VSESSION#{session_id}", "SK": "METADATA"}
        )["Item"]

        assert item["session_id"] == session_id
        assert item["user_id"] == "user-456"
        assert item["status"] == "in_progress"
        assert item["current_field"] == "title"
        assert item["entity_type"] == "VOICE_SESSION"

    def test_dynamodb_item_has_ttl(self, full_aws):
        now = int(time.time())
        event = _make_event({"user_id": "user-789"})
        result = handler(event, None)
        body = json.loads(result["body"])
        session_id = body["session_id"]

        table = full_aws["dynamodb"].Table(TABLE_NAME)
        item = table.get_item(
            Key={"PK": f"VSESSION#{session_id}", "SK": "METADATA"}
        )["Item"]

        ttl = int(item["ttl"])
        # TTL should be roughly now + 3600 (allow 5 seconds tolerance)
        assert ttl >= now + 3595
        assert ttl <= now + 3605

    def test_dynamodb_item_has_fields_collected(self, full_aws):
        event = _make_event({"user_id": "user-123"})
        result = handler(event, None)
        body = json.loads(result["body"])
        session_id = body["session_id"]

        table = full_aws["dynamodb"].Table(TABLE_NAME)
        item = table.get_item(
            Key={"PK": f"VSESSION#{session_id}", "SK": "METADATA"}
        )["Item"]

        fields = item["fields_collected"]
        assert fields["title"] is None
        assert fields["memo_type"] is None
        assert fields["memo_date"] is None
        assert fields["person_brought_in"] is None
        assert fields["person_took_out"] is None

    def test_dynamodb_item_has_retry_counts(self, full_aws):
        event = _make_event({"user_id": "user-123"})
        result = handler(event, None)
        body = json.loads(result["body"])
        session_id = body["session_id"]

        table = full_aws["dynamodb"].Table(TABLE_NAME)
        item = table.get_item(
            Key={"PK": f"VSESSION#{session_id}", "SK": "METADATA"}
        )["Item"]

        retry_counts = item["retry_counts"]
        assert retry_counts["title"] == 0
        assert retry_counts["memo_type"] == 0
        assert retry_counts["memo_date"] == 0
        assert retry_counts["person"] == 0

    def test_polly_audio_uploaded_to_s3(self, full_aws):
        event = _make_event({"user_id": "user-123"})
        handler(event, None)

        s3 = full_aws["s3"]
        objects = s3.list_objects_v2(Bucket=AUDIO_BUCKET, Prefix="audio/polly/")
        assert objects["KeyCount"] == 1
        key = objects["Contents"][0]["Key"]
        assert key.startswith("audio/polly/")
        assert key.endswith(".mp3")


class TestStartMemoSessionValidation:
    """Tests for request validation errors."""

    def test_missing_user_id_returns_400(self, full_aws):
        event = _make_event({})
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"
        assert "user_id" in body["error"]

    def test_empty_user_id_returns_400(self, full_aws):
        event = _make_event({"user_id": ""})
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_whitespace_user_id_returns_400(self, full_aws):
        event = _make_event({"user_id": "   "})
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_invalid_json_body_returns_400(self, full_aws):
        event = {"body": "not-json"}
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_none_body_returns_400(self, full_aws):
        event = {"body": None}
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"
