"""Lambda handler for confirming or rejecting a voice-guided memo registration session."""

import json
import uuid
from datetime import datetime, timezone

import boto3

from backend.shared.config import AUDIO_BUCKET, AWS_REGION
from backend.shared.dynamodb import (
    get_table,
    gsi1_date_sk,
    gsi1_type_pk,
    gsi2_person_pk,
    memo_pk,
    memo_sk,
    session_pk,
)
from backend.shared.response import error_response, success_response
from backend.voice.submit_session_field import _transcribe_audio

SESSION_TTL_SECONDS = 3600


def _get_session(table, session_id):
    """Retrieve a voice session from DynamoDB by session_id."""
    response = table.get_item(
        Key={"PK": session_pk(session_id), "SK": "METADATA"}
    )
    return response.get("Item")


def _validate_session_fields(fields_collected):
    """Check that all required fields have been collected."""
    title = fields_collected.get("title")
    memo_type = fields_collected.get("memo_type")
    memo_date = fields_collected.get("memo_date")

    if not title or not memo_type or not memo_date:
        return False

    if memo_type == "incoming":
        return bool(fields_collected.get("person_brought_in"))
    else:
        return bool(fields_collected.get("person_took_out"))


def _generate_prompt_audio(prompt_text):
    """Generate prompt audio via Polly and upload to S3.

    Returns a presigned URL for the audio.
    """
    polly_client = boto3.client("polly", region_name=AWS_REGION)
    polly_response = polly_client.synthesize_speech(
        Text=prompt_text,
        OutputFormat="mp3",
        VoiceId="Joanna",
    )

    request_id = str(uuid.uuid4())
    s3_key = f"audio/polly/{request_id}.mp3"

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
    return prompt_audio_url


def _create_memo_from_session(table, session):
    """Create a memo record in DynamoDB from session data.

    Returns the new memo_id.
    """
    fields = session.get("fields_collected", {})
    memo_type = fields.get("memo_type", "")
    memo_date = fields.get("memo_date", "")
    title = fields.get("title", "")
    person_brought_in = fields.get("person_brought_in") or ""
    person_took_out = fields.get("person_took_out") or ""
    created_by = session.get("user_id", "")

    new_memo_id = str(uuid.uuid4())
    recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    person_name = person_brought_in if memo_type == "incoming" else person_took_out

    item = {
        "PK": memo_pk(new_memo_id),
        "SK": memo_sk(),
        "memo_id": new_memo_id,
        "title": title,
        "memo_type": memo_type,
        "memo_date": memo_date,
        "recorded_at": recorded_at,
        "person_brought_in": person_brought_in,
        "person_took_out": person_took_out,
        "created_by": created_by,
        "entity_type": "MEMO",
        "GSI1PK": gsi1_type_pk(memo_type),
        "GSI1SK": gsi1_date_sk(memo_date),
        "GSI2PK": gsi2_person_pk(person_name.lower()),
        "GSI2SK": gsi1_date_sk(memo_date),
    }

    table.put_item(Item=item)
    return new_memo_id


def _parse_confirmation(transcribed_text):
    """Parse transcribed text for yes/no confirmation.

    Returns "yes", "no", or "unclear".
    """
    lower = transcribed_text.lower()
    if "yes" in lower:
        return "yes"
    if "no" in lower:
        return "no"
    return "unclear"


