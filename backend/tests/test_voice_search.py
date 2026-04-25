"""Unit tests for the voice_search Lambda handler."""

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.voice.voice_search import handler, _execute_search, _strip_keys


def _make_event(body=None):
    """Build a minimal API Gateway event."""
    if body is not None:
        return {"body": json.dumps(body)}
    return {"body": "{}"}


def _mock_transcribe_success(mock_boto3, mock_time, mock_get_table, transcribed_text):
    """Set up mocks for a successful transcription flow.

    Returns (mock_transcribe, mock_s3, mock_polly, mock_table) clients.
    """
    mock_time.sleep = MagicMock()

    mock_transcribe = MagicMock()
    mock_s3 = MagicMock()
    mock_polly = MagicMock()
    mock_table = MagicMock()
    mock_get_table.return_value = mock_table

    def client_factory(service, **kwargs):
        if service == "transcribe":
            return mock_transcribe
        if service == "s3":
            return mock_s3
        if service == "polly":
            return mock_polly
        return MagicMock()

    mock_boto3.client.side_effect = client_factory

    # Transcribe succeeds immediately
    mock_transcribe.start_transcription_job.return_value = {}
    mock_transcribe.get_transcription_job.return_value = {
        "TranscriptionJob": {
            "TranscriptionJobStatus": "COMPLETED",
            "Transcript": {
                "TranscriptFileUri": "s3://memo-tracker-audio/output.json"
            },
        }
    }

    # S3 returns transcript content
    transcript_content = {
        "results": {"transcripts": [{"transcript": transcribed_text}]}
    }
    mock_body = MagicMock()
    mock_body.read.return_value = json.dumps(transcript_content).encode("utf-8")
    mock_s3.get_object.return_value = {"Body": mock_body}

    # Polly returns audio
    mock_audio_stream = MagicMock()
    mock_audio_stream.read.return_value = b"fake-audio-bytes"
    mock_polly.synthesize_speech.return_value = {"AudioStream": mock_audio_stream}

    # S3 presigned URL
    mock_s3.generate_presigned_url.return_value = (
        "https://s3.amazonaws.com/memo-tracker-audio/audio/polly/test.mp3"
    )

    return mock_transcribe, mock_s3, mock_polly, mock_table


class TestVoiceSearchSuccess:
    """Tests for the successful voice search flow."""

    @patch("backend.voice.voice_search.get_table")
    @patch("backend.voice.voice_search.boto3")
    @patch("backend.voice.voice_search.time")
    def test_successful_voice_search(self, mock_time, mock_boto3, mock_get_table):
        """A valid audio_key with parseable query should return results and audio URL."""
        mock_transcribe, mock_s3, mock_polly, mock_table = (
            _mock_transcribe_success(
                mock_boto3, mock_time, mock_get_table, "Show incoming memos"
            )
        )

        # DynamoDB query returns memos
        mock_table.query.return_value = {
            "Items": [
                {
                    "PK": "MEMO#123",
                    "SK": "METADATA",
                    "GSI1PK": "TYPE#incoming",
                    "GSI1SK": "DATE#2024-01-15",
                    "GSI2PK": "PERSON#jane doe",
                    "GSI2SK": "DATE#2024-01-15",
                    "entity_type": "MEMO",
                    "memo_id": "123",
                    "title": "Budget Report",
                    "memo_type": "incoming",
                    "memo_date": "2024-01-15",
                }
            ]
        }

        event = _make_event({"audio_key": "audio/transcribe/test.wav"})
        result = handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["transcribed_text"] == "Show incoming memos"
        assert len(body["search_results"]) == 1
        assert body["search_results"][0]["memo_id"] == "123"
        assert body["search_results"][0]["title"] == "Budget Report"
        assert "audio_response_url" in body
        assert body["audio_response_url"].startswith("https://")

        # Verify key attributes are stripped from results
        assert "PK" not in body["search_results"][0]
        assert "SK" not in body["search_results"][0]
        assert "GSI1PK" not in body["search_results"][0]

    @patch("backend.voice.voice_search.get_table")
    @patch("backend.voice.voice_search.boto3")
    @patch("backend.voice.voice_search.time")
    def test_empty_search_results_returns_200(self, mock_time, mock_boto3, mock_get_table):
        """When search finds no memos, should return 200 with empty array."""
        mock_transcribe, mock_s3, mock_polly, mock_table = (
            _mock_transcribe_success(
                mock_boto3, mock_time, mock_get_table, "Show outgoing memos"
            )
        )

        # DynamoDB query returns no items
        mock_table.query.return_value = {"Items": []}

        event = _make_event({"audio_key": "audio/transcribe/test.wav"})
        result = handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["transcribed_text"] == "Show outgoing memos"
        assert body["search_results"] == []
        assert "audio_response_url" in body


