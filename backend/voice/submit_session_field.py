"""Lambda handler for submitting a spoken field response during voice-guided memo registration."""

import json
import time
import uuid

import boto3

from backend.shared.config import AUDIO_BUCKET, AWS_REGION
from backend.shared.dynamodb import get_table, session_pk
from backend.shared.response import error_response, success_response
from backend.voice.start_memo_session import FIELD_ORDER, FIELD_PROMPTS

MAX_RETRIES = 2
TRANSCRIBE_POLL_INTERVAL = 0.5
TRANSCRIBE_POLL_MAX_ATTEMPTS = 60


def _get_session(table, session_id):
    """Retrieve a voice session from DynamoDB by session_id."""
    response = table.get_item(
        Key={"PK": session_pk(session_id), "SK": "METADATA"}
    )
    return response.get("Item")


def _transcribe_audio(audio_s3_key, transcribe_client=None):
    """Start a Transcribe batch job and poll until complete.

    Returns the transcribed text on success, or None on failure.
    """
    import urllib.request

    if transcribe_client is None:
        transcribe_client = boto3.client("transcribe", region_name=AWS_REGION)

    job_name = f"session-field-{uuid.uuid4()}"

    transcribe_client.start_transcription_job(
        TranscriptionJobName=job_name,
        Media={"MediaFileUri": f"s3://{AUDIO_BUCKET}/{audio_s3_key}"},
        MediaFormat="wav",
        LanguageCode="en-US",
    )

    for _ in range(TRANSCRIBE_POLL_MAX_ATTEMPTS):
        result = transcribe_client.get_transcription_job(
            TranscriptionJobName=job_name
        )
        status = result["TranscriptionJob"]["TranscriptionJobStatus"]
        if status == "COMPLETED":
            transcript_uri = result["TranscriptionJob"]["Transcript"][
                "TranscriptFileUri"
            ]
            # Fetch the transcript JSON from the URI
            response = urllib.request.urlopen(transcript_uri)
            transcript_json = json.loads(response.read().decode("utf-8"))
            transcripts = transcript_json.get("results", {}).get(
                "transcripts", []
            )
            if transcripts:
                return transcripts[0].get("transcript", "").strip()
            return None
        elif status == "FAILED":
            return None
        time.sleep(TRANSCRIBE_POLL_INTERVAL)

    return None


def _validate_field_value(field_name, value):
    """Validate a transcribed field value.

    Returns (is_valid, cleaned_value).
    """
    if not value or not value.strip():
        return False, value

    cleaned = value.strip()

    if field_name == "memo_type":
        lower = cleaned.lower()
        if "incoming" in lower:
            return True, "incoming"
        elif "outgoing" in lower:
            return True, "outgoing"
        return False, cleaned

    if field_name == "memo_date":
        # Basic date validation: must contain at least some date-like content
        import re

        # Accept various date formats
        date_patterns = [
            r"\d{4}-\d{2}-\d{2}",  # ISO format
            r"\d{1,2}/\d{1,2}/\d{2,4}",  # MM/DD/YYYY
            r"\d{1,2}-\d{1,2}-\d{2,4}",  # MM-DD-YYYY
            r"(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s*\d{2,4}",
        ]
        for pattern in date_patterns:
            if re.search(pattern, cleaned, re.IGNORECASE):
                return True, cleaned
        return False, cleaned

    # For title and person fields, any non-empty string is valid
    return True, cleaned


def _get_person_field_name(memo_type):
    """Determine the actual person field name based on memo_type."""
    if memo_type == "incoming":
        return "person_brought_in"
    return "person_took_out"


def _get_person_prompt(memo_type):
    """Get the correct person prompt based on memo_type."""
    if memo_type == "incoming":
        return FIELD_PROMPTS["person_brought_in"]
    return FIELD_PROMPTS["person_took_out"]


def _get_next_field(current_field):
    """Get the next field in FIELD_ORDER after current_field, or None."""
    try:
        idx = FIELD_ORDER.index(current_field)
        if idx + 1 < len(FIELD_ORDER):
            return FIELD_ORDER[idx + 1]
    except ValueError:
        pass
    return None


def _get_prompt_for_field(field_name, session):
    """Get the prompt text for a given field, handling the person field specially."""
    if field_name == "person":
        memo_type = session.get("fields_collected", {}).get("memo_type")
        return _get_person_prompt(memo_type)
    return FIELD_PROMPTS.get(field_name, "")


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
        ExpiresIn=3600,
    )
    return prompt_audio_url


