"""DynamoDB single-table key builders and table resource helper."""

import boto3

from backend.shared.config import TABLE_NAME, AWS_REGION


def get_table():
    """Return a DynamoDB Table resource for the application table."""
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    return dynamodb.Table(TABLE_NAME)


# --- Key builders ---

def memo_pk(memo_id: str) -> str:
    return f"MEMO#{memo_id}"


def memo_sk() -> str:
    return "METADATA"


def user_pk(user_id: str) -> str:
    return f"USER#{user_id}"


def user_sk() -> str:
    return "PROFILE"


def gsi1_email_pk(email: str) -> str:
    return f"EMAIL#{email}"


def gsi1_email_sk() -> str:
    return "PROFILE"


def gsi2_role_pk(role: str) -> str:
    return f"ROLE#{role}"


def gsi2_role_sk(user_id: str) -> str:
    return f"USER#{user_id}"


def gsi1_type_pk(memo_type: str) -> str:
    return f"TYPE#{memo_type}"


def gsi1_date_sk(memo_date: str) -> str:
    return f"DATE#{memo_date}"


def gsi2_person_pk(person_name: str) -> str:
    return f"PERSON#{person_name.lower()}"


def log_sk(timestamp: str, user_id: str) -> str:
    return f"LOG#{timestamp}#{user_id}"


def note_sk(timestamp: str) -> str:
    return f"NOTE#{timestamp}"


def audit_sk(timestamp: str) -> str:
    return f"AUDIT#{timestamp}"


def session_pk(session_id: str) -> str:
    return f"VSESSION#{session_id}"
