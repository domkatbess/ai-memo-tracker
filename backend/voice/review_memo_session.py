"""Lambda handler for reviewing collected fields in a voice-guided memo registration session."""

import uuid

import boto3

from backend.shared.config import AUDIO_BUCKET, AWS_REGION
from backend.shared.dynamodb import get_table, session_pk
from backend.shared.response import error_response, success_response

REVIEW_TEMPLATE = (
    "Here is what I have recorded. "
    "Title: {title}. "
    "Type: {memo_type}. "
    "Date: {memo_date}. "
    "{person_field}: {person_name}. "
    "Would you like to save this memo? Please say yes or no."
)

SESSION_TTL_SECONDS = 3600


def _get_session(table, session_id):
    """Retrieve a voice session from DynamoDB by session_id."""
    response = table.get_item(
        Key={"PK": session_pk(session_id), "SK": "METADATA"}
    )
    return response.get("Item")


def _validate_session_fields(fields_collected):
    """Check that all required fields have been collected.

    Returns True if the session is complete, False otherwise.
    The required fields are title, memo_type, memo_date, and the
    appropriate person field based on memo_type.
    """
    title = fields_collected.get("title")
    memo_type = fields_collected.get("memo_type")
    memo_date = fields_collected.get("memo_date")

    if not title or not memo_type or not memo_date:
        return False

    if memo_type == "incoming":
        return bool(fields_collected.get("person_brought_in"))
    else:
        return bool(fields_collected.get("person_took_out"))


def _format_review_text(fields_collected):
    """Format the review summary text from collected fields."""
    memo_type = fields_collected.get("memo_type")

    if memo_type == "incoming":
        person_field = "Person who brought in"
        person_name = fields_collected.get("person_brought_in")
    else:
        person_field = "Person who took out"
        person_name = fields_collected.get("person_took_out")

    return REVIEW_TEMPLATE.format(
        title=fields_collected.get("title"),
        memo_type=memo_type,
        memo_date=fields_collected.get("memo_date"),
        person_field=person_field,
        person_name=person_name,
    )


def handler(event, context):
    """Generate a review audio summary of all collected fields for user review.

    Retrieves the session, validates all fields are collected, formats a
    review summary, generates audio via Polly, and returns the audio URL
    along with the collected data.
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

    # Format review summary text
    review_text = _format_review_text(fields_collected)

    # Generate review audio via Polly
    request_id = str(uuid.uuid4())
    s3_key = f"audio/polly/{request_id}.mp3"

    try:
        polly_client = boto3.client("polly", region_name=AWS_REGION)
        polly_response = polly_client.synthesize_speech(
            Text=review_text,
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

        review_audio_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": AUDIO_BUCKET, "Key": s3_key},
            ExpiresIn=SESSION_TTL_SECONDS,
        )
    except Exception:
        return error_response(
            message="Failed to generate review audio",
            error_code="SERVICE_UNAVAILABLE",
            status_code=503,
        )

    # Build collected_data from fields_collected
    collected_data = {
        "title": fields_collected.get("title"),
        "memo_type": fields_collected.get("memo_type"),
        "memo_date": fields_collected.get("memo_date"),
        "person_brought_in": fields_collected.get("person_brought_in"),
        "person_took_out": fields_collected.get("person_took_out"),
    }

    return success_response({
        "review_audio_url": review_audio_url,
        "collected_data": collected_data,
    })
