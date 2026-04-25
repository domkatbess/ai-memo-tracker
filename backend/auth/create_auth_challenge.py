"""
Cognito CreateAuthChallenge Lambda trigger.

Creates challenge metadata for the client specifying the auth type
("facial" or "voice"). The define_auth_challenge trigger decides *which*
challenge to issue; this trigger builds the actual challenge payload that
the mobile app receives.

Requirements: 6.1, 7.1
"""

from backend.auth.define_auth_challenge import FACIAL_CHALLENGE, VOICE_CHALLENGE

# Human-readable instructions sent to the mobile app for each auth type.
_INSTRUCTIONS = {
    FACIAL_CHALLENGE: "Please look at the camera for facial recognition.",
    VOICE_CHALLENGE: "Please speak the displayed phrase for voice recognition.",
}

# Default auth type when the session has no prior challenge metadata.
_DEFAULT_AUTH_TYPE = FACIAL_CHALLENGE


def _determine_auth_type(session: list[dict]) -> str:
    """Determine the auth type from the most recent session entry.

    The define_auth_challenge trigger stores the intended auth method in
    ``challengeMetadata`` of the last session entry.  If the session is
    empty (first challenge), we default to facial recognition.
    """
    if not session:
        return _DEFAULT_AUTH_TYPE

    last_entry = session[-1]
    metadata = last_entry.get("challengeMetadata", "")

    if metadata == VOICE_CHALLENGE:
        return VOICE_CHALLENGE

    # Count facial failures to decide if we should switch to voice.
    facial_failures = sum(
        1
        for entry in session
        if entry.get("challengeMetadata") == FACIAL_CHALLENGE
        and entry.get("challengeResult") is False
    )
    if facial_failures >= 3:
        return VOICE_CHALLENGE

    return FACIAL_CHALLENGE


def handler(event: dict, context) -> dict:
    """Cognito CreateAuthChallenge trigger handler.

    Reads the session history to determine the auth type, then populates:

    - ``publicChallengeParameters``: visible to the client (auth_type,
      instructions).
    - ``privateChallengeParameters``: visible only to the
      VerifyAuthChallengeResponse trigger (auth_type, user_id).
    - ``challengeMetadata``: string identifying this challenge type.
    """
    request = event.get("request", {})
    session: list[dict] = request.get("session", [])
    user_attributes: dict = request.get("userAttributes", {})
    user_id: str = user_attributes.get("sub", "")

    auth_type = _determine_auth_type(session)

    response = event.setdefault("response", {})

    response["publicChallengeParameters"] = {
        "auth_type": auth_type.lower(),
        "instructions": _INSTRUCTIONS.get(auth_type, ""),
    }

    response["privateChallengeParameters"] = {
        "auth_type": auth_type.lower(),
        "user_id": user_id,
    }

    response["challengeMetadata"] = auth_type

    return event
