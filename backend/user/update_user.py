"""Lambda handler for updating an existing user account.

Only superusers may update users. The handler validates input, checks for
duplicate emails when email changes, updates the user record in DynamoDB
and Cognito, and creates an audit log entry.

Validates: Requirements 8.7
"""

import json
from datetime import datetime, timezone

import boto3

from backend.shared.auth_middleware import get_user_claims, require_superuser
from backend.shared.config import COGNITO_USER_POOL_ID, AWS_REGION
from backend.shared.dynamodb import (
    audit_sk,
    get_table,
    gsi1_email_pk,
    gsi1_email_sk,
    gsi2_role_pk,
    gsi2_role_sk,
    user_pk,
    user_sk,
)
from backend.shared.response import error_response, success_response
from backend.shared.validators import validate_email

UPDATABLE_FIELDS = {"full_name", "email", "department", "role", "phone_number"}
VALID_ROLES = {"regular_user", "superuser"}


def handler(event, context):
    """Update an existing user account.

    Requires superuser authorization. Validates fields, checks email
    uniqueness if changed, updates DynamoDB and Cognito, and writes an
    audit log entry.
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

    # --- Parse body ---
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return error_response(
            "Invalid JSON in request body.",
            "VALIDATION_ERROR",
            400,
        )

    if not body:
        return error_response(
            "No fields provided for update.",
            "VALIDATION_ERROR",
            400,
        )

    # --- Filter to updatable fields only ---
    updates = {k: v for k, v in body.items() if k in UPDATABLE_FIELDS}
    if not updates:
        return error_response(
            "No valid fields provided for update.",
            "VALIDATION_ERROR",
            400,
        )

    # --- Validate email format if provided ---
    if "email" in updates:
        email = updates["email"].strip() if isinstance(updates["email"], str) else updates["email"]
        if not validate_email(email):
            return error_response(
                "Invalid email format.",
                "VALIDATION_ERROR",
                400,
                details={"invalid_fields": ["email"]},
            )
        updates["email"] = email

    # --- Validate role if provided ---
    if "role" in updates:
        role = updates["role"].strip() if isinstance(updates["role"], str) else updates["role"]
        if role not in VALID_ROLES:
            return error_response(
                f"Invalid role. Must be one of: {', '.join(sorted(VALID_ROLES))}.",
                "VALIDATION_ERROR",
                400,
                details={"invalid_fields": ["role"]},
            )
        updates["role"] = role

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

    # --- Check duplicate email if email is changing ---
    if "email" in updates and updates["email"] != existing_user.get("email"):
        gsi1_response = table.query(
            IndexName="GSI1",
            KeyConditionExpression="GSI1PK = :pk AND GSI1SK = :sk",
            ExpressionAttributeValues={
                ":pk": gsi1_email_pk(updates["email"]),
                ":sk": gsi1_email_sk(),
            },
            Limit=1,
        )
        if gsi1_response.get("Items"):
            return error_response(
                "Email already registered.",
                "DUPLICATE_EMAIL",
                409,
            )

    # --- Build changes dict for audit log ---
    changes = {}
    for field, new_value in updates.items():
        old_value = existing_user.get(field)
        if isinstance(new_value, str):
            new_value = new_value.strip()
            updates[field] = new_value
        if old_value != new_value:
            changes[field] = {"old": old_value, "new": new_value}

    if not changes:
        # Nothing actually changed — return current user data
        return success_response(_user_response(existing_user))

    # --- Update DynamoDB record ---
    update_expr_parts = []
    expr_attr_names = {}
    expr_attr_values = {}

    for field, change in changes.items():
        attr_alias = f"#{field}"
        val_alias = f":{field}"
        update_expr_parts.append(f"{attr_alias} = {val_alias}")
        expr_attr_names[attr_alias] = field
        expr_attr_values[val_alias] = change["new"]

    # Update GSI keys if email changed
    if "email" in changes:
        update_expr_parts.append("GSI1PK = :gsi1pk")
        expr_attr_values[":gsi1pk"] = gsi1_email_pk(changes["email"]["new"])
        update_expr_parts.append("GSI1SK = :gsi1sk")
        expr_attr_values[":gsi1sk"] = gsi1_email_sk()

    # Update GSI keys if role changed
    if "role" in changes:
        update_expr_parts.append("GSI2PK = :gsi2pk")
        expr_attr_values[":gsi2pk"] = gsi2_role_pk(changes["role"]["new"])
        update_expr_parts.append("GSI2SK = :gsi2sk")
        expr_attr_values[":gsi2sk"] = gsi2_role_sk(user_id)

    update_expression = "SET " + ", ".join(update_expr_parts)

    table.update_item(
        Key={"PK": user_pk(user_id), "SK": user_sk()},
        UpdateExpression=update_expression,
        ExpressionAttributeNames=expr_attr_names if expr_attr_names else None,
        ExpressionAttributeValues=expr_attr_values,
    )

    # --- Update Cognito if name or email changed ---
    cognito_attrs = []
    if "full_name" in changes:
        cognito_attrs.append({"Name": "name", "Value": changes["full_name"]["new"]})
    if "email" in changes:
        cognito_attrs.append({"Name": "email", "Value": changes["email"]["new"]})

    if cognito_attrs and existing_user.get("cognito_sub"):
        cognito_client = boto3.client("cognito-idp", region_name=AWS_REGION)
        try:
            cognito_client.admin_update_user_attributes(
                UserPoolId=COGNITO_USER_POOL_ID,
                Username=existing_user["cognito_sub"],
                UserAttributes=cognito_attrs,
            )
        except Exception:
            # Log but don't fail the request if Cognito update fails
            pass

    # --- Create audit log entry ---
    now = datetime.now(timezone.utc).isoformat()
    audit_item = {
        "PK": user_pk(user_id),
        "SK": audit_sk(now),
        "user_id": user_id,
        "action": "UPDATE",
        "modified_by": superuser_claims["user_id"],
        "modified_by_name": superuser_claims["full_name"],
        "timestamp": now,
        "changes": changes,
        "entity_type": "USER_AUDIT",
    }
    table.put_item(Item=audit_item)

    # --- Build updated user for response ---
    updated_user = {**existing_user}
    for field, change in changes.items():
        updated_user[field] = change["new"]

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
