"""
Tests for the create_auth_challenge Cognito Lambda trigger.

Covers challenge creation logic:
  - Empty session → facial challenge parameters
  - Session with facial metadata → facial challenge
  - Session with voice metadata → voice challenge
  - After 3 facial failures → voice challenge
  - Public and private challenge parameters are set correctly
  - challengeMetadata is set on the response

Requirements: 6.1, 7.1
"""

import pytest

from backend.auth.define_auth_challenge import FACIAL_CHALLENGE, VOICE_CHALLENGE
from backend.auth.create_auth_challenge import (
    _INSTRUCTIONS,
    _DEFAULT_AUTH_TYPE,
    _determine_auth_type,
    handler,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    session: list[dict] | None = None,
    user_sub: str = "user-abc-123",
) -> dict:
    """Build a minimal Cognito CreateAuthChallenge event."""
    return {
        "request": {
            "session": session or [],
            "challengeName": "CUSTOM_CHALLENGE",
            "userAttributes": {"sub": user_sub},
        },
        "response": {},
    }


def _failed_entry(method: str) -> dict:
    """Return a session entry representing a failed challenge."""
    return {
        "challengeName": "CUSTOM_CHALLENGE",
        "challengeResult": False,
        "challengeMetadata": method,
    }


def _success_entry(method: str) -> dict:
    """Return a session entry representing a successful challenge."""
    return {
        "challengeName": "CUSTOM_CHALLENGE",
        "challengeResult": True,
        "challengeMetadata": method,
    }


# ---------------------------------------------------------------------------
# 1. Empty session → facial challenge
# ---------------------------------------------------------------------------

class TestEmptySession:
    def test_creates_facial_challenge(self):
        event = _make_event(session=[])
        result = handler(event, None)

        assert result["response"]["publicChallengeParameters"]["auth_type"] == "facial"
        assert result["response"]["challengeMetadata"] == FACIAL_CHALLENGE

    def test_includes_facial_instructions(self):
        event = _make_event(session=[])
        result = handler(event, None)

        expected = _INSTRUCTIONS[FACIAL_CHALLENGE]
        assert result["response"]["publicChallengeParameters"]["instructions"] == expected

    def test_sets_private_parameters_with_user_id(self):
        event = _make_event(session=[], user_sub="user-xyz-789")
        result = handler(event, None)

        private = result["response"]["privateChallengeParameters"]
        assert private["auth_type"] == "facial"
        assert private["user_id"] == "user-xyz-789"


# ---------------------------------------------------------------------------
# 2. Facial challenge in progress
# ---------------------------------------------------------------------------

class TestFacialChallenge:
    def test_one_facial_failure_continues_facial(self):
        session = [_failed_entry(FACIAL_CHALLENGE)]
        event = _make_event(session=session)
        result = handler(event, None)

        assert result["response"]["publicChallengeParameters"]["auth_type"] == "facial"
        assert result["response"]["challengeMetadata"] == FACIAL_CHALLENGE

    def test_two_facial_failures_continues_facial(self):
        session = [
            _failed_entry(FACIAL_CHALLENGE),
            _failed_entry(FACIAL_CHALLENGE),
        ]
        event = _make_event(session=session)
        result = handler(event, None)

        assert result["response"]["publicChallengeParameters"]["auth_type"] == "facial"
        assert result["response"]["challengeMetadata"] == FACIAL_CHALLENGE


# ---------------------------------------------------------------------------
# 3. Switch to voice after 3 facial failures
# ---------------------------------------------------------------------------

class TestSwitchToVoice:
    def test_three_facial_failures_creates_voice_challenge(self):
        session = [_failed_entry(FACIAL_CHALLENGE)] * 3
        event = _make_event(session=session)
        result = handler(event, None)

        assert result["response"]["publicChallengeParameters"]["auth_type"] == "voice"
        assert result["response"]["challengeMetadata"] == VOICE_CHALLENGE

    def test_voice_instructions_after_switch(self):
        session = [_failed_entry(FACIAL_CHALLENGE)] * 3
        event = _make_event(session=session)
        result = handler(event, None)

        expected = _INSTRUCTIONS[VOICE_CHALLENGE]
        assert result["response"]["publicChallengeParameters"]["instructions"] == expected

    def test_private_params_reflect_voice_after_switch(self):
        session = [_failed_entry(FACIAL_CHALLENGE)] * 3
        event = _make_event(session=session, user_sub="user-voice-001")
        result = handler(event, None)

        private = result["response"]["privateChallengeParameters"]
        assert private["auth_type"] == "voice"
        assert private["user_id"] == "user-voice-001"


