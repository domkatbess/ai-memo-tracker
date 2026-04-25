"""Tests for the enroll_voice Lambda handler.

Validates Requirements 7.4, 8.4:
- 7.4: New user voice sample stored in S3 for future verification.
- 8.4: Superuser prompted to capture new user's voice sample for enrollment.
"""

import base64
import json

import boto3
import pytest

from backend.shared.config import AWS_REGION
from backend.user.create_user import handler as create_user_handler
from backend.user.enroll_voice import handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_AUDIO = b"\x52\x49\x46\x46" + b"\x00" * 20  # minimal WAV-like bytes
FAKE_AUDIO_B64 = base64.b64encode(FAKE_AUDIO).decode()

BIOMETRIC_BUCKET = "test-biometric-bucket"


def _superuser_event(path_id: str, body: dict | None = None) -> dict:
    """Build an API Gateway event with superuser claims."""
    return {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "cognito-sub-admin",
                    "custom:user_id": "admin-001",
                    "custom:role": "superuser",
                    "name": "Admin User",
                }
            }
        },
        "pathParameters": {"id": path_id},
        "body": json.dumps(body) if body is not None else None,
    }


def _regular_user_event(path_id: str, body: dict | None = None) -> dict:
    """Build an API Gateway event with regular_user claims."""
    return {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "cognito-sub-user",
                    "custom:user_id": "user-001",
                    "custom:role": "regular_user",
                    "name": "Regular User",
                }
            }
        },
        "pathParameters": {"id": path_id},
        "body": json.dumps(body) if body is not None else None,
    }


def _create_test_user(cognito_pool_id: str, monkeypatch) -> str:
    """Create a user via create_user handler and return the user_id."""
    monkeypatch.setattr(
        "backend.user.create_user.COGNITO_USER_POOL_ID",
        cognito_pool_id,
    )
    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "cognito-sub-admin",
                    "custom:user_id": "admin-001",
                    "custom:role": "superuser",
                    "name": "Admin User",
                }
            }
        },
        "body": json.dumps(
            {
                "full_name": "Jane Doe",
                "email": "jane.doe@gov.example",
                "department": "Finance",
                "role": "regular_user",
                "phone_number": "+1234567890",
            }
        ),
    }
    result = create_user_handler(event, None)
    assert result["statusCode"] == 201
    return json.loads(result["body"])["user_id"]


@pytest.fixture()
def enroll_env(mock_all_aws, monkeypatch):
    """Set up S3 bucket and create a test user."""
    # Patch config values used by enroll_voice
    monkeypatch.setattr(
        "backend.user.enroll_voice.BIOMETRIC_BUCKET", BIOMETRIC_BUCKET
    )

    # Create S3 bucket
    s3_client = boto3.client("s3", region_name=AWS_REGION)
    s3_client.create_bucket(Bucket=BIOMETRIC_BUCKET)

    # Create a test user
    user_id = _create_test_user(mock_all_aws["cognito_pool_id"], monkeypatch)

    return {
        **mock_all_aws,
        "user_id": user_id,
        "s3_client": s3_client,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEnrollVoiceSuccess:
    """Successful voice enrollment returns 200 with confirmation."""

    def test_enrolls_voice_returns_200(self, enroll_env):
        event = _superuser_event(
            enroll_env["user_id"], {"audio": FAKE_AUDIO_B64}
        )
        result = handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["user_id"] == enroll_env["user_id"]
        assert body["voice_sample_s3_key"] == f"biometric/{enroll_env['user_id']}/voice_enrollment.wav"
        assert "enrolled" in body["message"].lower()

    def test_audio_uploaded_to_s3(self, enroll_env):
        event = _superuser_event(
            enroll_env["user_id"], {"audio": FAKE_AUDIO_B64}
        )
        handler(event, None)

        s3_key = f"biometric/{enroll_env['user_id']}/voice_enrollment.wav"
        obj = enroll_env["s3_client"].get_object(
            Bucket=BIOMETRIC_BUCKET, Key=s3_key
        )
        assert obj["Body"].read() == FAKE_AUDIO

    def test_embedding_stored_in_s3(self, enroll_env):
        event = _superuser_event(
            enroll_env["user_id"], {"audio": FAKE_AUDIO_B64}
        )
        handler(event, None)

        embedding_key = f"biometric/{enroll_env['user_id']}/voice_embedding.json"
        obj = enroll_env["s3_client"].get_object(
            Bucket=BIOMETRIC_BUCKET, Key=embedding_key
        )
        embedding = json.loads(obj["Body"].read().decode())
        assert isinstance(embedding, list)
        assert len(embedding) == 128
        assert all(isinstance(v, float) for v in embedding)

    def test_user_record_updated_in_dynamodb(self, enroll_env):
        event = _superuser_event(
            enroll_env["user_id"], {"audio": FAKE_AUDIO_B64}
        )
        handler(event, None)

        table = enroll_env["table"]
        item = table.get_item(
            Key={
                "PK": f"USER#{enroll_env['user_id']}",
                "SK": "PROFILE",
            }
        )["Item"]
        assert item["voice_sample_s3_key"] == f"biometric/{enroll_env['user_id']}/voice_enrollment.wav"


class TestEnrollVoiceValidation:
    """Missing audio returns 400."""

    def test_missing_audio_field(self, enroll_env):
        event = _superuser_event(enroll_env["user_id"], {})
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"
        assert "audio" in body["error"].lower()

    def test_null_body(self, enroll_env):
        event = _superuser_event(enroll_env["user_id"])
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"


class TestEnrollVoiceUserNotFound:
    """Non-existent user returns 404."""

    def test_user_not_found(self, enroll_env):
        event = _superuser_event(
            "nonexistent-user-id", {"audio": FAKE_AUDIO_B64}
        )
        result = handler(event, None)

        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert body["error_code"] == "NOT_FOUND"


class TestEnrollVoiceAuthorization:
    """Non-superuser access returns 403."""

    def test_regular_user_denied(self, enroll_env):
        event = _regular_user_event(
            enroll_env["user_id"], {"audio": FAKE_AUDIO_B64}
        )
        result = handler(event, None)

        assert result["statusCode"] == 403
        body = json.loads(result["body"])
        assert body["error_code"] == "FORBIDDEN"
