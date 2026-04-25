# Requirements Document

## Introduction

The AI-Powered Government Memo Tracking Personal Assistant is a system that enables government office personnel to track incoming and outgoing memos with full audit trails. The system uses biometric authentication (facial and voice recognition) for secure memo operations, supports voice-based input for note-taking and record retrieval, and enforces role-based access control where only a superuser can manage application users. The solution is built with a Python backend, React Native frontend, and leverages AWS free-tier AI and infrastructure services.

## Glossary

- **Memo_Tracker**: The core backend system responsible for managing memo records, audit logs, and business logic.
- **Auth_Service**: The authentication and authorization service that handles user identity verification via facial recognition, voice recognition, and credential-based login.
- **Voice_Service**: The service responsible for converting speech to text and text to speech using AWS Transcribe and AWS Polly.
- **Facial_Recognition_Service**: The service that uses AWS Rekognition to identify and verify users via facial features.
- **Voice_Recognition_Service**: The service that uses voice biometric analysis to identify and verify users by their voice patterns.
- **Mobile_App**: The React Native frontend application used by all users to interact with the system.
- **Superuser**: An administrative user with elevated privileges who can create, modify, and deactivate user accounts.
- **Regular_User**: A standard user who can perform memo operations (record, retrieve, access) but cannot manage other user accounts.
- **Memo**: A government document tracked by the system, classified as either incoming or outgoing.
- **Incoming_Memo**: A memo received by the office from an external source.
- **Outgoing_Memo**: A memo sent from the office to an external destination.
- **Access_Log**: A record of every user who accessed a specific memo, including timestamp and action performed.
- **AWS_Rekognition**: AWS AI service used for facial recognition and verification (free tier: 5,000 API calls/month for 12 months).
- **AWS_Transcribe**: AWS AI service used for speech-to-text conversion (free tier: 60 minutes/month for 12 months).
- **AWS_Polly**: AWS AI service used for text-to-speech conversion (free tier: 5 million characters/month for 12 months).
- **AWS_DynamoDB**: AWS NoSQL database service used for data storage (free tier: 25 GB storage, 25 read/write capacity units).
- **AWS_Lambda**: AWS serverless compute service for running backend functions (free tier: 1 million requests/month).
- **AWS_API_Gateway**: AWS service for creating and managing REST APIs (free tier: 1 million API calls/month for 12 months).
- **AWS_S3**: AWS object storage service for storing biometric data and memo attachments (free tier: 5 GB storage).
- **AWS_Cognito**: AWS service for user authentication and management (free tier: 50,000 monthly active users).

## Requirements

### Requirement 1: Memo Registration

**User Story:** As a Regular_User, I want to register incoming and outgoing memos in the system, so that all government memos are tracked with complete metadata.

#### Acceptance Criteria

1. WHEN a Regular_User submits a new memo record, THE Memo_Tracker SHALL store the memo with the following fields: memo title, memo type (incoming or outgoing), date on the memo, date the memo was recorded, the person who brought in the memo, and the person who took the memo out.
2. WHEN a memo is registered, THE Memo_Tracker SHALL automatically set the recording date to the current date and time in UTC.
3. WHEN a memo is registered as an Incoming_Memo, THE Memo_Tracker SHALL require the name of the person who brought in the memo.
4. WHEN a memo is registered as an Outgoing_Memo, THE Memo_Tracker SHALL require the name of the person who took the memo out.
5. THE Memo_Tracker SHALL assign a unique identifier to each registered memo.
6. IF a required field is missing during memo registration, THEN THE Memo_Tracker SHALL return a descriptive error message identifying the missing field.

### Requirement 2: Memo Retrieval

**User Story:** As a Regular_User, I want to search and retrieve memo records, so that I can find specific memos and review their details.

#### Acceptance Criteria

1. WHEN a Regular_User searches by memo title, THE Memo_Tracker SHALL return all memos with titles matching or containing the search term.
2. WHEN a Regular_User searches by date range, THE Memo_Tracker SHALL return all memos with memo dates falling within the specified range.
3. WHEN a Regular_User searches by memo type, THE Memo_Tracker SHALL return all memos matching the specified type (incoming or outgoing).
4. WHEN a Regular_User searches by person name, THE Memo_Tracker SHALL return all memos associated with that person as either the one who brought in or took out the memo.
5. WHEN a memo record is retrieved, THE Memo_Tracker SHALL display all stored metadata for that memo.

### Requirement 3: Memo Access Logging

**User Story:** As a Superuser, I want to track who accessed each memo, so that there is a complete audit trail for accountability.

#### Acceptance Criteria

1. WHEN a user views a memo record, THE Memo_Tracker SHALL create an Access_Log entry containing the user identity, memo identifier, timestamp, and action performed.
2. WHEN a Superuser requests the access history for a memo, THE Memo_Tracker SHALL return all Access_Log entries for that memo sorted by timestamp in descending order.
3. THE Memo_Tracker SHALL retain Access_Log entries for the lifetime of the memo record.
4. THE Access_Log SHALL be append-only; no user SHALL be able to modify or delete Access_Log entries.

