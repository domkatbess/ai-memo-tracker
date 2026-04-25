"""DynamoDB single-table key builders and table resource helper."""

import boto3

from backend.shared.config import TABLE_NAME, AWS_REGION


def get_table():
    """Return a DynamoDB Table resource for the main table."""
    return boto3.resource("dynamodb", region_name=AWS_REGION).Table(TABLE_NAME)


def memo_pk(memo_id: str) -> str:
    """Build partition key for a memo entity."""
    return f"MEMO#{memo_id}"


def memo_sk() -> str:
    """Build sort key for a memo metadata record."""
    return "METADATA"


def user_pk(user_id: str) -> str:
    """Build partition key for a user entity."""
    return f"USER#{user_id}"


def user_sk() -> str:
    """Build sort key for a user profile record."""
    return "PROFILE"


def gsi1_email_pk(email: str) -> str:
    """Build GSI1 partition key for email lookup."""
    return f"EMAIL#{email}"


def gsi1_email_sk() -> str:
    """Build GSI1 sort key for email lookup."""
    return "PROFILE"


def gsi2_role_pk(role: str) -> str:
    """Build GSI2 partition key for role lookup."""
    return f"ROLE#{role}"


def gsi2_role_sk(user_id: str) -> str:
    """Build GSI2 sort key for role lookup."""
    return f"USER#{user_id}"


def gsi1_type_pk(memo_type: str) -> str:
    """Build GSI1 partition key for memo type queries."""
    return f"TYPE#{memo_type}"


def gsi1_date_sk(memo_date: str) -> str:
    """Build GSI1 sort key for date-based queries."""
    return f"DATE#{memo_date}"


def gsi2_person_pk(person_name: str) -> str:
    """Build GSI2 partition key for person name queries."""
    return f"PERSON#{person_name}"


def log_sk(timestamp: str, user_id: str) -> str:
    """Build sort key for an access log entry."""
    return f"LOG#{timestamp}#{user_id}"


def note_sk(timestamp: str) -> str:
    """Build sort key for a memo note entry."""
    return f"NOTE#{timestamp}"


def audit_sk(timestamp: str) -> str:
    """Build sort key for a user audit entry."""
    return f"AUDIT#{timestamp}"


def session_pk(session_id: str) -> str:
    """Build partition key for a voice session entity."""
    return f"VSESSION#{session_id}"
