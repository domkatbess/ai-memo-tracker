"""DynamoDB single-table key builders and table resource helper."""

import boto3

from backend.shared.config import TABLE_NAME, AWS_REGION


def get_table():
    """Return a DynamoDB Table resource for the application table."""
    return boto3.resource("dynamodb", region_name=AWS_REGION).Table(TABLE_NAME)


def memo_pk(memo_id: str) -> str:
    """Return the partition key for a memo item."""
    return f"MEMO#{memo_id}"


def memo_sk() -> str:
    """Return the sort key for a memo metadata item."""
    return "METADATA"


def user_pk(user_id: str) -> str:
    """Return the partition key for a user item."""
    return f"USER#{user_id}"


def user_sk() -> str:
    """Return the sort key for a user profile item."""
    return "PROFILE"


def gsi1_email_pk(email: str) -> str:
    """Return GSI1 partition key for user email lookup."""
    return f"EMAIL#{email}"


def gsi1_email_sk() -> str:
    """Return GSI1 sort key for user email lookup."""
    return "PROFILE"


def gsi2_role_pk(role: str) -> str:
    """Return GSI2 partition key for user role lookup."""
    return f"ROLE#{role}"


def gsi2_role_sk(user_id: str) -> str:
    """Return GSI2 sort key for user role lookup."""
    return f"USER#{user_id}"


def gsi1_type_pk(memo_type: str) -> str:
    """Return GSI1 partition key for memo type queries."""
    return f"TYPE#{memo_type}"


def gsi1_date_sk(memo_date: str) -> str:
    """Return GSI1 sort key for memo date queries."""
    return f"DATE#{memo_date}"


def gsi2_person_pk(person_name: str) -> str:
    """Return GSI2 partition key for person name queries."""
    return f"PERSON#{person_name}"


def log_sk(timestamp: str, user_id: str) -> str:
    """Return the sort key for an access log entry."""
    return f"LOG#{timestamp}#{user_id}"


def note_sk(timestamp: str) -> str:
    """Return the sort key for a memo note entry."""
    return f"NOTE#{timestamp}"


def audit_sk(timestamp: str) -> str:
    """Return the sort key for a user audit entry."""
    return f"AUDIT#{timestamp}"


def session_pk(session_id: str) -> str:
    """Return the partition key for a voice session item."""
    return f"VSESSION#{session_id}"