# ---------------------------------------------------------------------------
# 4. Voice challenge in progress
# ---------------------------------------------------------------------------

class TestVoiceChallenge:
    def test_voice_failure_continues_voice(self):
        session = [
            *[_failed_entry(FACIAL_CHALLENGE)] * 3,
            _failed_entry(VOICE_CHALLENGE),
        ]
        event = _make_event(session=session)
        result = handler(event, None)

        assert result["response"]["publicChallengeParameters"]["auth_type"] == "voice"
        assert result["response"]["challengeMetadata"] == VOICE_CHALLENGE

    def test_two_voice_failures_continues_voice(self):
        session = [
            *[_failed_entry(FACIAL_CHALLENGE)] * 3,
            *[_failed_entry(VOICE_CHALLENGE)] * 2,
        ]
        event = _make_event(session=session)
        result = handler(event, None)

        assert result["response"]["publicChallengeParameters"]["auth_type"] == "voice"
        assert result["response"]["challengeMetadata"] == VOICE_CHALLENGE


# ---------------------------------------------------------------------------
# 5. Response structure
# ---------------------------------------------------------------------------

class TestResponseStructure:
    def test_public_parameters_has_auth_type_and_instructions(self):
        event = _make_event()
        result = handler(event, None)

        public = result["response"]["publicChallengeParameters"]
        assert "auth_type" in public
        assert "instructions" in public

    def test_private_parameters_has_auth_type_and_user_id(self):
        event = _make_event()
        result = handler(event, None)

        private = result["response"]["privateChallengeParameters"]
        assert "auth_type" in private
        assert "user_id" in private

    def test_challenge_metadata_is_set(self):
        event = _make_event()
        result = handler(event, None)

        assert "challengeMetadata" in result["response"]

    def test_returns_same_event_object(self):
        """Handler should mutate and return the same event dict."""
        event = _make_event()
        result = handler(event, None)
        assert result is event

    def test_auth_type_values_are_lowercase(self):
        """Public and private auth_type should be lowercase."""
        event = _make_event()
        result = handler(event, None)

        public_type = result["response"]["publicChallengeParameters"]["auth_type"]
        private_type = result["response"]["privateChallengeParameters"]["auth_type"]
        assert public_type == public_type.lower()
        assert private_type == private_type.lower()


# ---------------------------------------------------------------------------
# 6. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_missing_request_key_does_not_crash(self):
        event = {"response": {}}
        result = handler(event, None)

        assert result["response"]["publicChallengeParameters"]["auth_type"] == "facial"

    def test_missing_user_attributes_uses_empty_user_id(self):
        event = {"request": {"session": []}, "response": {}}
        result = handler(event, None)

        assert result["response"]["privateChallengeParameters"]["user_id"] == ""

    def test_missing_sub_attribute_uses_empty_user_id(self):
        event = {
            "request": {
                "session": [],
                "userAttributes": {"email": "test@example.com"},
            },
            "response": {},
        }
        result = handler(event, None)

        assert result["response"]["privateChallengeParameters"]["user_id"] == ""

    def test_default_auth_type_is_facial(self):
        assert _DEFAULT_AUTH_TYPE == FACIAL_CHALLENGE

    def test_determine_auth_type_empty_session(self):
        assert _determine_auth_type([]) == FACIAL_CHALLENGE

    def test_determine_auth_type_voice_metadata(self):
        session = [
            *[_failed_entry(FACIAL_CHALLENGE)] * 3,
            _failed_entry(VOICE_CHALLENGE),
        ]
        assert _determine_auth_type(session) == VOICE_CHALLENGE

    def test_session_with_unknown_metadata_defaults_to_facial(self):
        session = [
            {
                "challengeName": "CUSTOM_CHALLENGE",
                "challengeResult": False,
                "challengeMetadata": "UNKNOWN",
            }
        ]
        event = _make_event(session=session)
        result = handler(event, None)

        assert result["response"]["publicChallengeParameters"]["auth_type"] == "facial"
