"""Unit tests for the synthesize_speech Lambda handler."""

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.voice.synthesize_speech import handler


def _make_event(body=None):
    """Build a minimal API Gateway event."""
    if body is not None:
        return {"body": json.dumps(body)}
    return {"body": "{}"}


class TestSynthesizeSpeechSuccess:
    """Tests for the successful synthesis flow."""

    @patch("backend.voice.synthesize_speech.boto3")
    def test_successful_synthesis(self, mock_boto3):
        """A valid text input should synthesize speech, upload to S3, and return a presigned URL."""
        mock_polly = MagicMock()
        mock_s3 = MagicMock()

        def client_factory(service, **kwargs):
            if service == "polly":
                return mock_polly
            if service == "s3":
                return mock_s3
            return MagicMock()

        mock_boto3.client.side_effect = client_factory

        # Mock Polly response
        mock_audio_stream = MagicMock()
        mock_audio_stream.read.return_value = b"fake-audio-bytes"
        mock_polly.synthesize_speech.return_value = {
            "AudioStream": mock_audio_stream,
        }

        # Mock S3 presigned URL
        mock_s3.generate_presigned_url.return_value = (
            "https://s3.amazonaws.com/memo-tracker-audio/audio/polly/test.mp3"
        )

        event = _make_event({"text": "Hello, this is a test."})
        result = handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "audio_url" in body
        assert "request_id" in body
        assert body["audio_url"].startswith("https://")

        # Verify Polly was called correctly
        mock_polly.synthesize_speech.assert_called_once_with(
            Text="Hello, this is a test.",
            OutputFormat="mp3",
            VoiceId="Joanna",
        )

        # Verify S3 upload was called
        mock_s3.put_object.assert_called_once()
        put_call_kwargs = mock_s3.put_object.call_args[1]
        assert put_call_kwargs["Body"] == b"fake-audio-bytes"
        assert put_call_kwargs["ContentType"] == "audio/mpeg"
        assert put_call_kwargs["Key"].startswith("audio/polly/")
        assert put_call_kwargs["Key"].endswith(".mp3")

        # Verify presigned URL was generated
        mock_s3.generate_presigned_url.assert_called_once()


class TestSynthesizeSpeechValidation:
    """Tests for request validation."""

    def test_missing_text_returns_400(self):
        """Request without text should return 400 VALIDATION_ERROR."""
        event = _make_event({})
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"
        assert "text" in body["error"]

    def test_empty_text_returns_400(self):
        """Request with empty text should return 400."""
        event = _make_event({"text": ""})
        result = handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_whitespace_text_returns_400(self):
        """Request with whitespace-only text should return 400."""
        event = _make_event({"text": "   "})
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


class TestSynthesizeSpeechFailure:
    """Tests for service failure scenarios."""

    @patch("backend.voice.synthesize_speech.boto3")
    def test_polly_failure_returns_503(self, mock_boto3):
        """When Polly SynthesizeSpeech throws, handler should return 503."""
        mock_polly = MagicMock()
        mock_polly.synthesize_speech.side_effect = Exception("Polly service error")

        def client_factory(service, **kwargs):
            if service == "polly":
                return mock_polly
            return MagicMock()

        mock_boto3.client.side_effect = client_factory

        event = _make_event({"text": "Test speech"})
        result = handler(event, None)

        assert result["statusCode"] == 503
        body = json.loads(result["body"])
        assert body["error_code"] == "SERVICE_UNAVAILABLE"
        assert "synthesize" in body["error"].lower()

    @patch("backend.voice.synthesize_speech.boto3")
    def test_s3_upload_failure_returns_503(self, mock_boto3):
        """When S3 upload fails, handler should return 503."""
        mock_polly = MagicMock()
        mock_s3 = MagicMock()

        def client_factory(service, **kwargs):
            if service == "polly":
                return mock_polly
            if service == "s3":
                return mock_s3
            return MagicMock()

        mock_boto3.client.side_effect = client_factory

        # Polly succeeds
        mock_audio_stream = MagicMock()
        mock_audio_stream.read.return_value = b"fake-audio-bytes"
        mock_polly.synthesize_speech.return_value = {
            "AudioStream": mock_audio_stream,
        }

        # S3 upload fails
        mock_s3.put_object.side_effect = Exception("S3 upload error")

        event = _make_event({"text": "Test speech"})
        result = handler(event, None)

        assert result["statusCode"] == 503
        body = json.loads(result["body"])
        assert body["error_code"] == "SERVICE_UNAVAILABLE"
        assert "s3" in body["error"].lower() or "upload" in body["error"].lower()
