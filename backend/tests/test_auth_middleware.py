"""Tests for superuser authorization middleware.

Validates Requirements 8.1 and 8.6:
- 8.1: User management operations restricted to superuser role.
- 8.6: Regular users denied with authorization error.
"""

import json

from backend.shared.auth_middleware import get_user_claims, require_superuser


def _make_event(role="superuser", user_id="user-123", full_name="Admin User"):
    """Build a minimal API Gateway event with Cognito authorizer claims."""
    return {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "cognito-sub-abc",
                    "custom:user_id": user_id,
                    "custom:role": role,
                    "name": full_name,
                }
            }
        }
    }


# --- get_user_claims tests ---


class TestGetUserClaims:
    def test_extracts_claims_from_valid_event(self):
        event = _make_event(role="superuser", user_id="u-1", full_name="Alice")
        claims = get_user_claims(event)

        assert claims is not None
        assert claims["user_id"] == "u-1"
        assert claims["role"] == "superuser"
        assert claims["full_name"] == "Alice"

    def test_falls_back_to_sub_when_custom_user_id_missing(self):
        event = _make_event()
        del event["requestContext"]["authorizer"]["claims"]["custom:user_id"]

        claims = get_user_claims(event)

        assert claims is not None
        assert claims["user_id"] == "cognito-sub-abc"

    def test_falls_back_to_custom_full_name(self):
        event = _make_event()
        claims_data = event["requestContext"]["authorizer"]["claims"]
        del claims_data["name"]
        claims_data["custom:full_name"] = "Bob Jones"

        claims = get_user_claims(event)

        assert claims["full_name"] == "Bob Jones"

    def test_returns_none_when_authorizer_missing(self):
        event = {"requestContext": {}}
        assert get_user_claims(event) is None

    def test_returns_none_when_claims_missing(self):
        event = {"requestContext": {"authorizer": {}}}
        assert get_user_claims(event) is None

    def test_returns_none_when_request_context_missing(self):
        event = {}
        assert get_user_claims(event) is None

    def test_returns_none_when_role_missing(self):
        event = _make_event()
        del event["requestContext"]["authorizer"]["claims"]["custom:role"]

        assert get_user_claims(event) is None

    def test_returns_none_when_both_user_ids_missing(self):
        event = _make_event()
        claims_data = event["requestContext"]["authorizer"]["claims"]
        del claims_data["custom:user_id"]
        del claims_data["sub"]

        assert get_user_claims(event) is None


# --- require_superuser tests ---


class TestRequireSuperuser:
    def test_allows_superuser_access(self):
        event = _make_event(role="superuser")
        result = require_superuser(event)

        assert result is None

    def test_denies_regular_user_with_403(self):
        event = _make_event(role="regular_user")
        result = require_superuser(event)

        assert result is not None
        assert result["statusCode"] == 403
        body = json.loads(result["body"])
        assert body["error_code"] == "FORBIDDEN"
        assert "Superuser role is required" in body["error"]

    def test_denies_when_claims_missing_with_403(self):
        event = {"requestContext": {"authorizer": {}}}
        result = require_superuser(event)

        assert result is not None
        assert result["statusCode"] == 403
        body = json.loads(result["body"])
        assert body["error_code"] == "FORBIDDEN"

    def test_denies_when_authorizer_context_missing_with_403(self):
        event = {"requestContext": {}}
        result = require_superuser(event)

        assert result is not None
        assert result["statusCode"] == 403
        body = json.loads(result["body"])
        assert body["error_code"] == "FORBIDDEN"

    def test_denies_unknown_role_with_403(self):
        event = _make_event(role="admin")
        result = require_superuser(event)

        assert result is not None
        assert result["statusCode"] == 403
        body = json.loads(result["body"])
        assert body["error_code"] == "FORBIDDEN"

    def test_denies_empty_event_with_403(self):
        result = require_superuser({})

        assert result is not None
        assert result["statusCode"] == 403