class TestVoiceSearchValidation:
    """Tests for request validation."""

    def test_missing_audio_key_returns_400(self):
        """Request without audio_key should return 400 VALIDATION_ERROR."""
        event = _make_event({})
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"
        assert "audio_key" in body["error"]

    def test_empty_audio_key_returns_400(self):
        """Request with empty audio_key should return 400."""
        event = _make_event({"audio_key": ""})
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_whitespace_audio_key_returns_400(self):
        """Request with whitespace-only audio_key should return 400."""
        event = _make_event({"audio_key": "   "})
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_invalid_body_returns_400(self):
        """Request with non-JSON body should return 400."""
        event = {"body": "not-json"}
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_null_body_returns_400(self):
        """Request with null body should return 400."""
        event = {"body": None}
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"


class TestVoiceSearchQueryParseFailed:
    """Tests for unparseable voice queries."""

    @patch("backend.voice.voice_search.get_table")
    @patch("backend.voice.voice_search.boto3")
    @patch("backend.voice.voice_search.time")
    def test_unparseable_query_returns_422(self, mock_time, mock_boto3, mock_get_table):
        """When transcribed text cannot be parsed, should return 422 with transcribed_text."""
        _mock_transcribe_success(mock_boto3, mock_time, mock_get_table, "hello world")

        event = _make_event({"audio_key": "audio/transcribe/test.wav"})
        result = handler(event, None)

        assert result["statusCode"] == 422
        body = json.loads(result["body"])
        assert body["error_code"] == "QUERY_PARSE_FAILED"
        assert body["details"]["transcribed_text"] == "hello world"


class TestVoiceSearchTranscriptionFailure:
    """Tests for transcription failure scenarios."""

    @patch("backend.voice.voice_search.boto3")
    @patch("backend.voice.voice_search.time")
    def test_transcription_failure_returns_422(self, mock_time, mock_boto3):
        """When Transcribe job fails, handler should return 422."""
        mock_time.sleep = MagicMock()

        mock_transcribe = MagicMock()

        def client_factory(service, **kwargs):
            if service == "transcribe":
                return mock_transcribe
            return MagicMock()

        mock_boto3.client.side_effect = client_factory

        mock_transcribe.start_transcription_job.return_value = {}
        mock_transcribe.get_transcription_job.return_value = {
            "TranscriptionJob": {
                "TranscriptionJobStatus": "FAILED",
                "FailureReason": "Audio format not supported",
            }
        }

        event = _make_event({"audio_key": "audio/bad-file.wav"})
        result = handler(event, None)

        assert result["statusCode"] == 422
        body = json.loads(result["body"])
        assert body["error_code"] == "TRANSCRIPTION_FAILED"

    @patch("backend.voice.voice_search.boto3")
    def test_start_job_exception_returns_422(self, mock_boto3):
        """When StartTranscriptionJob throws, handler should return 422."""
        mock_transcribe = MagicMock()
        mock_transcribe.start_transcription_job.side_effect = Exception("AWS error")
        mock_boto3.client.return_value = mock_transcribe

        event = _make_event({"audio_key": "audio/test.wav"})
        result = handler(event, None)

        assert result["statusCode"] == 422
        body = json.loads(result["body"])
        assert body["error_code"] == "TRANSCRIPTION_FAILED"