def handler(event, context):
    """Confirm or reject a voice-guided memo registration session.

    Transcribes the user's spoken confirmation audio and:
    - If "yes": creates the memo, updates session to "saved", returns 201
    - If "no": returns collected data with re-record/cancel options, returns 200
    - If unclear: returns CONFIRMATION_UNCLEAR error, returns 422
    """
    # Extract session_id from path parameters
    path_params = event.get("pathParameters") or {}
    session_id = path_params.get("session_id")
    if not session_id:
        return error_response(
            message="Missing session_id in path",
            error_code="VALIDATION_ERROR",
            status_code=400,
        )

    # Parse request body
    try:
        body = json.loads(event.get("body", "{}"))
    except (json.JSONDecodeError, TypeError):
        return error_response(
            message="Invalid JSON in request body",
            error_code="VALIDATION_ERROR",
            status_code=400,
        )

    audio_key = body.get("audio_key")
    if not audio_key or (isinstance(audio_key, str) and not audio_key.strip()):
        return error_response(
            message="Missing required field: audio_key",
            error_code="VALIDATION_ERROR",
            status_code=400,
            details={"missing_fields": ["audio_key"]},
        )

    # Retrieve session from DynamoDB
    try:
        table = get_table()
        session = _get_session(table, session_id)
    except Exception:
        return error_response(
            message="Failed to retrieve session",
            error_code="SERVICE_UNAVAILABLE",
            status_code=503,
        )

    if not session:
        return error_response(
            message="Session not found",
            error_code="SESSION_NOT_FOUND",
            status_code=404,
        )

    # Validate all required fields are collected
    fields_collected = session.get("fields_collected", {})
    if not _validate_session_fields(fields_collected):
        return error_response(
            message="Session fields incomplete",
            error_code="SESSION_INCOMPLETE",
            status_code=400,
        )

    # Transcribe the confirmation audio
    try:
        transcribed_text = _transcribe_audio(audio_key)
    except Exception:
        transcribed_text = None

    if not transcribed_text:
        return error_response(
            message="Failed to transcribe confirmation audio",
            error_code="SERVICE_UNAVAILABLE",
            status_code=503,
        )

    # Parse confirmation response
    confirmation = _parse_confirmation(transcribed_text)

    if confirmation == "yes":
        # Create the memo
        try:
            memo_id = _create_memo_from_session(table, session)
        except Exception:
            return error_response(
                message="Failed to create memo",
                error_code="SERVICE_UNAVAILABLE",
                status_code=503,
            )

        # Update session status to "saved"
        try:
            table.update_item(
                Key={"PK": session_pk(session_id), "SK": "METADATA"},
                UpdateExpression="SET #status = :saved",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":saved": "saved"},
            )
        except Exception:
            return error_response(
                message="Failed to update session status",
                error_code="SERVICE_UNAVAILABLE",
                status_code=503,
            )

        # Generate confirmation audio
        try:
            confirmation_audio_url = _generate_prompt_audio(
                "Memo saved successfully"
            )
        except Exception:
            return error_response(
                message="Failed to generate confirmation audio",
                error_code="SERVICE_UNAVAILABLE",
                status_code=503,
            )

        return success_response(
            {
                "status": "saved",
                "memo_id": memo_id,
                "confirmation_audio_url": confirmation_audio_url,
            },
            status_code=201,
        )

    elif confirmation == "no":
        # Generate rejection prompt audio
        try:
            prompt_audio_url = _generate_prompt_audio(
                "Which field would you like to re-record?"
            )
        except Exception:
            return error_response(
                message="Failed to generate prompt audio",
                error_code="SERVICE_UNAVAILABLE",
                status_code=503,
            )

        collected_data = {
            "title": fields_collected.get("title"),
            "memo_type": fields_collected.get("memo_type"),
            "memo_date": fields_collected.get("memo_date"),
            "person_brought_in": fields_collected.get("person_brought_in"),
            "person_took_out": fields_collected.get("person_took_out"),
        }

        return success_response({
            "status": "rejected",
            "collected_data": collected_data,
            "options": ["re-record", "cancel"],
            "prompt_audio_url": prompt_audio_url,
        })

    else:
        # Unclear confirmation
        try:
            prompt_audio_url = _generate_prompt_audio(
                "Please say yes or no"
            )
        except Exception:
            return error_response(
                message="Failed to generate prompt audio",
                error_code="SERVICE_UNAVAILABLE",
                status_code=503,
            )

        return {
            "statusCode": 422,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "error": "Could not understand confirmation",
                "error_code": "CONFIRMATION_UNCLEAR",
                "prompt_audio_url": prompt_audio_url,
            }),
        }
