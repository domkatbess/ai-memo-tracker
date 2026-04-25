"""
Cognito DefineAuthChallenge Lambda trigger.

Determines which authentication challenge to issue based on the session
history. Facial recognition is the primary method; voice recognition is
the fallback after 3 facial failures. After 3 facial + 3 voice failures
the authentication is failed (account lock).

Requirements: 6.1, 6.3, 6.5, 7.5
"""

# Maximum allowed failures per biometric method before switching / locking.
MAX_FAILURES_PER_METHOD = 3

# Challenge metadata prefixes used to identify the auth method.
FACIAL_CHALLENGE = "FACIAL"
VOICE_CHALLENGE = "VOICE"


def _count_failures(session: list[dict], method: str) -> int:
    """Return the number of failed challenges for *method* in *session*.

    Each session entry has:
      - challengeName: str
      - challengeResult: bool
      - challengeMetadata: str  (e.g. "FACIAL" or "VOICE")
    """
    return sum(
        1
        for entry in session
        if entry.get("challengeMetadata") == method
        and entry.get("challengeResult") is False
    )


def _last_challenge_succeeded(session: list[dict]) -> bool:
    """Return True if the most recent challenge in *session* succeeded."""
    if not session:
        return False
    return session[-1].get("challengeResult") is True


def handler(event: dict, context) -> dict:
    """Cognito DefineAuthChallenge trigger handler.

    Examines ``event['request']['session']`` to decide the next step:

    1. If the last challenge succeeded → issue tokens.
    2. If facial failures < 3 → issue a facial challenge.
    3. If facial failures >= 3 and voice failures < 3 → issue a voice challenge.
    4. If both >= 3 → fail authentication (triggers account lock).
    """
    session: list[dict] = event.get("request", {}).get("session", [])
    response = event.setdefault("response", {})

    # --- 1. Last challenge succeeded → issue tokens -----------------------
    if _last_challenge_succeeded(session):
        response["issueTokens"] = True
        response["failAuthentication"] = False
        return event

    # --- Count failures per method ----------------------------------------
    facial_failures = _count_failures(session, FACIAL_CHALLENGE)
    voice_failures = _count_failures(session, VOICE_CHALLENGE)

    # --- 4. Both methods exhausted → fail authentication ------------------
    if (
        facial_failures >= MAX_FAILURES_PER_METHOD
        and voice_failures >= MAX_FAILURES_PER_METHOD
    ):
        response["issueTokens"] = False
        response["failAuthentication"] = True
        return event

    # --- 3. Facial exhausted → switch to voice ----------------------------
    if facial_failures >= MAX_FAILURES_PER_METHOD:
        response["issueTokens"] = False
        response["failAuthentication"] = False
        response["challengeName"] = "CUSTOM_CHALLENGE"
        response["challengeMetadata"] = VOICE_CHALLENGE
        return event

    # --- 2. Default → issue facial challenge ------------------------------
    response["issueTokens"] = False
    response["failAuthentication"] = False
    response["challengeName"] = "CUSTOM_CHALLENGE"
    response["challengeMetadata"] = FACIAL_CHALLENGE
    return event
