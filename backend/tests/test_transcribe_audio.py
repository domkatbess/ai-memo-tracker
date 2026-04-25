"""Unit tests for the transcribe_audio Lambda handler."""

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.voice.transcribe_audio import handler


def _make_event(body=None):
    """Build a minimal API Gateway event."""
    if body is not None:
        return {"body": json.dumps(body)}
    return {"body": "{}"}


class TestTranscribeAudioSuccess:
    """Tests for the successful transcription flow."""

    @patch("backend.voice.transcribe_audio.boto3")
    @patch("backend.voice.transcribe_audio.time")
    def test_successful_transcription(self, mock_time, mock_boto3):
        """A valid audio_key should start a job, poll, and return text."""
        mock_time.sleep = MagicMock()

        # Mock Transcribe client
        mock_transcribe = MagicMock()
        mock_s3 = MagicMock()

        def client_factory(service, **kwargs):
            if service == "transcribe":
                return mock_transcribe
            if service == "s3":
                return mock_s3
            return MagicMock()

        mock_boto3.client.side_effect = client_factory

        # StartTranscriptionJob succeeds
        mock_transcribe.start_transcription_job.return_value = {}

        # GetTranscriptionJob returns COMPLETED on first poll
        mock_transcribe.get_transcription_job.return_value = {
            "TranscriptionJob": {
                "TranscriptionJobStatus": "COMPLETED",
                "Transcript": {
                    "TranscriptFileUri": "s3://memo-tracker-audio/output.json"
                },
            }
        }

        # Mock S3 get_object for transcript fetch
        transcript_content = {
            "results": {
                "transcripts": [{"transcript": "Hello this is a test memo"}]
            }
        }
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(transcript_content).encode("utf-8")
        mock_s3.get_object.return_value = {"Body": mock_body}

        event = _make_event({"audio_key": "audio/transcribe/test-input.wav"})
        result = handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["transcribed_text"] == "Hello this is a test memo"
        mock_transcribe.start_transcription_job.assert_called_once()

    @patch("backend.voice.transcribe_audio.boto3")
    @patch("backend.voice.transcribe_audio.time")
    def test_transcription_polls_until_complete(self, mock_time, mock_boto3):
        """Handler should poll when job is IN_PROGRESS before COMPLETED."""
        mock_time.sleep = MagicMock()

        mock_transcribe = MagicMock()
        mock_s3 = MagicMock()

        def client_factory(service, **kwargs):
            if service == "transcribe":
                return mock_transcribe
            if service == "s3":
                return mock_s3
            return MagicMock()

        mock_boto3.client.side_effect = client_factory
        mock_transcribe.start_transcription_job.return_value = {}

        # First call: IN_PROGRESS, second call: COMPLETED
        mock_transcribe.get_transcription_job.side_effect = [
            {
                "TranscriptionJob": {
                    "TranscriptionJobStatus": "IN_PROGRESS",
                }
            },
            {
                "TranscriptionJob": {
                    "TranscriptionJobStatus": "COMPLETED",
                    "Transcript": {
                        "TranscriptFileUri": "s3://memo-tracker-audio/out.json"
                    },
                }
            },
        ]

        transcript_content = {
            "results": {"transcripts": [{"transcript": "Polled result"}]}
        }
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(transcript_content).encode("utf-8")
        mock_s3.get_object.return_value = {"Body": mock_body}

        event = _make_event({"audio_key": "audio/test.wav"})
        result = handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["transcribed_text"] == "Polled result"
        assert mock_transcribe.get_transcription_job.call_count == 2


class TestTranscribeAudioValidation:
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


class TestTranscribeAudioFailure:
    """Tests for transcription failure scenarios."""

    @patch("backend.voice.transcribe_audio.boto3")
    @patch("backend.voice.transcribe_audio.time")
    def test_failed_transcription_returns_422(self, mock_time, mock_boto3):
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
        assert "Audio format not supported" in body["error"]

    @patch("backend.voice.transcribe_audio.boto3")
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

    @patch("backend.voice.transcribe_audio.POLL_TIMEOUT", 4)
    @patch("backend.voice.transcribe_audio.POLL_INTERVAL", 2)
    @patch("backend.voice.transcribe_audio.boto3")
    @patch("backend.voice.transcribe_audio.time")
    def test_timeout_returns_422(self, mock_time, mock_boto3):
        """When transcription exceeds timeout, handler should return 422."""
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
                "TranscriptionJobStatus": "IN_PROGRESS",
            }
        }

        event = _make_event({"audio_key": "audio/slow.wav"})
        result = handler(event, None)

        assert result["statusCode"] == 422
        body = json.loads(result["body"])
        assert body["error_code"] == "TRANSCRIPTION_FAILED"
        assert "timed out" in body["error"].lower()
