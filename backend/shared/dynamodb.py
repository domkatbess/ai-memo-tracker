"""
DynamoDB helpers for the single-table design.

Provides a table resource accessor and key builder functions for all
entities in the MemoTrackerTable.
"""

import boto3
from backend.shared.config import TABLE_NAME, AWS_REGION


def get_table():
    """Return a DynamoDB Table resource for the configured table name."""
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    return dynamodb.Table(TABLE_NAME)


# ---------------------------------------------------------------------------
# Primary key builders
# ---------------------------------------------------------------------------

def memo_pk(memo_id: str) -> str:
    """Partition key for a memo entity."""
    return f"MEMO#{memo_id}"


def memo_sk() -> str:
    """Sort key for memo metadata."""
    return "METADATA"


def user_pk(user_id: str) -> str:
    """Partition key for a user entity."""
    return f"USER#{user_id}"


def user_sk() -> str:
    """Sort key for user profile."""
    return "PROFILE"


def log_sk(timestamp: str, user_id: str) -> str:
    """Sort key for an access-log entry on a memo."""
    return f"LOG#{timestamp}#{user_id}"


def note_sk(timestamp: str) -> str:
    """Sort key for a memo note."""
    return f"NOTE#{timestamp}"


def session_pk(session_id: str) -> str:
    """Partition key for a voice-guided memo session."""
    return f"VSESSION#{session_id}"


def audit_sk(timestamp: str) -> str:
    """Sort key for a user audit-trail entry."""
    return f"AUDIT#{timestamp}"


def auth_sk(timestamp: str) -> str:
    """Sort key for an authentication attempt entry."""
    return f"AUTH#{timestamp}"


# ---------------------------------------------------------------------------
# GSI key builders
# ---------------------------------------------------------------------------

def gsi1_type_pk(memo_type: str) -> str:
    """GSI1 partition key for querying memos by type."""
    return f"TYPE#{memo_type}"


def gsi1_date_sk(date: str) -> str:
    """GSI1 sort key for date-based ordering."""
    return f"DATE#{date}"


def gsi2_person_pk(person_name: str) -> str:
    """GSI2 partition key for querying memos by person (lowercased)."""
    return f"PERSON#{person_name.lower()}"


def gsi1_email_pk(email: str) -> str:
    """GSI1 partition key for looking up users by email."""
    return f"EMAIL#{email}"


def gsi2_role_pk(role: str) -> str:
    """GSI2 partition key for listing users by role."""
    return f"ROLE#{role}"
