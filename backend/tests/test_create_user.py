"""Tests for the create_user Lambda handler.

Validates Requirements 8.2, 9.2, 9.5:
- 8.2: Superuser can create a new user account with provided details.
- 9.2: All required fields validated; email format checked.
- 9.5: Duplicate email registration prevented.
"""

import json

import pytest

from backend.user.create_user import handler


def _superuser_event(body: dict) -> dict:
    """Build an API Gateway event with superuser claims and a JSON body."""
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
        "body": json.dumps(body),
    }


def _regular_user_event(body: dict) -> dict:
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
        "body": json.dumps(body),
    }


VALID_USER_BODY = {
    "full_name": "Jane Doe",
    "email": "jane.doe@gov.example",
    "department": "Finance",
    "role": "regular_user",
    "phone_number": "+1234567890",
}


class TestCreateUserSuccess:
    """Successful user creation returns 201 with user data."""

    def test_creates_user_with_all_fields(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.create_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        event = _superuser_event(VALID_USER_BODY)
        result = handler(event, None)

        assert result["statusCode"] == 201
        body = json.loads(result["body"])
        assert body["full_name"] == "Jane Doe"
        assert body["email"] == "jane.doe@gov.example"
        assert body["department"] == "Finance"
        assert body["role"] == "regular_user"
        assert body["phone_number"] == "+1234567890"
        assert body["status"] == "active"
        assert "user_id" in body
        assert "created_at" in body

    def test_user_stored_in_dynamodb(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.create_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        event = _superuser_event(VALID_USER_BODY)
        result = handler(event, None)
        body = json.loads(result["body"])

        table = mock_all_aws["table"]
        db_item = table.get_item(
            Key={"PK": f"USER#{body['user_id']}", "SK": "PROFILE"}
        )["Item"]

        assert db_item["full_name"] == "Jane Doe"
        assert db_item["email"] == "jane.doe@gov.example"
        assert db_item["entity_type"] == "USER"
        assert db_item["GSI1PK"] == "EMAIL#jane.doe@gov.example"
        assert db_item["GSI1SK"] == "PROFILE"
        assert db_item["GSI2PK"] == "ROLE#regular_user"
        assert db_item["GSI2SK"] == f"USER#{body['user_id']}"

    def test_creates_superuser_role(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.create_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        body = {**VALID_USER_BODY, "role": "superuser", "email": "admin@gov.example"}
        event = _superuser_event(body)
        result = handler(event, None)

        assert result["statusCode"] == 201
        resp_body = json.loads(result["body"])
        assert resp_body["role"] == "superuser"


class TestCreateUserValidation:
    """Validation errors return 400 with VALIDATION_ERROR code."""

    @pytest.mark.parametrize(
        "missing_field",
        ["full_name", "email", "department", "role", "phone_number"],
    )
    def test_missing_required_field(self, mock_all_aws, monkeypatch, missing_field):
        monkeypatch.setattr(
            "backend.user.create_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        body = {**VALID_USER_BODY}
        del body[missing_field]
        event = _superuser_event(body)
        result = handler(event, None)

        assert result["statusCode"] == 400
        resp = json.loads(result["body"])
        assert resp["error_code"] == "VALIDATION_ERROR"
        assert missing_field in resp["details"]["missing_fields"]

    def test_invalid_email_format(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.create_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        body = {**VALID_USER_BODY, "email": "not-an-email"}
        event = _superuser_event(body)
        result = handler(event, None)

        assert result["statusCode"] == 400
        resp = json.loads(result["body"])
        assert resp["error_code"] == "VALIDATION_ERROR"
        assert "email" in resp["details"]["invalid_fields"]

    def test_invalid_role(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.create_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        body = {**VALID_USER_BODY, "role": "admin"}
        event = _superuser_event(body)
        result = handler(event, None)

        assert result["statusCode"] == 400
        resp = json.loads(result["body"])
        assert resp["error_code"] == "VALIDATION_ERROR"
        assert "role" in resp["details"]["invalid_fields"]

    def test_invalid_json_body(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.create_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        event = _superuser_event({})
        event["body"] = "not-json"
        result = handler(event, None)

        assert result["statusCode"] == 400
        resp = json.loads(result["body"])
        assert resp["error_code"] == "VALIDATION_ERROR"

    def test_empty_string_fields_treated_as_missing(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.create_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        body = {**VALID_USER_BODY, "full_name": "  "}
        event = _superuser_event(body)
        result = handler(event, None)

        assert result["statusCode"] == 400
        resp = json.loads(result["body"])
        assert "full_name" in resp["details"]["missing_fields"]


class TestCreateUserDuplicateEmail:
    """Duplicate email returns 409 with DUPLICATE_EMAIL code."""

    def test_duplicate_email_rejected(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.create_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        event = _superuser_event(VALID_USER_BODY)

        # First creation succeeds
        result1 = handler(event, None)
        assert result1["statusCode"] == 201

        # Second creation with same email fails
        result2 = handler(event, None)
        assert result2["statusCode"] == 409
        resp = json.loads(result2["body"])
        assert resp["error_code"] == "DUPLICATE_EMAIL"
        assert "already registered" in resp["error"].lower()


class TestCreateUserAuthorization:
    """Non-superuser access returns 403 FORBIDDEN."""

    def test_regular_user_denied(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.create_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        event = _regular_user_event(VALID_USER_BODY)
        result = handler(event, None)

        assert result["statusCode"] == 403
        resp = json.loads(result["body"])
        assert resp["error_code"] == "FORBIDDEN"

    def test_missing_auth_claims_denied(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.create_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        event = {"requestContext": {}, "body": json.dumps(VALID_USER_BODY)}
        result = handler(event, None)

        assert result["statusCode"] == 403
        resp = json.loads(result["body"])
        assert resp["error_code"] == "FORBIDDEN"
