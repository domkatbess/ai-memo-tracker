"""Tests for the update_user Lambda handler.

Validates Requirements 8.7:
- 8.7: Superuser can modify a user account with audit logging.
"""

import json

import pytest

from backend.user.create_user import handler as create_handler
from backend.user.update_user import handler as update_handler


def _superuser_event(body: dict, path_params: dict = None) -> dict:
    """Build an API Gateway event with superuser claims."""
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
        "body": json.dumps(body),
    }
    if path_params:
        event["pathParameters"] = path_params
    return event


def _regular_user_event(body: dict, path_params: dict = None) -> dict:
    """Build an API Gateway event with regular_user claims."""
    event = {
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
    if path_params:
        event["pathParameters"] = path_params
    return event


VALID_USER_BODY = {
    "full_name": "Jane Doe",
    "email": "jane.doe@gov.example",
    "department": "Finance",
    "role": "regular_user",
    "phone_number": "+1234567890",
}


def _create_user(mock_all_aws, monkeypatch):
    """Helper to create a user and return the response body."""
    monkeypatch.setattr(
        "backend.user.create_user.COGNITO_USER_POOL_ID",
        mock_all_aws["cognito_pool_id"],
    )
    event = _superuser_event(VALID_USER_BODY)
    result = create_handler(event, None)
    assert result["statusCode"] == 201
    return json.loads(result["body"])


class TestUpdateUserSuccess:
    """Successful user update returns 200 with updated data."""

    def test_update_full_name(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.update_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        user = _create_user(mock_all_aws, monkeypatch)
        user_id = user["user_id"]

        event = _superuser_event(
            {"full_name": "Jane Smith"},
            path_params={"id": user_id},
        )
        result = update_handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["full_name"] == "Jane Smith"
        assert body["email"] == "jane.doe@gov.example"

    def test_update_department(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.update_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        user = _create_user(mock_all_aws, monkeypatch)
        user_id = user["user_id"]

        event = _superuser_event(
            {"department": "Engineering"},
            path_params={"id": user_id},
        )
        result = update_handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["department"] == "Engineering"

    def test_update_multiple_fields(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.update_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        user = _create_user(mock_all_aws, monkeypatch)
        user_id = user["user_id"]

        event = _superuser_event(
            {"full_name": "Jane Smith", "phone_number": "+9876543210"},
            path_params={"id": user_id},
        )
        result = update_handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["full_name"] == "Jane Smith"
        assert body["phone_number"] == "+9876543210"

    def test_update_role(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.update_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        user = _create_user(mock_all_aws, monkeypatch)
        user_id = user["user_id"]

        event = _superuser_event(
            {"role": "superuser"},
            path_params={"id": user_id},
        )
        result = update_handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["role"] == "superuser"

    def test_update_email(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.update_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        user = _create_user(mock_all_aws, monkeypatch)
        user_id = user["user_id"]

        event = _superuser_event(
            {"email": "jane.new@gov.example"},
            path_params={"id": user_id},
        )
        result = update_handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["email"] == "jane.new@gov.example"


class TestUpdateUserAuditLog:
    """Audit log entry created on update."""

    def test_audit_log_created(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.update_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        user = _create_user(mock_all_aws, monkeypatch)
        user_id = user["user_id"]

        event = _superuser_event(
            {"full_name": "Jane Smith"},
            path_params={"id": user_id},
        )
        update_handler(event, None)

        # Query audit log entries
        table = mock_all_aws["table"]
        response = table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
            ExpressionAttributeValues={
                ":pk": f"USER#{user_id}",
                ":sk_prefix": "AUDIT#",
            },
        )
        items = response["Items"]
        assert len(items) == 1

        audit = items[0]
        assert audit["user_id"] == user_id
        assert audit["action"] == "UPDATE"
        assert audit["modified_by"] == "admin-001"
        assert audit["modified_by_name"] == "Admin User"
        assert audit["entity_type"] == "USER_AUDIT"
        assert "timestamp" in audit
        assert "changes" in audit
        assert audit["changes"]["full_name"]["old"] == "Jane Doe"
        assert audit["changes"]["full_name"]["new"] == "Jane Smith"


class TestUpdateUserNotFound:
    """User not found returns 404."""

    def test_nonexistent_user(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.update_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        event = _superuser_event(
            {"full_name": "Nobody"},
            path_params={"id": "nonexistent-id"},
        )
        result = update_handler(event, None)

        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert body["error_code"] == "NOT_FOUND"


class TestUpdateUserAuthorization:
    """Non-superuser access returns 403."""

    def test_regular_user_denied(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.update_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        event = _regular_user_event(
            {"full_name": "Hacker"},
            path_params={"id": "some-id"},
        )
        result = update_handler(event, None)

        assert result["statusCode"] == 403
        body = json.loads(result["body"])
        assert body["error_code"] == "FORBIDDEN"


class TestUpdateUserEmailValidation:
    """Email format validation on update."""

    def test_invalid_email_rejected(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.update_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        user = _create_user(mock_all_aws, monkeypatch)
        user_id = user["user_id"]

        event = _superuser_event(
            {"email": "not-an-email"},
            path_params={"id": user_id},
        )
        result = update_handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"
        assert "email" in body["details"]["invalid_fields"]


class TestUpdateUserDuplicateEmail:
    """Duplicate email check on update."""

    def test_duplicate_email_rejected(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.update_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        # Create first user
        _create_user(mock_all_aws, monkeypatch)

        # Create second user with different email
        monkeypatch.setattr(
            "backend.user.create_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        second_body = {**VALID_USER_BODY, "email": "second@gov.example"}
        event2 = _superuser_event(second_body)
        result2 = create_handler(event2, None)
        assert result2["statusCode"] == 201
        second_user = json.loads(result2["body"])

        # Try to update second user's email to first user's email
        event = _superuser_event(
            {"email": "jane.doe@gov.example"},
            path_params={"id": second_user["user_id"]},
        )
        result = update_handler(event, None)

        assert result["statusCode"] == 409
        body = json.loads(result["body"])
        assert body["error_code"] == "DUPLICATE_EMAIL"


class TestUpdateUserInvalidRole:
    """Invalid role on update."""

    def test_invalid_role_rejected(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.update_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        user = _create_user(mock_all_aws, monkeypatch)
        user_id = user["user_id"]

        event = _superuser_event(
            {"role": "admin"},
            path_params={"id": user_id},
        )
        result = update_handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"
        assert "role" in body["details"]["invalid_fields"]
