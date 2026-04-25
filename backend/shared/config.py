"""
Configuration module for AI Memo Tracker backend.

Loads environment variables with sensible defaults for local development.
"""

import os

# DynamoDB
TABLE_NAME = os.environ.get("TABLE_NAME", "MemoTrackerTable")

# S3 Buckets
BIOMETRIC_BUCKET = os.environ.get("BIOMETRIC_BUCKET", "memo-tracker-biometric-dev")
AUDIO_BUCKET = os.environ.get("AUDIO_BUCKET", "memo-tracker-audio-dev")

# AWS Region
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Cognito
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")

# Rekognition
REKOGNITION_COLLECTION_ID = os.environ.get("REKOGNITION_COLLECTION_ID", "")
