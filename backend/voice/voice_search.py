"""Lambda handler for voice-based memo search.

Accepts an audio_key, transcribes the audio, parses the transcribed text
into search parameters, executes the search against DynamoDB, synthesizes
a results summary via Polly, and returns the search results with an audio
response URL.
"""

import json
import time
import uuid

import boto3
from boto3.dynamodb.conditions import Attr, Key

from backend.shared.config import AUDIO_BUCKET, AWS_REGION, TABLE_NAME
from backend.shared.dynamodb import (
    get_table,
    gsi1_date_sk,
    gsi1_type_pk,
    gsi2_person_pk,
)
from backend.shared.response import error_response, success_response
from backend.voice.query_parser import parse_voice_query


POLL_INTERVAL = 2  # seconds between polling attempts
POLL_TIMEOUT = 60  # maximum seconds to wait for transcription

# DynamoDB key attributes to strip from search results
_KEY_ATTRIBUTES = {"PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "entity_type"}


def handler(event, context):
    """Handle voice search requests.

    Request body:
        audio_key (str): S3 key of the uploaded audio file.

    Returns:
        200: { transcribed_text, search_results[], audio_response_url }
        400: VALIDATION_ERROR if audio_key is missing
        422: QUERY_PARSE_FAILED if query cannot be parsed
        422: TRANSCRIPTION_FAILED if transcription fails
        503: SERVICE_UNAVAILABLE if AWS service fails
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

    # Step 1: Transcribe the audio
    transcribed_text = _transcribe_audio(audio_key)
    if transcribed_text is None:
        return error_response(
            message="Failed to transcribe audio",
            error_code="TRANSCRIPTION_FAILED",
            status_code=422,
        )

    # Step 2: Parse the transcribed text into search parameters
    search_params = parse_voice_query(transcribed_text)
    if not search_params:
        return error_response(
            message="Could not parse search query",
            error_code="QUERY_PARSE_FAILED",
            status_code=422,
            details={"transcribed_text": transcribed_text},
        )

    # Step 3: Execute search against DynamoDB
    table = get_table()
    search_results = _execute_search(search_params, table)

    # Step 4: Synthesize results summary via Polly
    summary_text = _build_results_summary(search_results, search_params)
    audio_response_url = _synthesize_and_upload(summary_text)

    return success_response(
        {
            "transcribed_text": transcribed_text,
            "search_results": search_results,
            "audio_response_url": audio_response_url,
        }
    )


def _transcribe_audio(audio_key):
    """Transcribe audio from S3 using AWS Transcribe batch job.

    Args:
        audio_key: S3 key of the audio file.

    Returns:
        The transcribed text string, or None on failure.
    """
    job_name = f"voice-search-{uuid.uuid4()}"
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
        return None

    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        try:
            response = transcribe_client.get_transcription_job(
                TranscriptionJobName=job_name
            )
        except Exception:
            return None

        status = response["TranscriptionJob"]["TranscriptionJobStatus"]

        if status == "COMPLETED":
            transcript_uri = (
                response["TranscriptionJob"]
                .get("Transcript", {})
                .get("TranscriptFileUri", "")
            )
            return _fetch_transcript(transcript_uri)

        if status == "FAILED":
            return None

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    return None


def _fetch_transcript(transcript_uri):
    """Fetch and parse the transcript text from the Transcribe output.

    Args:
        transcript_uri: URI of the transcript JSON file.

    Returns:
        The transcribed text string, or None on failure.
    """
    try:
        s3_client = boto3.client("s3", region_name=AWS_REGION)

        if transcript_uri.startswith("s3://"):
            parts = transcript_uri.replace("s3://", "").split("/", 1)
            bucket = parts[0]
            key = parts[1]
        elif "s3.amazonaws.com" in transcript_uri or "s3." in transcript_uri:
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


def _execute_search(params, table):
    """Execute a DynamoDB search based on parsed voice query parameters.

    Supports the following search strategies:
    - title: Full table scan with case-insensitive contains filter
    - type + date: GSI1 query with date range
    - person + date: GSI2 query with date range
    - type only: GSI1 query
    - person only: GSI2 query

    Args:
        params: Dict of search parameters from parse_voice_query.
        table: DynamoDB Table resource.

    Returns:
        List of memo dicts with internal key attributes stripped.
    """
    title = params.get("title")
    memo_type = params.get("memo_type")
    person_name = params.get("person_name")
    date_from = params.get("date_from")
    date_to = params.get("date_to")

    try:
        if title:
            # Title search: full table scan with case-insensitive contains
            return _scan_by_title(table, title)

        if memo_type and date_from and date_to:
            # Type + date range: query GSI1
            return _query_gsi1(table, memo_type, date_from, date_to)

        if person_name and date_from and date_to:
            # Person + date range: query GSI2
            return _query_gsi2(table, person_name, date_from, date_to)

        if memo_type:
            # Type only: query GSI1 without date range
            return _query_gsi1(table, memo_type)

        if person_name:
            # Person only: query GSI2 without date range
            return _query_gsi2(table, person_name)

        return []
    except Exception:
        return []


def _scan_by_title(table, title):
    """Scan the table for memos whose title contains the search term.

    Args:
        table: DynamoDB Table resource.
        title: Search term for title matching.

    Returns:
        List of matching memo dicts.
    """
    scan_kwargs = {
        "FilterExpression": Attr("SK").eq("METADATA")
        & Attr("title").contains(title.lower()),
    }
    items = []
    response = table.scan(**scan_kwargs)
    items.extend(response.get("Items", []))

    while "LastEvaluatedKey" in response:
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        response = table.scan(**scan_kwargs)
        items.extend(response.get("Items", []))

    return [_strip_keys(item) for item in items]


def _query_gsi1(table, memo_type, date_from=None, date_to=None):
    """Query GSI1 for memos by type, optionally filtered by date range.

    Args:
        table: DynamoDB Table resource.
        memo_type: Memo type ("incoming" or "outgoing").
        date_from: Optional start date (ISO 8601).
        date_to: Optional end date (ISO 8601).

    Returns:
        List of matching memo dicts.
    """
    key_condition = Key("GSI1PK").eq(gsi1_type_pk(memo_type))

    if date_from and date_to:
        key_condition = key_condition & Key("GSI1SK").between(
            gsi1_date_sk(date_from), gsi1_date_sk(date_to)
        )

    response = table.query(IndexName="GSI1", KeyConditionExpression=key_condition)
    items = response.get("Items", [])

    while "LastEvaluatedKey" in response:
        response = table.query(
            IndexName="GSI1",
            KeyConditionExpression=key_condition,
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    return [_strip_keys(item) for item in items]


def _query_gsi2(table, person_name, date_from=None, date_to=None):
    """Query GSI2 for memos by person name, optionally filtered by date range.

    Args:
        table: DynamoDB Table resource.
        person_name: Person name to search for.
        date_from: Optional start date (ISO 8601).
        date_to: Optional end date (ISO 8601).

    Returns:
        List of matching memo dicts.
    """
    key_condition = Key("GSI2PK").eq(gsi2_person_pk(person_name.lower()))

    if date_from and date_to:
        key_condition = key_condition & Key("GSI2SK").between(
            gsi1_date_sk(date_from), gsi1_date_sk(date_to)
        )

    response = table.query(IndexName="GSI2", KeyConditionExpression=key_condition)
    items = response.get("Items", [])

    while "LastEvaluatedKey" in response:
        response = table.query(
            IndexName="GSI2",
            KeyConditionExpression=key_condition,
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    return [_strip_keys(item) for item in items]


def _strip_keys(item):
    """Remove internal DynamoDB key attributes from a memo item.

    Args:
        item: DynamoDB item dict.

    Returns:
        Dict with key attributes removed.
    """
    return {k: v for k, v in item.items() if k not in _KEY_ATTRIBUTES}


def _build_results_summary(results, params):
    """Build a human-readable summary of search results.

    Args:
        results: List of memo result dicts.
        params: The parsed search parameters.

    Returns:
        Summary text string.
    """
    count = len(results)
    if count == 0:
        return "No memos found matching your query."

    if count == 1:
        return "Found 1 memo matching your query."

    return f"Found {count} memos matching your query."


def _synthesize_and_upload(text):
    """Synthesize speech from text via Polly and upload to S3.

    Args:
        text: Text to synthesize.

    Returns:
        Presigned URL for the audio file, or empty string on failure.
    """
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
        return ""

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
        return audio_url
    except Exception:
        return ""