### Requirement 4: Voice-Based Memo Note-Taking

**User Story:** As a Regular_User, I want to take notes on memos using voice input, so that I can quickly add observations without typing.

#### Acceptance Criteria

1. WHEN a Regular_User activates voice input on a memo record, THE Voice_Service SHALL capture audio from the device microphone and convert the speech to text using AWS_Transcribe.
2. WHEN the Voice_Service completes transcription, THE Memo_Tracker SHALL attach the transcribed text as a note to the specified memo record.
3. WHEN a transcription is saved, THE Memo_Tracker SHALL store the note text, the identity of the user who created the note, and the timestamp of creation.
4. IF the Voice_Service fails to transcribe the audio, THEN THE Mobile_App SHALL display an error message and allow the user to retry.
5. WHEN a Regular_User requests to hear memo notes read aloud, THE Voice_Service SHALL convert the note text to speech using AWS_Polly and play the audio through the device speaker.
6. WHEN a Regular_User initiates voice-based memo registration, THE Voice_Service SHALL use AWS_Polly to prompt the user for each required memo field one at a time, in the following order: memo title, memo type (incoming or outgoing), date on the memo, and the person who brought in or took out the memo (based on the memo type selected).
7. WHEN the Voice_Service prompts for a memo field, THE Voice_Service SHALL wait for the user's spoken response, convert it to text using AWS_Transcribe, and then proceed to the next field prompt.
8. IF the Voice_Service cannot transcribe a field response, THEN THE Voice_Service SHALL re-prompt the user for the same field and allow up to two retries before offering to cancel or switch to manual text input.
9. WHEN all required memo fields have been collected via voice input, THE Voice_Service SHALL use AWS_Polly to read back all collected field values to the user and ask for confirmation before saving.
10. WHEN the user confirms the voice-collected memo data, THE Memo_Tracker SHALL save the memo record with all collected fields.
11. IF the user rejects the voice-collected memo data during the review step, THEN THE Voice_Service SHALL allow the user to re-record individual fields or cancel the registration entirely.

### Requirement 5: Voice-Based Record Retrieval

**User Story:** As a Regular_User, I want to retrieve memo records using voice commands, so that I can search hands-free.

#### Acceptance Criteria

1. WHEN a Regular_User activates voice search, THE Voice_Service SHALL capture audio from the device microphone and convert the spoken query to text using AWS_Transcribe.
2. WHEN the Voice_Service produces a text query, THE Memo_Tracker SHALL parse the transcribed text to extract search parameters (title, date, person name, or memo type).
3. WHEN search parameters are extracted, THE Memo_Tracker SHALL execute the search and return matching memo records.
4. IF the Voice_Service cannot parse a valid search query from the transcription, THEN THE Mobile_App SHALL prompt the user to rephrase the query.
5. WHEN search results are returned via voice search, THE Voice_Service SHALL read aloud a summary of the results using AWS_Polly.

### Requirement 6: Facial Recognition Authentication

**User Story:** As a Regular_User, I want to authenticate using facial recognition when performing memo operations, so that memo access is secured biometrically.

#### Acceptance Criteria

1. WHEN a user initiates a memo input or retrieval operation, THE Auth_Service SHALL capture a facial image from the device camera and verify the user identity using AWS_Rekognition.
2. WHEN AWS_Rekognition returns a confidence score at or above 95%, THE Auth_Service SHALL authenticate the user and allow the operation to proceed.
3. IF AWS_Rekognition returns a confidence score below 95%, THEN THE Auth_Service SHALL deny the operation and prompt the user to retry or use an alternative authentication method.
4. WHEN a new user is registered, THE Facial_Recognition_Service SHALL capture and store a reference facial image in AWS_S3 and index the face in an AWS_Rekognition collection.
5. IF the device camera is unavailable, THEN THE Auth_Service SHALL fall back to voice recognition authentication.

### Requirement 7: Voice Recognition Authentication

**User Story:** As a Regular_User, I want to authenticate using voice recognition when performing memo operations, so that I have a biometric alternative to facial recognition.

#### Acceptance Criteria

1. WHEN a user initiates a memo input or retrieval operation and selects voice authentication, THE Auth_Service SHALL capture a voice sample from the device microphone and verify the user identity using the Voice_Recognition_Service.
2. WHEN the Voice_Recognition_Service confirms a match with the stored voice profile, THE Auth_Service SHALL authenticate the user and allow the operation to proceed.
3. IF the Voice_Recognition_Service cannot confirm a match, THEN THE Auth_Service SHALL deny the operation and prompt the user to retry or use an alternative authentication method.
4. WHEN a new user is registered, THE Voice_Recognition_Service SHALL capture and store a reference voice sample in AWS_S3 for future verification.
5. IF both facial recognition and voice recognition fail after three attempts each, THEN THE Auth_Service SHALL lock the user account and notify the Superuser.

