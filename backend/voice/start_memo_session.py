"""Lambda handler for starting a voice-guided memo registration session."""

import json
import time
import uuid

import boto3

from backend.shared.config import AUDIO_BUCKET, AWS_REGION
from backend.shared.dynamodb import get_table, session_pk
from backend.shared.response import error_response, success_response

FIELD_PROMPTS = {
    "title": "What is the memo title?",
    "memo_type": "Is this an incoming or outgoing memo?",
    "memo_date": "What is the date on the memo?",
    "person_brought_in": "Who brought in this memo?",
    "person_took_out": "Who took out this memo?",
}

FIELD_ORDER = ["title", "memo_type", "memo_date", "person"]

SESSION_TTL_SECONDS = 3600  # 1 hour


def handler(event, context):
    """Start a new voice-guided memo registration session.

    Creates a Voice Session item in DynamoDB, generates the first field
    prompt audio via Polly, and returns session details to the caller.
    """
    try:
        body = json.loads(event.get("body", "{}"))
    except (json.JSONDecodeError, TypeError):
        return error_response(
            message="Invalid JSON in request body",
            error_code="VALIDATION_ERROR",
            status_code=400,
        )

    user_id = body.get("user_id")
    if not user_id or (isinstance(user_id, str) and not user_id.strip()):
        return error_response(
            message="Missing required field: user_id",
            error_code="VALIDATION_ERROR",
            status_code=400,
            details={"missing_fields": ["user_id"]},
        )

    session_id = str(uuid.uuid4())
    now_epoch = int(time.time())
    ttl = now_epoch + SESSION_TTL_SECONDS

    # Build Voice Session item
    item = {
        "PK": session_pk(session_id),
        "SK": "METADATA",
        "session_id": session_id,
        "user_id": user_id,
        "status": "in_progress",
        "current_field": "title",
        "fields_collected": {
            "title": None,
            "memo_type": None,
            "memo_date": None,
            "person_brought_in": None,
            "person_took_out": None,
        },
        "field_order": FIELD_ORDER,
        "retry_counts": {
            "title": 0,
            "memo_type": 0,
            "memo_date": 0,
            "person": 0,
        },
        "ttl": ttl,
        "entity_type": "VOICE_SESSION",
    }

    try:
        table = get_table()
        table.put_item(Item=item)
    except Exception:
        return error_response(
            message="Failed to create voice session",
            error_code="SERVICE_UNAVAILABLE",
            status_code=503,
        )

    # Generate first field prompt audio via Polly
    prompt_text = FIELD_PROMPTS["title"]
    request_id = str(uuid.uuid4())
    s3_key = f"audio/polly/{request_id}.mp3"

    try:
        polly_client = boto3.client("polly", region_name=AWS_REGION)
        polly_response = polly_client.synthesize_speech(
            Text=prompt_text,
            OutputFormat="mp3",
            VoiceId="Joanna",
        )

        s3_client = boto3.client("s3", region_name=AWS_REGION)
        s3_client.put_object(
            Bucket=AUDIO_BUCKET,
            Key=s3_key,
            Body=polly_response["AudioStream"].read(),
            ContentType="audio/mpeg",
        )

        prompt_audio_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": AUDIO_BUCKET, "Key": s3_key},
            ExpiresIn=SESSION_TTL_SECONDS,
        )
    except Exception:
        return error_response(
            message="Failed to generate prompt audio",
            error_code="SERVICE_UNAVAILABLE",
            status_code=503,
        )

    fields_remaining = [f for f in FIELD_ORDER if f != "title"]

    return success_response(
        {
            "session_id": session_id,
            "prompt_audio_url": prompt_audio_url,
            "current_field": "title",
            "fields_remaining": fields_remaining,
        },
        status_code=201,
    )
