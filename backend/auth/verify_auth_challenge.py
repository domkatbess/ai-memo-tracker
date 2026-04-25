"""
Cognito VerifyAuthChallengeResponse Lambda trigger.

Verifies the biometric response (facial image or voice sample) against
stored reference data and returns whether the answer is correct.

- Facial auth: retrieves reference face from S3, calls Rekognition
  CompareFaces, checks confidence >= 95%.
- Voice auth: retrieves reference voiceprint from S3, extracts embedding
  from submitted sample, computes cosine similarity against reference.
- Tracks failed_auth_attempts on the user record in DynamoDB.
- Locks account and notifies superuser after 3 facial + 3 voice failures.

Requirements: 6.2, 6.3, 7.1, 7.2, 7.3, 7.5
"""

import base64
import json
import logging

import boto3

from backend.auth.define_auth_challenge import MAX_FAILURES_PER_METHOD
from backend.auth.voice_biometrics import verify_voice
from backend.shared.config import (
    AWS_REGION,
    BIOMETRIC_BUCKET,
    TABLE_NAME,
)
from backend.shared.dynamodb import get_table, user_pk, user_sk

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Minimum Rekognition confidence score for a facial match.
FACIAL_CONFIDENCE_THRESHOLD = 95.0

# Total failures that trigger account lock (3 facial + 3 voice).
TOTAL_LOCKOUT_THRESHOLD = MAX_FAILURES_PER_METHOD * 2


def _get_s3_object(bucket: str, key: str) -> bytes:
    """Download an object from S3 and return its body bytes."""
    s3 = boto3.client("s3", region_name=AWS_REGION)
    response = s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def _verify_facial(user_id: str, challenge_answer: str) -> bool:
    """Verify a facial image against the stored reference.

    Parameters
    ----------
    user_id : str
        The user whose reference face to compare against.
    challenge_answer : str
        Base64-encoded image submitted by the client.

    Returns
    -------
    bool
        True if the confidence score >= 95%.
    """
    # Retrieve reference face from S3
    reference_key = f"biometric/{user_id}/face.jpg"
    reference_bytes = _get_s3_object(BIOMETRIC_BUCKET, reference_key)

    # Decode submitted image
    submitted_bytes = base64.b64decode(challenge_answer)

    # Call Rekognition CompareFaces
    rekognition = boto3.client("rekognition", region_name=AWS_REGION)
    response = rekognition.compare_faces(
        SourceImage={"Bytes": reference_bytes},
        TargetImage={"Bytes": submitted_bytes},
        SimilarityThreshold=0.0,  # We check the threshold ourselves
    )

    face_matches = response.get("FaceMatches", [])
    if not face_matches:
        return False

    # Use the highest confidence match
    best_confidence = max(m["Similarity"] for m in face_matches)
    return best_confidence >= FACIAL_CONFIDENCE_THRESHOLD


def _verify_voice(user_id: str, challenge_answer: str) -> bool:
    """Verify a voice sample against the stored reference voiceprint.

    Parameters
    ----------
    user_id : str
        The user whose reference voiceprint to compare against.
    challenge_answer : str
        Base64-encoded audio submitted by the client.

    Returns
    -------
    bool
        True if cosine similarity meets the threshold.
    """
    # Retrieve reference voice sample from S3
    reference_key = f"biometric/{user_id}/voice_enrollment.wav"
    reference_bytes = _get_s3_object(BIOMETRIC_BUCKET, reference_key)

    # Decode submitted audio
    submitted_bytes = base64.b64decode(challenge_answer)

    is_match, similarity = verify_voice(reference_bytes, submitted_bytes)
    logger.info(
        "Voice verification for user %s: similarity=%.4f, match=%s",
        user_id,
        similarity,
        is_match,
    )
    return is_match


def _get_user_record(user_id: str) -> dict | None:
    """Retrieve the user profile from DynamoDB."""
    table = get_table()
    response = table.get_item(
        Key={"PK": user_pk(user_id), "SK": user_sk()}
    )
    return response.get("Item")


def _update_failed_attempts(user_id: str, new_count: int) -> None:
    """Update the failed_auth_attempts counter on the user record."""
    table = get_table()
    table.update_item(
        Key={"PK": user_pk(user_id), "SK": user_sk()},
        UpdateExpression="SET failed_auth_attempts = :count",
        ExpressionAttributeValues={":count": new_count},
    )


def _reset_failed_attempts(user_id: str) -> None:
    """Reset failed_auth_attempts to 0 on successful auth."""
    _update_failed_attempts(user_id, 0)


def _lock_account(user_id: str) -> None:
    """Lock the user account by setting status to 'deactivated'."""
    table = get_table()
    table.update_item(
        Key={"PK": user_pk(user_id), "SK": user_sk()},
        UpdateExpression="SET #status = :status",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":status": "deactivated"},
    )
    logger.warning("Account locked for user %s after repeated auth failures.", user_id)


def _notify_superuser(user_id: str) -> None:
    """Notify the superuser about an account lockout.

    For now this logs the event. In a production system this would
    create a notification record or send an SNS message.
    """
    logger.warning(
        "SUPERUSER NOTIFICATION: User %s account has been locked "
        "after exceeding maximum authentication failures.",
        user_id,
    )


def handler(event: dict, context) -> dict:
    """Cognito VerifyAuthChallengeResponse trigger handler.

    Reads the auth type and user_id from privateChallengeParameters,
    verifies the biometric response, updates the failed attempt counter,
    and returns answerCorrect.
    """
    request = event.get("request", {})
    private_params = request.get("privateChallengeParameters", {})
    challenge_answer = request.get("challengeAnswer", "")

    auth_type = private_params.get("auth_type", "")
    user_id = private_params.get("user_id", "")

    response = event.setdefault("response", {})

    # Default to failure
    answer_correct = False

    try:
        if auth_type == "facial":
            answer_correct = _verify_facial(user_id, challenge_answer)
        elif auth_type == "voice":
            answer_correct = _verify_voice(user_id, challenge_answer)
        else:
            logger.error("Unknown auth_type: %s", auth_type)
            answer_correct = False
    except Exception:
        logger.exception(
            "Error during %s verification for user %s", auth_type, user_id
        )
        answer_correct = False

    # Update failed attempt tracking
    if user_id:
        try:
            user_record = _get_user_record(user_id)
            if user_record:
                current_failures = int(
                    user_record.get("failed_auth_attempts", 0)
                )

                if answer_correct:
                    _reset_failed_attempts(user_id)
                else:
                    new_count = current_failures + 1
                    _update_failed_attempts(user_id, new_count)

                    # Lock account after total lockout threshold
                    if new_count >= TOTAL_LOCKOUT_THRESHOLD:
                        _lock_account(user_id)
                        _notify_superuser(user_id)
        except Exception:
            logger.exception(
                "Error updating failed auth attempts for user %s", user_id
            )

    response["answerCorrect"] = answer_correct
    return event
