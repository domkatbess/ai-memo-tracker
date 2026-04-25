"""
Shared pytest fixtures for the AI Memo Tracker backend test suite.

Uses moto to mock AWS services so tests run without real AWS credentials.
"""

import os
import boto3
import pytest
from moto import mock_aws


# ---------------------------------------------------------------------------
# Environment variables — set before any application code imports config
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    """Inject test-safe environment variables for every test."""
    monkeypatch.setenv("TABLE_NAME", "MemoTrackerTable")
    monkeypatch.setenv("BIOMETRIC_BUCKET", "memo-tracker-biometric-dev")
    monkeypatch.setenv("AUDIO_BUCKET", "memo-tracker-audio-dev")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")


# ---------------------------------------------------------------------------
# DynamoDB table fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def dynamodb_table():
    """Create a mocked DynamoDB table matching the single-table design."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="MemoTrackerTable",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(
            "MemoTrackerTable"
        )
        yield table


# ---------------------------------------------------------------------------
# S3 bucket fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def s3_biometric_bucket():
    """Create a mocked S3 bucket for biometric data."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="memo-tracker-biometric-dev")
        yield client


@pytest.fixture
def s3_audio_bucket():
    """Create a mocked S3 bucket for audio and attachments."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="memo-tracker-audio-dev")
        yield client


# ---------------------------------------------------------------------------
# Cognito fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def cognito_user_pool():
    """Create a mocked Cognito user pool."""
    with mock_aws():
        client = boto3.client("cognito-idp", region_name="us-east-1")
        response = client.create_user_pool(PoolName="MemoTrackerPool")
        pool_id = response["UserPool"]["Id"]
        yield client, pool_id
