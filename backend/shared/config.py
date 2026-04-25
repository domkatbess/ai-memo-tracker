"""Application configuration loaded from environment variables."""

import os

TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "MemoTrackerTable")
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "us-east-1_TestPool")
BIOMETRIC_BUCKET = os.environ.get("BIOMETRIC_BUCKET", "memo-tracker-biometric")
AUDIO_BUCKET = os.environ.get("AUDIO_BUCKET", "memo-tracker-audio")
REKOGNITION_COLLECTION_ID = os.environ.get("REKOGNITION_COLLECTION_ID", "memo-tracker-faces")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
