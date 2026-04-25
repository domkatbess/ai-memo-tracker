"""Lambda handler for text-to-speech synthesis via AWS Polly."""

import json
import uuid

import boto3

from backend.shared.config import AUDIO_BUCKET, AWS_REGION
from backend.shared.response import error_response, success_response


def handler(event, context):
    """Synthesize speech from text using AWS Polly.

    Request body:
        text (str): The text to convert to speech.

    Returns:
        200: {"audio_url": str, "request_id": str}
        400: VALIDATION_ERROR if text is missing or empty
        503: SERVICE_UNAVAILABLE if Polly or S3 fails
    """
    try:
        body = json.loads(event.get("body", "{}"))
    except (json.JSONDecodeError, TypeError):
        return error_response(
            message="Invalid request body",
            error_code="VALIDATION_ERROR",
            status_code=400,
        )

    text = body.get("text")
    if not text or not isinstance(text, str) or not text.strip():
        return error_response(
            message="Missing or invalid request field: text",
            error_code="VALIDATION_ERROR",
            status_code=400,
        )

    request_id = str(uuid.uuid4())
    s3_key = f"audio/polly/{request_id}.mp3"

    try:
        polly_client = boto3.client("polly", region_name=AWS_REGION)
        response = polly_client.synthesize_speech(
            Text=text,
            OutputFormat="mp3",
            VoiceId="Joanna",
        )
        audio_stream = response["AudioStream"].read()
    except Exception:
        return error_response(
            message="Failed to synthesize speech",
            error_code="SERVICE_UNAVAILABLE",
            status_code=503,
        )

    try:
        s3_client = boto3.client("s3", region_name=AWS_REGION)
        s3_client.put_object(
            Bucket=AUDIO_BUCKET,
            Key=s3_key,
            Body=audio_stream,
            ContentType="audio/mpeg",
        )
        audio_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": AUDIO_BUCKET, "Key": s3_key},
            ExpiresIn=3600,
        )
    except Exception:
        return error_response(
            message="Failed to upload audio to S3",
            error_code="SERVICE_UNAVAILABLE",
            status_code=503,
        )

    return success_response({"audio_url": audio_url, "request_id": request_id})