def handler(event, context):
    """Submit a spoken field response for the current voice session prompt.

    Transcribes the audio, validates the field value, updates the session,
    and returns the next prompt or completion status.
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

    current_field = session.get("current_field")
    if not current_field:
        return error_response(
            message="Session has no pending field",
            error_code="SESSION_COMPLETE",
            status_code=400,
        )

    # Determine the actual field name for storage (person -> person_brought_in/person_took_out)
    if current_field == "person":
        memo_type = session.get("fields_collected", {}).get("memo_type")
        actual_field_name = _get_person_field_name(memo_type)
    else:
        actual_field_name = current_field

    # Copy audio to the session's S3 path
    try:
        s3_client = boto3.client("s3", region_name=AWS_REGION)
        s3_dest_key = (
            f"audio/voice-sessions/{session_id}/{actual_field_name}.wav"
        )
        s3_client.copy_object(
            Bucket=AUDIO_BUCKET,
            CopySource={"Bucket": AUDIO_BUCKET, "Key": audio_key},
            Key=s3_dest_key,
        )
    except Exception:
        return error_response(
            message="Failed to process audio file",
            error_code="SERVICE_UNAVAILABLE",
            status_code=503,
        )

    # Transcribe the audio
    try:
        transcribed_text = _transcribe_audio(s3_dest_key)
    except Exception:
        transcribed_text = None

    # Get current retry counts
    retry_counts = session.get("retry_counts", {})
    current_retry = int(retry_counts.get(current_field, 0))

    # Handle transcription failure
    if not transcribed_text:
        current_retry += 1

        # Update retry count in DynamoDB
        try:
            table.update_item(
                Key={"PK": session_pk(session_id), "SK": "METADATA"},
                UpdateExpression="SET retry_counts.#field = :count",
                ExpressionAttributeNames={"#field": current_field},
                ExpressionAttributeValues={":count": current_retry},
            )
        except Exception:
            pass

        if current_retry >= MAX_RETRIES:
            return error_response(
                message="Maximum retries exceeded for field",
                error_code="FIELD_RETRY_EXCEEDED",
                status_code=422,
                details={
                    "field": current_field,
                    "options": ["cancel", "manual_input"],
                },
            )

        # Re-prompt for the same field
        try:
            prompt_text = _get_prompt_for_field(current_field, session)
            prompt_audio_url = _generate_prompt_audio(prompt_text)
        except Exception:
            return error_response(
                message="Failed to generate re-prompt audio",
                error_code="SERVICE_UNAVAILABLE",
                status_code=503,
            )

        return {
            "statusCode": 422,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {
                    "error": "Transcription failed",
                    "error_code": "TRANSCRIPTION_FAILED",
                    "retry_count": current_retry,
                    "max_retries": MAX_RETRIES,
                    "prompt_audio_url": prompt_audio_url,
                }
            ),
        }

    # Validate the transcribed value
    is_valid, cleaned_value = _validate_field_value(current_field, transcribed_text)

    if not is_valid:
        # Treat validation failure like transcription failure
        current_retry += 1

        try:
            table.update_item(
                Key={"PK": session_pk(session_id), "SK": "METADATA"},
                UpdateExpression="SET retry_counts.#field = :count",
                ExpressionAttributeNames={"#field": current_field},
                ExpressionAttributeValues={":count": current_retry},
            )
        except Exception:
            pass

        if current_retry >= MAX_RETRIES:
            return error_response(
                message="Maximum retries exceeded for field",
                error_code="FIELD_RETRY_EXCEEDED",
                status_code=422,
                details={
                    "field": current_field,
                    "options": ["cancel", "manual_input"],
                },
            )

        try:
            prompt_text = _get_prompt_for_field(current_field, session)
            prompt_audio_url = _generate_prompt_audio(prompt_text)
        except Exception:
            return error_response(
                message="Failed to generate re-prompt audio",
                error_code="SERVICE_UNAVAILABLE",
                status_code=503,
            )

        return {
            "statusCode": 422,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {
                    "error": "Transcription failed",
                    "error_code": "TRANSCRIPTION_FAILED",
                    "retry_count": current_retry,
                    "max_retries": MAX_RETRIES,
                    "prompt_audio_url": prompt_audio_url,
                }
            ),
        }

    # Determine next field
    next_field = _get_next_field(current_field)

    # Build update expression for DynamoDB
    update_expr_parts = [
        "SET fields_collected.#actual_field = :value",
        "retry_counts.#field = :zero",
    ]
    expr_attr_names = {
        "#actual_field": actual_field_name,
        "#field": current_field,
    }
    expr_attr_values = {
        ":value": cleaned_value,
        ":zero": 0,
    }

    if next_field:
        update_expr_parts.append("current_field = :next_field")
        expr_attr_values[":next_field"] = next_field
    else:
        update_expr_parts.append("current_field = :null_val")
        update_expr_parts.append("#status = :complete_status")
        expr_attr_names["#status"] = "status"
        expr_attr_values[":null_val"] = None
        expr_attr_values[":complete_status"] = "fields_complete"

    try:
        table.update_item(
            Key={"PK": session_pk(session_id), "SK": "METADATA"},
            UpdateExpression=", ".join(update_expr_parts),
            ExpressionAttributeNames=expr_attr_names,
            ExpressionAttributeValues=expr_attr_values,
        )
    except Exception:
        return error_response(
            message="Failed to update session",
            error_code="SERVICE_UNAVAILABLE",
            status_code=503,
        )

    # Calculate fields remaining
    if next_field:
        next_idx = FIELD_ORDER.index(next_field)
        fields_remaining = FIELD_ORDER[next_idx + 1 :]
    else:
        fields_remaining = []

    # Generate next prompt audio if more fields remain
    next_prompt_audio_url = None
    if next_field:
        try:
            # Refresh session to get updated fields_collected for person prompt
            updated_session = _get_session(table, session_id)
            prompt_text = _get_prompt_for_field(next_field, updated_session)
            next_prompt_audio_url = _generate_prompt_audio(prompt_text)
        except Exception:
            return error_response(
                message="Failed to generate next prompt audio",
                error_code="SERVICE_UNAVAILABLE",
                status_code=503,
            )

    response_data = {
        "field_name": current_field,
        "field_value": cleaned_value,
        "next_prompt_audio_url": next_prompt_audio_url,
        "current_field": next_field,
        "fields_remaining": fields_remaining,
        "status": "in_progress" if next_field else "fields_complete",
    }

    return success_response(response_data)
