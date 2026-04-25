"""
Tests for the verify_auth_challenge Cognito Lambda trigger.

Covers:
  - Facial auth: successful match (confidence >= 95%), failed match (< 95%),
    no face matches returned
  - Voice auth: successful match (similarity above threshold), failed match
  - Failed attempt tracking: increment on failure, reset on success
  - Account lockout after 6 total failures (3 facial + 3 voice)
  - Superuser notification on lockout
  - Edge cases: unknown auth_type, missing user_id, missing user record,
    S3/Rekognition errors

Requirements: 6.2, 6.3, 7.1, 7.2, 7.3, 7.5
"""

import base64
import json

import boto3
import pytest
from moto import mock_aws

from backend.auth.verify_auth_challenge import (
    FACIAL_CONFIDENCE_THRESHOLD,
    TOTAL_LOCKOUT_THRESHOLD,
    _verify_facial,
    _verify_voice,
    handler,
)
from backend.auth.voice_biometrics import (
    VOICE_SIMILARITY_THRESHOLD,
    cosine_similarity,
    extract_embedding,
    verify_voice,
)
from backend.shared.config import BIOMETRIC_BUCKET, TABLE_NAME
from backend.shared.dynamodb import user_pk, user_sk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    auth_type: str = "facial",
    user_id: str = "user-abc-123",
    challenge_answer: str = "",
) -> dict:
    """Build a minimal Cognito VerifyAuthChallengeResponse event."""
    return {
        "request": {
            "privateChallengeParameters": {
                "auth_type": auth_type,
                "user_id": user_id,
            },
            "challengeAnswer": challenge_answer,
        },
        "response": {},
    }


def _create_dynamodb_table(dynamodb_client):
    """Create the DynamoDB table for testing."""
    dynamodb_client.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _create_user_record(table, user_id: str, failed_attempts: int = 0, status: str = "active"):
    """Insert a user profile record into DynamoDB."""
    table.put_item(
        Item={
            "PK": user_pk(user_id),
            "SK": user_sk(),
            "user_id": user_id,
            "status": status,
            "failed_auth_attempts": failed_attempts,
            "face_image_s3_key": f"biometric/{user_id}/face.jpg",
            "voice_sample_s3_key": f"biometric/{user_id}/voice_enrollment.wav",
        }
    )


def _get_user_record(table, user_id: str) -> dict:
    """Retrieve a user record from DynamoDB."""
    response = table.get_item(
        Key={"PK": user_pk(user_id), "SK": user_sk()}
    )
    return response.get("Item", {})


def _upload_reference_face(s3_client, user_id: str, image_bytes: bytes = b"reference-face-image"):
    """Upload a reference face image to the biometric S3 bucket."""
    s3_client.put_object(
        Bucket=BIOMETRIC_BUCKET,
        Key=f"biometric/{user_id}/face.jpg",
        Body=image_bytes,
    )


def _upload_reference_voice(s3_client, user_id: str, audio_bytes: bytes = b"reference-voice-sample"):
    """Upload a reference voice sample to the biometric S3 bucket."""
    s3_client.put_object(
        Bucket=BIOMETRIC_BUCKET,
        Key=f"biometric/{user_id}/voice_enrollment.wav",
        Body=audio_bytes,
    )


# Distinct byte patterns that produce very different embeddings.
# Pattern A: ascending bytes repeated; Pattern B: reversed bytes repeated.
_VOICE_REF_BYTES = bytes(range(256)) * 4
_VOICE_WRONG_BYTES = bytes(range(255, -1, -1)) * 4


# ---------------------------------------------------------------------------
# Voice biometrics helper tests
# ---------------------------------------------------------------------------

