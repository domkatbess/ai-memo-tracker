"""Superuser authorization middleware for protected endpoints.

Extracts user identity from Cognito JWT claims in API Gateway events
and enforces role-based access control.
"""

from backend.shared.response import error_response


def get_user_claims(event):
    """Extract user identity info from API Gateway Cognito authorizer claims.

    Args:
        event: API Gateway proxy event dict.

    Returns:
        dict with user_id, role, and full_name if claims are present,
        or None if claims cannot be extracted.
    """
    try:
        claims = event["requestContext"]["authorizer"]["claims"]
    except (KeyError, TypeError):
        return None

    user_id = claims.get("custom:user_id") or claims.get("sub")
    role = claims.get("custom:role")
    full_name = claims.get("name") or claims.get("custom:full_name")

    if not user_id or not role:
        return None

    return {
        "user_id": user_id,
        "role": role,
        "full_name": full_name,
    }


def require_superuser(event):
    """Check that the requesting user has the superuser role.

    Args:
        event: API Gateway proxy event dict.

    Returns:
        None if the user is authorized (superuser role),
        or an API Gateway error response dict (403) if not.
    """
    claims = get_user_claims(event)

    if claims is None:
        return error_response(
            "Authorization required. Unable to verify user identity.",
            "FORBIDDEN",
            403,
        )

    if claims["role"] != "superuser":
        return error_response(
            "Access denied. Superuser role is required for this operation.",
            "FORBIDDEN",
            403,
        )

    return None
