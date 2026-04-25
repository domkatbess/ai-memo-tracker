"""
Tests for the define_auth_challenge Cognito Lambda trigger.

Covers the challenge-routing logic:
  - No prior session → facial challenge
  - Last challenge succeeded → issue tokens
  - Facial failures < 3 → facial challenge
  - Facial failures >= 3, voice failures < 3 → voice challenge
  - Both >= 3 → fail authentication (account lock)

Requirements: 6.1, 6.3, 6.5, 7.5
"""

import pytest

from backend.auth.define_auth_challenge import (
    FACIAL_CHALLENGE,
    MAX_FAILURES_PER_METHOD,
    VOICE_CHALLENGE,
    handler,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(session: list[dict] | None = None) -> dict:
    """Build a minimal Cognito DefineAuthChallenge event."""
    return {
        "request": {
            "session": session or [],
            "userAttributes": {"sub": "user-abc-123"},
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
# 1. Empty session → issue facial challenge
# ---------------------------------------------------------------------------

class TestEmptySession:
    def test_issues_facial_challenge(self):
        event = _make_event(session=[])
        result = handler(event, None)

        assert result["response"]["issueTokens"] is False
        assert result["response"]["failAuthentication"] is False
        assert result["response"]["challengeName"] == "CUSTOM_CHALLENGE"
        assert result["response"]["challengeMetadata"] == FACIAL_CHALLENGE

    def test_no_session_key_defaults_to_facial(self):
        event = {"request": {"userAttributes": {}}, "response": {}}
        result = handler(event, None)

        assert result["response"]["challengeMetadata"] == FACIAL_CHALLENGE
        assert result["response"]["issueTokens"] is False


# ---------------------------------------------------------------------------
# 2. Last challenge succeeded → issue tokens
# ---------------------------------------------------------------------------

class TestLastChallengeSucceeded:
    def test_facial_success_issues_tokens(self):
        session = [_success_entry(FACIAL_CHALLENGE)]
        event = _make_event(session=session)
        result = handler(event, None)

        assert result["response"]["issueTokens"] is True
        assert result["response"]["failAuthentication"] is False

    def test_voice_success_issues_tokens(self):
        session = [
            _failed_entry(FACIAL_CHALLENGE),
            _failed_entry(FACIAL_CHALLENGE),
            _failed_entry(FACIAL_CHALLENGE),
            _success_entry(VOICE_CHALLENGE),
        ]
        event = _make_event(session=session)
        result = handler(event, None)

        assert result["response"]["issueTokens"] is True
        assert result["response"]["failAuthentication"] is False

    def test_success_after_some_failures_issues_tokens(self):
        session = [
            _failed_entry(FACIAL_CHALLENGE),
            _failed_entry(FACIAL_CHALLENGE),
            _success_entry(FACIAL_CHALLENGE),
        ]
        event = _make_event(session=session)
        result = handler(event, None)

        assert result["response"]["issueTokens"] is True
        assert result["response"]["failAuthentication"] is False


# ---------------------------------------------------------------------------
# 3. Facial failures < 3 → continue with facial
# ---------------------------------------------------------------------------

class TestFacialRetries:
    def test_one_facial_failure_retries_facial(self):
        session = [_failed_entry(FACIAL_CHALLENGE)]
        event = _make_event(session=session)
        result = handler(event, None)

        assert result["response"]["challengeMetadata"] == FACIAL_CHALLENGE
        assert result["response"]["issueTokens"] is False
        assert result["response"]["failAuthentication"] is False

    def test_two_facial_failures_retries_facial(self):
        session = [
            _failed_entry(FACIAL_CHALLENGE),
            _failed_entry(FACIAL_CHALLENGE),
        ]
        event = _make_event(session=session)
        result = handler(event, None)

        assert result["response"]["challengeMetadata"] == FACIAL_CHALLENGE
        assert result["response"]["issueTokens"] is False
        assert result["response"]["failAuthentication"] is False


# ---------------------------------------------------------------------------
# 4. Facial failures >= 3 → switch to voice
# ---------------------------------------------------------------------------

class TestSwitchToVoice:
    def test_three_facial_failures_switches_to_voice(self):
        session = [_failed_entry(FACIAL_CHALLENGE)] * 3
        event = _make_event(session=session)
        result = handler(event, None)

        assert result["response"]["challengeMetadata"] == VOICE_CHALLENGE
        assert result["response"]["issueTokens"] is False
        assert result["response"]["failAuthentication"] is False

    def test_three_facial_plus_one_voice_failure_continues_voice(self):
        session = [
            *[_failed_entry(FACIAL_CHALLENGE)] * 3,
            _failed_entry(VOICE_CHALLENGE),
        ]
        event = _make_event(session=session)
        result = handler(event, None)

        assert result["response"]["challengeMetadata"] == VOICE_CHALLENGE
        assert result["response"]["issueTokens"] is False
        assert result["response"]["failAuthentication"] is False

    def test_three_facial_plus_two_voice_failures_continues_voice(self):
        session = [
            *[_failed_entry(FACIAL_CHALLENGE)] * 3,
            *[_failed_entry(VOICE_CHALLENGE)] * 2,
        ]
        event = _make_event(session=session)
        result = handler(event, None)

        assert result["response"]["challengeMetadata"] == VOICE_CHALLENGE
        assert result["response"]["issueTokens"] is False
        assert result["response"]["failAuthentication"] is False


# ---------------------------------------------------------------------------
# 5. Both methods exhausted → fail authentication (account lock)
# ---------------------------------------------------------------------------

class TestAccountLock:
    def test_three_facial_three_voice_fails_auth(self):
        session = [
            *[_failed_entry(FACIAL_CHALLENGE)] * 3,
            *[_failed_entry(VOICE_CHALLENGE)] * 3,
        ]
        event = _make_event(session=session)
        result = handler(event, None)

        assert result["response"]["issueTokens"] is False
        assert result["response"]["failAuthentication"] is True

    def test_more_than_three_each_still_fails_auth(self):
        session = [
            *[_failed_entry(FACIAL_CHALLENGE)] * 4,
            *[_failed_entry(VOICE_CHALLENGE)] * 4,
        ]
        event = _make_event(session=session)
        result = handler(event, None)

        assert result["response"]["issueTokens"] is False
        assert result["response"]["failAuthentication"] is True

    def test_no_challenge_name_in_response_when_locked(self):
        session = [
            *[_failed_entry(FACIAL_CHALLENGE)] * 3,
            *[_failed_entry(VOICE_CHALLENGE)] * 3,
        ]
        event = _make_event(session=session)
        result = handler(event, None)

        assert "challengeName" not in result["response"]


# ---------------------------------------------------------------------------
# 6. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_max_failures_constant_is_three(self):
        assert MAX_FAILURES_PER_METHOD == 3

    def test_event_is_returned_with_response_mutated(self):
        """Handler should mutate and return the same event dict."""
        event = _make_event(session=[])
        result = handler(event, None)
        assert result is event

    def test_missing_request_key_does_not_crash(self):
        event = {"response": {}}
        result = handler(event, None)
        # Should default to empty session → facial challenge
        assert result["response"]["challengeMetadata"] == FACIAL_CHALLENGE

    def test_voice_success_after_facial_exhaustion_issues_tokens(self):
        """Voice success after 3 facial failures should still issue tokens."""
        session = [
            *[_failed_entry(FACIAL_CHALLENGE)] * 3,
            _success_entry(VOICE_CHALLENGE),
        ]
        event = _make_event(session=session)
        result = handler(event, None)

        assert result["response"]["issueTokens"] is True
        assert result["response"]["failAuthentication"] is False