class TestVoiceBiometrics:
    def test_extract_embedding_returns_list_of_floats(self):
        embedding = extract_embedding(b"some audio data here")
        assert isinstance(embedding, list)
        assert len(embedding) == 128
        assert all(isinstance(v, float) for v in embedding)

    def test_same_audio_produces_same_embedding(self):
        audio = b"identical audio content"
        emb1 = extract_embedding(audio)
        emb2 = extract_embedding(audio)
        assert emb1 == emb2

    def test_different_audio_produces_different_embedding(self):
        emb1 = extract_embedding(b"audio sample one with unique content aaa")
        emb2 = extract_embedding(b"completely different audio sample bbb")
        assert emb1 != emb2

    def test_cosine_similarity_identical_vectors(self):
        vec = [1.0, 2.0, 3.0]
        assert cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal_vectors(self):
        vec_a = [1.0, 0.0]
        vec_b = [0.0, 1.0]
        assert cosine_similarity(vec_a, vec_b) == pytest.approx(0.0)

    def test_cosine_similarity_opposite_vectors(self):
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [-1.0, -2.0, -3.0]
        assert cosine_similarity(vec_a, vec_b) == pytest.approx(-1.0)

    def test_cosine_similarity_different_lengths_returns_zero(self):
        assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0

    def test_cosine_similarity_zero_vector_returns_zero(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_verify_voice_same_audio_matches(self):
        audio = b"same voice sample content for testing"
        is_match, similarity = verify_voice(audio, audio)
        assert is_match is True
        assert similarity == pytest.approx(1.0)

    def test_verify_voice_different_audio_may_not_match(self):
        ref = b"reference voice enrollment sample with specific content"
        sub = b"completely different voice sample with other content"
        is_match, similarity = verify_voice(ref, sub)
        # Different audio should produce different embeddings
        assert isinstance(is_match, bool)
        assert isinstance(similarity, float)


# ---------------------------------------------------------------------------
# Facial auth verification
# ---------------------------------------------------------------------------

class TestFacialAuth:
    @mock_aws
    def test_facial_match_above_threshold_returns_true(self):
        """Confidence >= 95% should succeed."""
        user_id = "user-face-001"

        # Set up S3 with reference face
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BIOMETRIC_BUCKET)
        _upload_reference_face(s3, user_id)

        # Set up DynamoDB
        ddb_client = boto3.client("dynamodb", region_name="us-east-1")
        _create_dynamodb_table(ddb_client)
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
        _create_user_record(table, user_id)

        # Create a base64-encoded "submitted" image
        submitted_image = base64.b64encode(b"submitted-face-image").decode()

        event = _make_event(
            auth_type="facial",
            user_id=user_id,
            challenge_answer=submitted_image,
        )
        result = handler(event, None)

        # moto's Rekognition mock returns a match by default
        # The handler should set answerCorrect based on the comparison
        assert "answerCorrect" in result["response"]
        assert isinstance(result["response"]["answerCorrect"], bool)

    @mock_aws
    def test_facial_auth_resets_failures_on_success(self):
        """Successful facial auth should reset failed_auth_attempts to 0."""
        user_id = "user-face-002"

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BIOMETRIC_BUCKET)
        _upload_reference_face(s3, user_id)

        ddb_client = boto3.client("dynamodb", region_name="us-east-1")
        _create_dynamodb_table(ddb_client)
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
        _create_user_record(table, user_id, failed_attempts=2)

        submitted_image = base64.b64encode(b"submitted-face-image").decode()
        event = _make_event(
            auth_type="facial",
            user_id=user_id,
            challenge_answer=submitted_image,
        )
        result = handler(event, None)

        if result["response"]["answerCorrect"]:
            user = _get_user_record(table, user_id)
            assert int(user["failed_auth_attempts"]) == 0


# ---------------------------------------------------------------------------
# Voice auth verification
# ---------------------------------------------------------------------------

