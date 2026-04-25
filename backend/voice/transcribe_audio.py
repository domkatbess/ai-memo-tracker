"""Lambda handler for audio transcription via AWS Transcribe."""

import json
import time
import uuid

import boto3

from backend.shared.config import AUDIO_BUCKET, AWS_REGION
from backend.shared.response import error_response, success_response


POLL_INTERVAL = 2  # seconds between polling attempts
POLL_TIMEOUT = 60  # maximum seconds to wait for transcription


def handler(event, context):
    """Transcribe audio from S3 using AWS Transcribe batch job.

    Request body:
        audio_key (str): S3 key of the uploaded audio file.

    Returns:
        200: {"transcribed_text": str}
        400: VALIDATION_ERROR if audio_key is missing
        422: TRANSCRIPTION_FAILED if transcription fails or times out
    """
    try:
        body = json.loads(event.get("body", "{}"))
    except (json.JSONDecodeError, TypeError):
        body = {}

    audio_key = body.get("audio_key")
    if not audio_key or not isinstance(audio_key, str) or not audio_key.strip():
        return error_response(
            message="Missing or invalid request field: audio_key",
            error_code="VALIDATION_ERROR",
            status_code=400,
        )

    job_name = f"transcribe-{uuid.uuid4()}"
    media_uri = f"s3://{AUDIO_BUCKET}/{audio_key}"

    transcribe_client = boto3.client("transcribe", region_name=AWS_REGION)

    try:
        transcribe_client.start_transcription_job(
            TranscriptionJobName=job_name,
            LanguageCode="en-US",
            Media={"MediaFileUri": media_uri},
            OutputBucketName=AUDIO_BUCKET,
        )
    except Exception:
        return error_response(
            message="Failed to start transcription job",
            error_code="TRANSCRIPTION_FAILED",
            status_code=422,
        )

    # Poll for job completion
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        try:
            response = transcribe_client.get_transcription_job(
                TranscriptionJobName=job_name
            )
        except Exception:
            return error_response(
                message="Failed to retrieve transcription job status",
                error_code="TRANSCRIPTION_FAILED",
                status_code=422,
            )

        status = response["TranscriptionJob"]["TranscriptionJobStatus"]

        if status == "COMPLETED":
            transcript_uri = (
                response["TranscriptionJob"]
                .get("Transcript", {})
                .get("TranscriptFileUri", "")
            )
            transcribed_text = _fetch_transcript(transcript_uri)
            if transcribed_text is None:
                return error_response(
                    message="Failed to retrieve transcription result",
                    error_code="TRANSCRIPTION_FAILED",
                    status_code=422,
                )
            return success_response({"transcribed_text": transcribed_text})

        if status == "FAILED":
            failure_reason = response["TranscriptionJob"].get(
                "FailureReason", "Unknown error"
            )
            return error_response(
                message=f"Transcription failed: {failure_reason}",
                error_code="TRANSCRIPTION_FAILED",
                status_code=422,
            )

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    # Timeout
    return error_response(
        message="Transcription timed out",
        error_code="TRANSCRIPTION_FAILED",
        status_code=422,
    )


def _fetch_transcript(transcript_uri):
    """Fetch and parse the transcript text from the Transcribe output.

    Args:
        transcript_uri: URI of the transcript JSON file.

    Returns:
        The transcribed text string, or None on failure.
    """
    try:
        s3_client = boto3.client("s3", region_name=AWS_REGION)
        # Parse the S3 URI from the transcript URI
        # URI format: https://s3.<region>.amazonaws.com/<bucket>/<key>
        # or s3://<bucket>/<key>
        if transcript_uri.startswith("s3://"):
            parts = transcript_uri.replace("s3://", "").split("/", 1)
            bucket = parts[0]
            key = parts[1]
        elif "s3.amazonaws.com" in transcript_uri or "s3." in transcript_uri:
            # https://s3.<region>.amazonaws.com/<bucket>/<key>
            from urllib.parse import urlparse

            parsed = urlparse(transcript_uri)
            path_parts = parsed.path.lstrip("/").split("/", 1)
            bucket = path_parts[0]
            key = path_parts[1]
        else:
            return None

        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = json.loads(response["Body"].read().decode("utf-8"))
        transcripts = content.get("results", {}).get("transcripts", [])
        if transcripts:
            return transcripts[0].get("transcript", "")
        return ""
    except Exception:
        return None
