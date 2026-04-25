"""Tests for the deactivate_user Lambda handler.

Validates Requirements 8.5:
- 8.5: Superuser can deactivate a user account, revoking sessions.
"""

import json

from backend.user.create_user import handler as create_handler
from backend.user.deactivate_user import handler as deactivate_handler


def _superuser_event(body: dict = None, path_params: dict = None) -> dict:
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
        "body": json.dumps(body) if body else None,
    }
    if path_params:
        event["pathParameters"] = path_params
    return event


def _regular_user_event(path_params: dict = None) -> dict:
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
        "body": None,
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
    event = _superuser_event(body=VALID_USER_BODY)
    result = create_handler(event, None)
    assert result["statusCode"] == 201
    return json.loads(result["body"])


class TestDeactivateUserSuccess:
    """Successful user deactivation returns 200 with status deactivated."""

    def test_deactivates_active_user(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.deactivate_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        user = _create_user(mock_all_aws, monkeypatch)
        user_id = user["user_id"]

        event = _superuser_event(path_params={"id": user_id})
        result = deactivate_handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["status"] == "deactivated"
        assert body["user_id"] == user_id
        assert body["full_name"] == "Jane Doe"
        assert body["email"] == "jane.doe@gov.example"

    def test_user_status_updated_in_dynamodb(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.deactivate_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        user = _create_user(mock_all_aws, monkeypatch)
        user_id = user["user_id"]

        event = _superuser_event(path_params={"id": user_id})
        deactivate_handler(event, None)

        table = mock_all_aws["table"]
        db_item = table.get_item(
            Key={"PK": f"USER#{user_id}", "SK": "PROFILE"}
        )["Item"]
        assert db_item["status"] == "deactivated"


class TestDeactivateUserAuditLog:
    """Audit log entry created on deactivation."""

    def test_audit_log_created(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.deactivate_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        user = _create_user(mock_all_aws, monkeypatch)
        user_id = user["user_id"]

        event = _superuser_event(path_params={"id": user_id})
        deactivate_handler(event, None)

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
        assert audit["action"] == "DEACTIVATE"
        assert audit["modified_by"] == "admin-001"
        assert audit["modified_by_name"] == "Admin User"
        assert audit["entity_type"] == "USER_AUDIT"
        assert "timestamp" in audit
        assert audit["changes"]["status"]["old"] == "active"
        assert audit["changes"]["status"]["new"] == "deactivated"


class TestDeactivateUserNotFound:
    """User not found returns 404."""

    def test_nonexistent_user(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.deactivate_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        event = _superuser_event(path_params={"id": "nonexistent-id"})
        result = deactivate_handler(event, None)

        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert body["error_code"] == "NOT_FOUND"


class TestDeactivateUserAuthorization:
    """Non-superuser access returns 403."""

    def test_regular_user_denied(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.deactivate_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        event = _regular_user_event(path_params={"id": "some-id"})
        result = deactivate_handler(event, None)

        assert result["statusCode"] == 403
        body = json.loads(result["body"])
        assert body["error_code"] == "FORBIDDEN"


class TestDeactivateAlreadyDeactivatedUser:
    """Deactivating an already deactivated user still succeeds."""

    def test_already_deactivated_user_succeeds(self, mock_all_aws, monkeypatch):
        monkeypatch.setattr(
            "backend.user.deactivate_user.COGNITO_USER_POOL_ID",
            mock_all_aws["cognito_pool_id"],
        )
        user = _create_user(mock_all_aws, monkeypatch)
        user_id = user["user_id"]

        # Deactivate once
        event = _superuser_event(path_params={"id": user_id})
        result1 = deactivate_handler(event, None)
        assert result1["statusCode"] == 200

        # Deactivate again
        result2 = deactivate_handler(event, None)
        assert result2["statusCode"] == 200
        body = json.loads(result2["body"])
        assert body["status"] == "deactivated"