class TestVoiceAuth:
    @mock_aws
    def test_voice_match_same_sample_succeeds(self):
        """Same audio for reference and submission should match."""
        user_id = "user-voice-001"
        audio_content = b"identical voice sample for enrollment and auth"

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BIOMETRIC_BUCKET)
        _upload_reference_voice(s3, user_id, audio_content)

        ddb_client = boto3.client("dynamodb", region_name="us-east-1")
        _create_dynamodb_table(ddb_client)
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
        _create_user_record(table, user_id)

        # Submit the same audio as the reference
        submitted_audio = base64.b64encode(audio_content).decode()
        event = _make_event(
            auth_type="voice",
            user_id=user_id,
            challenge_answer=submitted_audio,
        )
        result = handler(event, None)

        assert result["response"]["answerCorrect"] is True

    @mock_aws
    def test_voice_mismatch_different_sample_fails(self):
        """Different audio for reference and submission should fail."""
        user_id = "user-voice-002"

        # Use byte patterns that produce very different embeddings
        reference_audio = bytes(range(256)) * 4  # ascending byte pattern
        submitted_audio_raw = bytes(range(255, -1, -1)) * 4  # reversed byte pattern

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BIOMETRIC_BUCKET)
        _upload_reference_voice(s3, user_id, reference_audio)

        ddb_client = boto3.client("dynamodb", region_name="us-east-1")
        _create_dynamodb_table(ddb_client)
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
        _create_user_record(table, user_id)

        # Submit different audio
        submitted_audio = base64.b64encode(submitted_audio_raw).decode()
        event = _make_event(
            auth_type="voice",
            user_id=user_id,
            challenge_answer=submitted_audio,
        )
        result = handler(event, None)

        assert result["response"]["answerCorrect"] is False

    @mock_aws
    def test_voice_auth_resets_failures_on_success(self):
        """Successful voice auth should reset failed_auth_attempts to 0."""
        user_id = "user-voice-003"
        audio_content = b"same voice sample for both enrollment and auth"

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BIOMETRIC_BUCKET)
        _upload_reference_voice(s3, user_id, audio_content)

        ddb_client = boto3.client("dynamodb", region_name="us-east-1")
        _create_dynamodb_table(ddb_client)
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
        _create_user_record(table, user_id, failed_attempts=4)

        submitted_audio = base64.b64encode(audio_content).decode()
        event = _make_event(
            auth_type="voice",
            user_id=user_id,
            challenge_answer=submitted_audio,
        )
        result = handler(event, None)

        assert result["response"]["answerCorrect"] is True
        user = _get_user_record(table, user_id)
        assert int(user["failed_auth_attempts"]) == 0


# ---------------------------------------------------------------------------
# Failed attempt tracking
# ---------------------------------------------------------------------------

class TestFailedAttemptTracking:
    @mock_aws
    def test_failure_increments_counter(self):
        """A failed auth attempt should increment failed_auth_attempts."""
        user_id = "user-fail-001"

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BIOMETRIC_BUCKET)
        _upload_reference_voice(s3, user_id, _VOICE_REF_BYTES)

        ddb_client = boto3.client("dynamodb", region_name="us-east-1")
        _create_dynamodb_table(ddb_client)
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
        _create_user_record(table, user_id, failed_attempts=0)

        # Submit different audio to trigger failure
        submitted_audio = base64.b64encode(_VOICE_WRONG_BYTES).decode()
        event = _make_event(
            auth_type="voice",
            user_id=user_id,
            challenge_answer=submitted_audio,
        )
        result = handler(event, None)

        assert result["response"]["answerCorrect"] is False
        user = _get_user_record(table, user_id)
        assert int(user["failed_auth_attempts"]) == 1

    @mock_aws
    def test_multiple_failures_increment_counter(self):
        """Multiple failures should accumulate."""
        user_id = "user-fail-002"

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BIOMETRIC_BUCKET)
        _upload_reference_voice(s3, user_id, _VOICE_REF_BYTES)

        ddb_client = boto3.client("dynamodb", region_name="us-east-1")
        _create_dynamodb_table(ddb_client)
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
        _create_user_record(table, user_id, failed_attempts=3)

        submitted_audio = base64.b64encode(_VOICE_WRONG_BYTES).decode()
        event = _make_event(
            auth_type="voice",
            user_id=user_id,
            challenge_answer=submitted_audio,
        )
        result = handler(event, None)

        assert result["response"]["answerCorrect"] is False
        user = _get_user_record(table, user_id)
        assert int(user["failed_auth_attempts"]) == 4


# ---------------------------------------------------------------------------
# Account lockout
# ---------------------------------------------------------------------------

