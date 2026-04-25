"""Lambda handler for creating a new user account.

Only superusers may create users. The handler validates input, checks for
duplicate emails, creates a Cognito user, and stores the user record in
DynamoDB.

Validates: Requirements 8.2, 9.2, 9.5
"""

import json
import uuid
from datetime import datetime, timezone

import boto3

from backend.shared.auth_middleware import require_superuser
from backend.shared.config import COGNITO_USER_POOL_ID, AWS_REGION
from backend.shared.dynamodb import (
    get_table,
    user_pk,
    user_sk,
    gsi1_email_pk,
    gsi1_email_sk,
    gsi2_role_pk,
    gsi2_role_sk,
)
from backend.shared.response import error_response, success_response
from backend.shared.validators import check_required_fields, validate_email

REQUIRED_FIELDS = ["full_name", "email", "department", "role", "phone_number"]
VALID_ROLES = {"regular_user", "superuser"}


def handler(event, context):
    """Create a new user account.

    Requires superuser authorization. Validates required fields, email format,
    role value, and email uniqueness before creating the Cognito user and
    DynamoDB record.
    """
    # --- Authorization ---
    auth_error = require_superuser(event)
    if auth_error is not None:
        return auth_error

    # --- Parse body ---
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return error_response(
            "Invalid JSON in request body.",
            "VALIDATION_ERROR",
            400,
        )

    # --- Validate required fields ---
    missing = check_required_fields(body, REQUIRED_FIELDS)
    if missing:
        return error_response(
            "Missing required fields.",
            "VALIDATION_ERROR",
            400,
            details={"missing_fields": missing},
        )

    email = body["email"].strip()
    full_name = body["full_name"].strip()
    department = body["department"].strip()
    role = body["role"].strip()
    phone_number = body["phone_number"].strip()

    # --- Validate email format ---
    if not validate_email(email):
        return error_response(
            "Invalid email format.",
            "VALIDATION_ERROR",
            400,
            details={"invalid_fields": ["email"]},
        )

    # --- Validate role ---
    if role not in VALID_ROLES:
        return error_response(
            f"Invalid role. Must be one of: {', '.join(sorted(VALID_ROLES))}.",
            "VALIDATION_ERROR",
            400,
            details={"invalid_fields": ["role"]},
        )

    # --- Check duplicate email via GSI1 ---
    table = get_table()
    gsi1_response = table.query(
        IndexName="GSI1",
        KeyConditionExpression="GSI1PK = :pk AND GSI1SK = :sk",
        ExpressionAttributeValues={
            ":pk": gsi1_email_pk(email),
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

    # --- Create Cognito user ---
    cognito_client = boto3.client("cognito-idp", region_name=AWS_REGION)
    cognito_response = cognito_client.admin_create_user(
        UserPoolId=COGNITO_USER_POOL_ID,
        Username=email,
        UserAttributes=[
            {"Name": "email", "Value": email},
            {"Name": "name", "Value": full_name},
            {"Name": "custom:role", "Value": role},
        ],
        MessageAction="SUPPRESS",
    )
    cognito_sub = cognito_response["User"]["Attributes"]
    # Extract the 'sub' attribute from the Cognito response
    cognito_sub_value = ""
    for attr in cognito_sub:
        if attr["Name"] == "sub":
            cognito_sub_value = attr["Value"]
            break

    # --- Build and store DynamoDB record ---
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    item = {
        "PK": user_pk(user_id),
        "SK": user_sk(),
        "user_id": user_id,
        "full_name": full_name,
        "email": email,
        "department": department,
        "role": role,
        "phone_number": phone_number,
        "status": "active",
        "face_image_s3_key": None,
        "voice_sample_s3_key": None,
        "cognito_sub": cognito_sub_value,
        "created_at": now,
        "failed_auth_attempts": 0,
        "GSI1PK": gsi1_email_pk(email),
        "GSI1SK": gsi1_email_sk(),
        "GSI2PK": gsi2_role_pk(role),
        "GSI2SK": gsi2_role_sk(user_id),
        "entity_type": "USER",
    }

    table.put_item(Item=item)

    return success_response(
        {
            "user_id": user_id,
            "full_name": full_name,
            "email": email,
            "department": department,
            "role": role,
            "phone_number": phone_number,
            "status": "active",
            "created_at": now,
        },
        status_code=201,
    )
