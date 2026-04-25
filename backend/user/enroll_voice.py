"""Lambda handler for enrolling a user's voice for biometric authentication.

Accepts a base64-encoded voice sample, uploads it to the biometric S3 bucket,
extracts a voiceprint embedding and stores it for future comparison, and
updates the user record in DynamoDB with the S3 key.

Only superusers may enroll voices.

Validates: Requirements 7.4, 8.4
"""

import base64
import json

import boto3

from backend.auth.voice_biometrics import extract_embedding
from backend.shared.auth_middleware import require_superuser
from backend.shared.config import AWS_REGION, BIOMETRIC_BUCKET
from backend.shared.dynamodb import get_table, user_pk, user_sk
from backend.shared.response import error_response, success_response


def handler(event, context):
    """Enroll a user's voice sample for biometric authentication.

    Requires superuser authorization. Uploads the voice sample to S3,
    extracts a voiceprint embedding, stores the embedding as JSON in S3,
    and records the S3 key on the user record.
    """
    # --- Authorization ---
    auth_error = require_superuser(event)
    if auth_error is not None:
        return auth_error

    # --- Extract user_id from path ---
    user_id = event["pathParameters"]["id"]

    # --- Parse body ---
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return error_response(
            "Invalid JSON in request body.",
            "VALIDATION_ERROR",
            400,
        )

    audio_b64 = body.get("audio")
    if not audio_b64:
        return error_response(
            "Missing required field: audio.",
            "VALIDATION_ERROR",
            400,
        )

    # --- Verify user exists ---
    table = get_table()
    user_response = table.get_item(Key={"PK": user_pk(user_id), "SK": user_sk()})
    if "Item" not in user_response:
        return error_response(
            "User not found.",
            "NOT_FOUND",
            404,
        )

    # --- Decode audio and upload to S3 ---
    audio_bytes = base64.b64decode(audio_b64)
    s3_key = f"biometric/{user_id}/voice_enrollment.wav"

    s3_client = boto3.client("s3", region_name=AWS_REGION)
    s3_client.put_object(
        Bucket=BIOMETRIC_BUCKET,
        Key=s3_key,
        Body=audio_bytes,
        ContentType="audio/wav",
    )

    # --- Extract voiceprint embedding ---
    embedding = extract_embedding(audio_bytes)

    # --- Store embedding as JSON in S3 ---
    embedding_key = f"biometric/{user_id}/voice_embedding.json"
    s3_client.put_object(
        Bucket=BIOMETRIC_BUCKET,
        Key=embedding_key,
        Body=json.dumps(embedding),
        ContentType="application/json",
    )

    # --- Update user record with S3 key ---
    table.update_item(
        Key={"PK": user_pk(user_id), "SK": user_sk()},
        UpdateExpression="SET voice_sample_s3_key = :key",
        ExpressionAttributeValues={":key": s3_key},
    )

    return success_response(
        {
            "user_id": user_id,
            "voice_sample_s3_key": s3_key,
            "message": "Voice enrolled successfully.",
        }
    )