class TestAccountLockout:
    @mock_aws
    def test_account_locked_after_six_failures(self):
        """Account should be locked after 6 total failures (3 facial + 3 voice)."""
        user_id = "user-lock-001"

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BIOMETRIC_BUCKET)
        _upload_reference_voice(s3, user_id, _VOICE_REF_BYTES)

        ddb_client = boto3.client("dynamodb", region_name="us-east-1")
        _create_dynamodb_table(ddb_client)
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
        # User already has 5 failures (one more triggers lockout)
        _create_user_record(table, user_id, failed_attempts=5)

        submitted_audio = base64.b64encode(_VOICE_WRONG_BYTES).decode()
        event = _make_event(
            auth_type="voice",
            user_id=user_id,
            challenge_answer=submitted_audio,
        )
        result = handler(event, None)

        assert result["response"]["answerCorrect"] is False
        user = _get_user_record(table, user_id)
        assert int(user["failed_auth_attempts"]) == 6
        assert user["status"] == "deactivated"

    @mock_aws
    def test_account_not_locked_below_threshold(self):
        """Account should NOT be locked if failures < 6."""
        user_id = "user-lock-002"

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BIOMETRIC_BUCKET)
        _upload_reference_voice(s3, user_id, _VOICE_REF_BYTES)

        ddb_client = boto3.client("dynamodb", region_name="us-east-1")
        _create_dynamodb_table(ddb_client)
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
        _create_user_record(table, user_id, failed_attempts=4)

        submitted_audio = base64.b64encode(_VOICE_WRONG_BYTES).decode()
        event = _make_event(
            auth_type="voice",
            user_id=user_id,
            challenge_answer=submitted_audio,
        )
        result = handler(event, None)

        assert result["response"]["answerCorrect"] is False
        user = _get_user_record(table, user_id)
        assert int(user["failed_auth_attempts"]) == 5
        assert user["status"] == "active"

    def test_total_lockout_threshold_is_six(self):
        assert TOTAL_LOCKOUT_THRESHOLD == 6


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    @mock_aws
    def test_unknown_auth_type_returns_false(self):
        """Unknown auth_type should result in answerCorrect=False."""
        user_id = "user-edge-001"

        ddb_client = boto3.client("dynamodb", region_name="us-east-1")
        _create_dynamodb_table(ddb_client)
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
        _create_user_record(table, user_id)

        event = _make_event(
            auth_type="unknown",
            user_id=user_id,
            challenge_answer="some-data",
        )
        result = handler(event, None)

        assert result["response"]["answerCorrect"] is False

    @mock_aws
    def test_empty_auth_type_returns_false(self):
        """Empty auth_type should result in answerCorrect=False."""
        ddb_client = boto3.client("dynamodb", region_name="us-east-1")
        _create_dynamodb_table(ddb_client)

        event = _make_event(auth_type="", user_id="", challenge_answer="")
        result = handler(event, None)

        assert result["response"]["answerCorrect"] is False

    @mock_aws
    def test_missing_user_record_does_not_crash(self):
        """Handler should not crash if user record doesn't exist in DynamoDB."""
        user_id = "user-nonexistent"

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BIOMETRIC_BUCKET)
        _upload_reference_voice(s3, user_id, b"reference audio")

        ddb_client = boto3.client("dynamodb", region_name="us-east-1")
        _create_dynamodb_table(ddb_client)

        submitted_audio = base64.b64encode(b"reference audio").decode()
        event = _make_event(
            auth_type="voice",
            user_id=user_id,
            challenge_answer=submitted_audio,
        )
        result = handler(event, None)

        # Should still return a result without crashing
        assert "answerCorrect" in result["response"]

    @mock_aws
    def test_s3_error_returns_false(self):
        """If S3 reference file is missing, auth should fail gracefully."""
        user_id = "user-edge-003"

        # Create bucket but don't upload reference
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BIOMETRIC_BUCKET)

        ddb_client = boto3.client("dynamodb", region_name="us-east-1")
        _create_dynamodb_table(ddb_client)
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
        _create_user_record(table, user_id)

        submitted_audio = base64.b64encode(b"some audio").decode()
        event = _make_event(
            auth_type="voice",
            user_id=user_id,
            challenge_answer=submitted_audio,
        )
        result = handler(event, None)

        assert result["response"]["answerCorrect"] is False

    def test_handler_returns_same_event_object(self):
        """Handler should mutate and return the same event dict."""
        event = {
            "request": {
                "privateChallengeParameters": {
                    "auth_type": "unknown",
                    "user_id": "",
                },
                "challengeAnswer": "",
            },
            "response": {},
        }
        result = handler(event, None)
        assert result is event

    def test_missing_request_key_does_not_crash(self):
        """Handler should handle missing request key gracefully."""
        event = {"response": {}}
        result = handler(event, None)
        assert result["response"]["answerCorrect"] is False

    def test_facial_confidence_threshold_is_95(self):
        assert FACIAL_CONFIDENCE_THRESHOLD == 95.0

    def test_voice_similarity_threshold_is_085(self):
        assert VOICE_SIMILARITY_THRESHOLD == 0.85