class TestVoiceSearchByType:
    """Tests for search by memo type."""

    @patch("backend.voice.voice_search.get_table")
    @patch("backend.voice.voice_search.boto3")
    @patch("backend.voice.voice_search.time")
    def test_search_by_memo_type(self, mock_time, mock_boto3, mock_get_table):
        """Searching by memo type should query GSI1 and return matching memos."""
        mock_transcribe, mock_s3, mock_polly, mock_table = (
            _mock_transcribe_success(
                mock_boto3, mock_time, mock_get_table, "Show incoming memos"
            )
        )

        mock_table.query.return_value = {
            "Items": [
                {
                    "PK": "MEMO#1",
                    "SK": "METADATA",
                    "GSI1PK": "TYPE#incoming",
                    "GSI1SK": "DATE#2024-01-15",
                    "entity_type": "MEMO",
                    "memo_id": "1",
                    "title": "Budget Report",
                    "memo_type": "incoming",
                },
                {
                    "PK": "MEMO#2",
                    "SK": "METADATA",
                    "GSI1PK": "TYPE#incoming",
                    "GSI1SK": "DATE#2024-02-10",
                    "entity_type": "MEMO",
                    "memo_id": "2",
                    "title": "Policy Update",
                    "memo_type": "incoming",
                },
            ]
        }

        event = _make_event({"audio_key": "audio/test.wav"})
        result = handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert len(body["search_results"]) == 2
        assert all(m["memo_type"] == "incoming" for m in body["search_results"])

        # Verify GSI1 was queried
        mock_table.query.assert_called_once()
        call_kwargs = mock_table.query.call_args[1]
        assert call_kwargs["IndexName"] == "GSI1"


class TestVoiceSearchByTitle:
    """Tests for search by title."""

    @patch("backend.voice.voice_search.get_table")
    @patch("backend.voice.voice_search.boto3")
    @patch("backend.voice.voice_search.time")
    def test_search_by_title(self, mock_time, mock_boto3, mock_get_table):
        """Searching by title should scan the table with a contains filter."""
        mock_transcribe, mock_s3, mock_polly, mock_table = (
            _mock_transcribe_success(
                mock_boto3, mock_time, mock_get_table, "Find memos about budget"
            )
        )

        mock_table.scan.return_value = {
            "Items": [
                {
                    "PK": "MEMO#1",
                    "SK": "METADATA",
                    "entity_type": "MEMO",
                    "memo_id": "1",
                    "title": "Budget Report Q3",
                    "memo_type": "incoming",
                }
            ]
        }

        event = _make_event({"audio_key": "audio/test.wav"})
        result = handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert len(body["search_results"]) == 1
        assert body["search_results"][0]["title"] == "Budget Report Q3"

        # Verify scan was used (not query)
        mock_table.scan.assert_called_once()


class TestExecuteSearch:
    """Tests for the _execute_search helper function."""

    def test_strip_keys_removes_internal_attributes(self):
        """_strip_keys should remove PK, SK, GSI keys, and entity_type."""
        item = {
            "PK": "MEMO#123",
            "SK": "METADATA",
            "GSI1PK": "TYPE#incoming",
            "GSI1SK": "DATE#2024-01-15",
            "GSI2PK": "PERSON#jane",
            "GSI2SK": "DATE#2024-01-15",
            "entity_type": "MEMO",
            "memo_id": "123",
            "title": "Test Memo",
        }
        result = _strip_keys(item)
        assert "PK" not in result
        assert "SK" not in result
        assert "GSI1PK" not in result
        assert "entity_type" not in result
        assert result["memo_id"] == "123"
        assert result["title"] == "Test Memo"
