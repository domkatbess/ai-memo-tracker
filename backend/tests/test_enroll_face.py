"""Tests for the enroll_face Lambda handler.

Validates Requirements 6.4, 8.3:
- 6.4: New user face image stored in S3 and indexed in Rekognition collection.
- 8.3: Superuser prompted to capture new user's facial image for enrollment.
"""

import base64
import json
from unittest.mock import MagicMock, patch

import boto3
import pytest

from backend.shared.config import AWS_REGION
from backend.user.create_user import handler as create_user_handler
from backend.user.enroll_face import handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_IMAGE = b"\xff\xd8\xff\xe0" + b"\x00" * 20  # minimal JPEG-like bytes
FAKE_IMAGE_B64 = base64.b64encode(FAKE_IMAGE).decode()

BIOMETRIC_BUCKET = "test-biometric-bucket"
REKOGNITION_COLLECTION = "test-face-collection"


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
    """Set up S3 bucket, mock Rekognition, and create a test user."""
    # Patch config values used by enroll_face
    monkeypatch.setattr(
        "backend.user.enroll_face.BIOMETRIC_BUCKET", BIOMETRIC_BUCKET
    )
    monkeypatch.setattr(
        "backend.user.enroll_face.REKOGNITION_COLLECTION_ID",
        REKOGNITION_COLLECTION,
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


class TestEnrollFaceSuccess:
    """Successful face enrollment returns 200 with confirmation."""

    @patch("backend.user.enroll_face.boto3")
    def test_enrolls_face_returns_200(self, mock_boto3, enroll_env):
        # Set up mock: boto3.client("rekognition") returns a mock,
        # but boto3.client("s3") should use the real moto client.
        real_s3 = enroll_env["s3_client"]
        mock_rek = MagicMock()
        mock_rek.index_faces.return_value = {
            "FaceRecords": [{"Face": {"FaceId": "abc-123"}}]
        }

        def side_effect(service, **kwargs):
            if service == "rekognition":
                return mock_rek
            if service == "s3":
                return real_s3
            return MagicMock()

        mock_boto3.client.side_effect = side_effect
        # get_table uses boto3.resource — delegate to real moto
        mock_boto3.resource.side_effect = boto3.resource

        event = _superuser_event(
            enroll_env["user_id"], {"image": FAKE_IMAGE_B64}
        )
        result = handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["user_id"] == enroll_env["user_id"]
        assert body["face_image_s3_key"] == f"biometric/{enroll_env['user_id']}/face.jpg"
        assert "enrolled" in body["message"].lower()

        # Verify Rekognition was called correctly
        mock_rek.index_faces.assert_called_once_with(
            CollectionId=REKOGNITION_COLLECTION,
            Image={"Bytes": FAKE_IMAGE},
            ExternalImageId=enroll_env["user_id"],
            DetectionAttributes=["DEFAULT"],
        )

    @patch("backend.user.enroll_face.boto3")
    def test_image_uploaded_to_s3(self, mock_boto3, enroll_env):
        real_s3 = enroll_env["s3_client"]
        mock_rek = MagicMock()
        mock_rek.index_faces.return_value = {
            "FaceRecords": [{"Face": {"FaceId": "abc-123"}}]
        }

        def side_effect(service, **kwargs):
            if service == "rekognition":
                return mock_rek
            if service == "s3":
                return real_s3
            return MagicMock()

        mock_boto3.client.side_effect = side_effect
        mock_boto3.resource.side_effect = boto3.resource

        event = _superuser_event(
            enroll_env["user_id"], {"image": FAKE_IMAGE_B64}
        )
        handler(event, None)

        s3_key = f"biometric/{enroll_env['user_id']}/face.jpg"
        obj = real_s3.get_object(Bucket=BIOMETRIC_BUCKET, Key=s3_key)
        assert obj["Body"].read() == FAKE_IMAGE

    @patch("backend.user.enroll_face.boto3")
    def test_user_record_updated_in_dynamodb(self, mock_boto3, enroll_env):
        real_s3 = enroll_env["s3_client"]
        mock_rek = MagicMock()
        mock_rek.index_faces.return_value = {
            "FaceRecords": [{"Face": {"FaceId": "abc-123"}}]
        }

        def side_effect(service, **kwargs):
            if service == "rekognition":
                return mock_rek
            if service == "s3":
                return real_s3
            return MagicMock()

        mock_boto3.client.side_effect = side_effect
        mock_boto3.resource.side_effect = boto3.resource

        event = _superuser_event(
            enroll_env["user_id"], {"image": FAKE_IMAGE_B64}
        )
        handler(event, None)

        table = enroll_env["table"]
        item = table.get_item(
            Key={
                "PK": f"USER#{enroll_env['user_id']}",
                "SK": "PROFILE",
            }
        )["Item"]
        assert item["face_image_s3_key"] == f"biometric/{enroll_env['user_id']}/face.jpg"


class TestEnrollFaceValidation:
    """Missing image returns 400."""

    def test_missing_image_field(self, enroll_env):
        event = _superuser_event(enroll_env["user_id"], {})
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"
        assert "image" in body["error"].lower()

    def test_null_body(self, enroll_env):
        event = _superuser_event(enroll_env["user_id"])
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"


class TestEnrollFaceUserNotFound:
    """Non-existent user returns 404."""

    def test_user_not_found(self, enroll_env):
        event = _superuser_event(
            "nonexistent-user-id", {"image": FAKE_IMAGE_B64}
        )
        result = handler(event, None)

        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert body["error_code"] == "NOT_FOUND"


class TestEnrollFaceAuthorization:
    """Non-superuser access returns 403."""

    def test_regular_user_denied(self, enroll_env):
        event = _regular_user_event(
            enroll_env["user_id"], {"image": FAKE_IMAGE_B64}
        )
        result = handler(event, None)

        assert result["statusCode"] == 403
        body = json.loads(result["body"])
        assert body["error_code"] == "FORBIDDEN"
