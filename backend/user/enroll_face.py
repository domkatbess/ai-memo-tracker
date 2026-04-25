"""Lambda handler for enrolling a user's face for biometric authentication.

Accepts a base64-encoded face image, uploads it to the biometric S3 bucket,
indexes the face in an AWS Rekognition collection, and updates the user
record in DynamoDB with the S3 key.

Only superusers may enroll faces.

Validates: Requirements 6.4, 8.3
"""

import base64
import json

import boto3

from backend.shared.auth_middleware import require_superuser
from backend.shared.config import (
    AWS_REGION,
    BIOMETRIC_BUCKET,
    REKOGNITION_COLLECTION_ID,
)
from backend.shared.dynamodb import get_table, user_pk, user_sk
from backend.shared.response import error_response, success_response


def handler(event, context):
    """Enroll a user's face image for biometric authentication.

    Requires superuser authorization. Uploads the face image to S3,
    indexes it in Rekognition, and stores the S3 key on the user record.
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

    image_b64 = body.get("image")
    if not image_b64:
        return error_response(
            "Missing required field: image.",
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

    # --- Decode image and upload to S3 ---
    image_bytes = base64.b64decode(image_b64)
    s3_key = f"biometric/{user_id}/face.jpg"

    s3_client = boto3.client("s3", region_name=AWS_REGION)
    s3_client.put_object(
        Bucket=BIOMETRIC_BUCKET,
        Key=s3_key,
        Body=image_bytes,
        ContentType="image/jpeg",
    )

    # --- Index face in Rekognition collection ---
    rekognition_client = boto3.client("rekognition", region_name=AWS_REGION)
    rekognition_client.index_faces(
        CollectionId=REKOGNITION_COLLECTION_ID,
        Image={"Bytes": image_bytes},
        ExternalImageId=user_id,
        DetectionAttributes=["DEFAULT"],
    )

    # --- Update user record with S3 key ---
    table.update_item(
        Key={"PK": user_pk(user_id), "SK": user_sk()},
        UpdateExpression="SET face_image_s3_key = :key",
        ExpressionAttributeValues={":key": s3_key},
    )

    return success_response(
        {
            "user_id": user_id,
            "face_image_s3_key": s3_key,
            "message": "Face enrolled successfully.",
        }
    )