### Requirement 8: Superuser User Management

**User Story:** As a Superuser, I want to add, modify, and deactivate user accounts through forms, so that I control who can access the application.

#### Acceptance Criteria

1. THE Auth_Service SHALL restrict user management operations to users with the Superuser role.
2. WHEN a Superuser submits the new user registration form, THE Auth_Service SHALL create a new user account with the provided details (name, role, email, department).
3. WHEN a new user account is created, THE Facial_Recognition_Service SHALL prompt the Superuser to capture the new user's facial image for biometric enrollment.
4. WHEN a new user account is created, THE Voice_Recognition_Service SHALL prompt the Superuser to capture the new user's voice sample for biometric enrollment.
5. WHEN a Superuser deactivates a user account, THE Auth_Service SHALL immediately revoke all active sessions for that user and prevent future logins.
6. IF a Regular_User attempts a user management operation, THEN THE Auth_Service SHALL deny the request and return an authorization error.
7. WHEN a Superuser modifies a user account, THE Auth_Service SHALL log the modification with the Superuser identity and timestamp.

### Requirement 9: User Registration Form

**User Story:** As a Superuser, I want a structured form to register new users, so that all required user information is collected consistently.

#### Acceptance Criteria

1. THE Mobile_App SHALL present a user registration form containing fields for: full name, email address, department, role (Regular_User or Superuser), and phone number.
2. WHEN the Superuser submits the registration form, THE Mobile_App SHALL validate that all required fields are populated and that the email address follows a valid format.
3. IF form validation fails, THEN THE Mobile_App SHALL highlight the invalid fields and display specific error messages.
4. WHEN the form is successfully submitted, THE Mobile_App SHALL proceed to the biometric enrollment flow for facial and voice capture.
5. THE Mobile_App SHALL prevent duplicate user registration by checking the email address against existing accounts before submission.

### Requirement 10: AWS Free-Tier Infrastructure Compliance

**User Story:** As a system administrator, I want the system to operate within AWS free-tier limits, so that the application runs without incurring costs during the initial deployment period.

#### Acceptance Criteria

1. THE Memo_Tracker SHALL use AWS_Lambda for all backend compute operations to remain within the free-tier limit of 1 million requests per month.
2. THE Memo_Tracker SHALL use AWS_DynamoDB for data storage to remain within the free-tier limit of 25 GB storage and 25 read/write capacity units.
3. THE Memo_Tracker SHALL use AWS_API_Gateway to expose REST API endpoints to remain within the free-tier limit of 1 million API calls per month.
4. THE Facial_Recognition_Service SHALL use AWS_Rekognition to remain within the free-tier limit of 5,000 API calls per month.
5. THE Voice_Service SHALL use AWS_Transcribe to remain within the free-tier limit of 60 minutes of transcription per month.
6. THE Voice_Service SHALL use AWS_Polly to remain within the free-tier limit of 5 million characters per month.
7. THE Auth_Service SHALL use AWS_Cognito for user pool management to remain within the free-tier limit of 50,000 monthly active users.
8. THE Memo_Tracker SHALL use AWS_S3 for storing biometric data and memo attachments to remain within the free-tier limit of 5 GB storage.

### Requirement 11: Mobile Application Platform

**User Story:** As a Regular_User, I want to use the application on my mobile device, so that I can track memos from anywhere in the office.

#### Acceptance Criteria

1. THE Mobile_App SHALL be built using React Native to support both iOS and Android platforms from a single codebase.
2. THE Mobile_App SHALL communicate with the backend exclusively through REST API endpoints exposed by AWS_API_Gateway.
3. WHEN the Mobile_App loses network connectivity, THE Mobile_App SHALL display a clear offline notification and queue pending operations for submission when connectivity is restored.
4. THE Mobile_App SHALL request device permissions for camera and microphone access before initiating biometric or voice operations.
5. IF the user denies camera or microphone permissions, THEN THE Mobile_App SHALL display a message explaining that the denied permission is required for the requested feature.

### Requirement 12: Data Security and Privacy

**User Story:** As a Superuser, I want all memo data and biometric information to be secured, so that sensitive government information is protected.

#### Acceptance Criteria

1. THE Memo_Tracker SHALL encrypt all data at rest using AWS-managed encryption keys in DynamoDB and S3.
2. THE Memo_Tracker SHALL enforce HTTPS for all communication between the Mobile_App and the backend API.
3. THE Auth_Service SHALL issue time-limited authentication tokens with a maximum validity of 1 hour.
4. WHEN an authentication token expires, THE Mobile_App SHALL require the user to re-authenticate before performing further operations.
5. THE Memo_Tracker SHALL store biometric reference data (facial images and voice samples) in a dedicated, access-restricted AWS_S3 bucket separate from memo data.
