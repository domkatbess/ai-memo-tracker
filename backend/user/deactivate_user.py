"""Lambda handler for deactivating a user account.

Only superusers may deactivate users. The handler sets the user status to
"deactivated" in DynamoDB, revokes all active Cognito sessions, and creates
an audit log entry.

Validates: Requirements 8.5
"""

import json
from datetime import datetime, timezone

import boto3

from backend.shared.auth_middleware import get_user_claims, require_superuser
from backend.shared.config import COGNITO_USER_POOL_ID, AWS_REGION
from backend.shared.dynamodb import (
    audit_sk,
    get_table,
    user_pk,
    user_sk,
)
from backend.shared.response import error_response, success_response


def handler(event, context):
    """Deactivate a user account.

    Requires superuser authorization. Sets user status to "deactivated",
    revokes all active Cognito sessions, and writes an audit log entry.
    """
    # --- Authorization ---
    auth_error = require_superuser(event)
    if auth_error is not None:
        return auth_error

    # --- Extract superuser identity for audit ---
    superuser_claims = get_user_claims(event)

    # --- Extract path parameter ---
    try:
        user_id = event["pathParameters"]["id"]
    except (KeyError, TypeError):
        return error_response(
            "Missing user ID in path.",
            "VALIDATION_ERROR",
            400,
        )

    # --- Retrieve existing user ---
    table = get_table()
    existing = table.get_item(
        Key={"PK": user_pk(user_id), "SK": user_sk()}
    )
    if "Item" not in existing:
        return error_response(
            "User not found.",
            "NOT_FOUND",
            404,
        )

    existing_user = existing["Item"]
    old_status = existing_user.get("status", "active")

    # --- Update user status to deactivated ---
    table.update_item(
        Key={"PK": user_pk(user_id), "SK": user_sk()},
        UpdateExpression="SET #status = :status",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":status": "deactivated"},
    )

    # --- Revoke all active Cognito sessions ---
    cognito_sub = existing_user.get("cognito_sub")
    if cognito_sub:
        cognito_client = boto3.client("cognito-idp", region_name=AWS_REGION)
        try:
            cognito_client.admin_user_global_sign_out(
                UserPoolId=COGNITO_USER_POOL_ID,
                Username=cognito_sub,
            )
        except Exception:
            # Log but don't fail the request if Cognito sign-out fails
            pass

    # --- Create audit log entry ---
    now = datetime.now(timezone.utc).isoformat()
    audit_item = {
        "PK": user_pk(user_id),
        "SK": audit_sk(now),
        "user_id": user_id,
        "action": "DEACTIVATE",
        "modified_by": superuser_claims["user_id"],
        "modified_by_name": superuser_claims["full_name"],
        "timestamp": now,
        "changes": {"status": {"old": old_status, "new": "deactivated"}},
        "entity_type": "USER_AUDIT",
    }
    table.put_item(Item=audit_item)

    # --- Build response with updated user data ---
    updated_user = {**existing_user, "status": "deactivated"}

    return success_response(_user_response(updated_user))


def _user_response(user: dict) -> dict:
    """Extract response-safe fields from a user record."""
    return {
        "user_id": user.get("user_id"),
        "full_name": user.get("full_name"),
        "email": user.get("email"),
        "department": user.get("department"),
        "role": user.get("role"),
        "phone_number": user.get("phone_number"),
        "status": user.get("status"),
        "created_at": user.get("created_at"),
    }
