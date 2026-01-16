# Meeting Intelligence Assistant - Comprehensive Architecture

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Component Details](#component-details)
4. [Data Flow](#data-flow)
5. [Step Functions Workflow](#step-functions-workflow)
6. [Lambda Functions](#lambda-functions)
7. [DynamoDB Schema](#dynamodb-schema)
8. [S3 Bucket Structure](#s3-bucket-structure)
9. [Google Drive Integration](#google-drive-integration)
10. [Error Handling & Retries](#error-handling--retries)
11. [Monitoring & Logging](#monitoring--logging)
12. [Cost Estimation](#cost-estimation)
13. [Deployment Guide](#deployment-guide)
14. [Security Considerations](#security-considerations)

---

## System Overview

### Purpose
End-to-end serverless system that automatically processes Google Meet recordings to generate:
- Accurate transcriptions with speaker diarization and timestamps
- Intelligent summaries per 10-minute segment
- Actionable items extracted from meetings
- Email and Slack notifications with results

### Key Features
- **Automatic Trigger**: Google Drive webhook triggers processing when recording uploaded
- **Parallel Processing**: Concurrent Lambda executions for transcription and summarization
- **Speaker Diarization**: Identifies who said what during meetings
- **Multi-language Support**: Handles multiple languages and accents
- **Retry Logic**: Automatic retry for failed chunks (max 3 attempts)
- **Notifications**: Email (SES) and Slack integration

### Technical Stack
- **Cloud Provider**: AWS
- **Orchestration**: Step Functions (Standard Workflow)
- **Compute**: Lambda Functions (15-min timeout)
- **Storage**: S3, DynamoDB
- **APIs**: OpenAI Whisper (STT), GPT-4o Mini (Summarization)
- **Integrations**: Google Drive API, AWS SES, Slack API

### Meeting Constraints
- **Max Duration**: 1 hour
- **Chunk Size**: 10 minutes
- **Max Chunks**: 6 per meeting
- **Video Format**: MP4 (Google Meet default)
- **Audio Format**: WAV (for Whisper compatibility)

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            GOOGLE DRIVE                                 │
│                    (Meeting Recordings Folder)                          │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             │ Webhook (Push Notification)
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          API GATEWAY                                    │
│                    POST /meeting-webhook                                │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    LAMBDA: WebhookHandler                               │
│  - Validate webhook signature                                          │
│  - Extract file metadata                                               │
│  - Generate meeting_id                                                 │
│  - Start Step Functions execution                                      │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      STEP FUNCTIONS WORKFLOW                            │
│                                                                         │
│  1. Download Video (Lambda: VideoDownloader)                           │
│                    ▼                                                    │
│  2. Extract Audio (Lambda: AudioExtractor)                             │
│                    ▼                                                    │
│  3. Split Audio into 10-min chunks (Lambda: AudioChunker)              │
│                    ▼                                                    │
│  4. PARALLEL: Transcribe each chunk (Lambda: Transcriber) [6x]         │
│                    ▼                                                    │
│  5. PARALLEL: Summarize each chunk (Lambda: Summarizer) [6x]           │
│                    ▼                                                    │
│  6. Combine Results (Lambda: ResultCombiner)                           │
│                    ▼                                                    │
│  7. Send Notifications (Lambda: NotificationSender)                    │
│                                                                         │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         DATA STORAGE                                    │
│                                                                         │
│  S3 Bucket: meeting-intelligence-data                                  │
│  - Original videos                                                     │
│  - Extracted audio files                                               │
│  - Audio chunks                                                        │
│  - Transcripts                                                         │
│  - Summaries                                                           │
│                                                                         │
│  DynamoDB Table: MeetingProcessing                                     │
│  - Meeting metadata                                                    │
│  - Processing status                                                   │
│  - Transcripts                                                         │
│  - Summaries                                                           │
│  - Action items                                                        │
└─────────────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        NOTIFICATION LAYER                               │
│                                                                         │
│  AWS SES (Email)          Slack API (Channel)                          │
│  - Hardcoded recipients   - Hardcoded channel                          │
│  - Plain text format      - Plain text format                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Component Details

### 1. Google Drive Webhook Integration

**Setup Requirements:**
- Google Cloud Project with Drive API enabled
- Service Account with appropriate permissions
- Push Notification channel configured for specific folder
- Webhook URL registered with Google

**Webhook Payload:**
```json
{
  "kind": "drive#change",
  "id": "file_id_here",
  "resourceId": "resource_id",
  "resourceUri": "https://www.googleapis.com/drive/v3/files/file_id",
  "changed": true
}
```

### 2. API Gateway

**Configuration:**
- REST API
- POST endpoint: `/meeting-webhook`
- Integration: Lambda (WebhookHandler)
- Authentication: API Key (for webhook validation)
- CORS: Disabled (server-to-server)

### 3. Step Functions State Machine

**Type:** Standard Workflow
**Max Duration:** ~45 minutes (well within 1-year limit)
**Pricing:** ~$0.025 per workflow execution

**States:**
1. DownloadVideo
2. ExtractAudio
3. ChunkAudio
4. ParallelTranscription (Map state)
5. ParallelSummarization (Map state)
6. CombineResults
7. SendNotifications

**Error Handling:**
- Each Lambda has retry policy (3 attempts)
- Exponential backoff: 2s, 4s, 8s
- Failed chunks logged but don't stop workflow
- Manual retry via Step Functions console

---

## Data Flow

### Stage 1: Ingestion
```
Google Drive → Webhook → API Gateway → WebhookHandler Lambda
```
**Data:**
- file_id from Google Drive
- file_name (e.g., "Team Standup - 2024-01-15.mp4")
- meeting_id (generated UUID)

**Actions:**
- Validate webhook signature
- Create DynamoDB entry (status: "initiated")
- Start Step Functions execution

### Stage 2: Download & Extraction
```
Step Functions → VideoDownloader → S3 → AudioExtractor → S3
```
**Data Flow:**
- Download video from GDrive to Lambda /tmp
- Upload to S3: `meetings/{meeting_id}/original_video.mp4`
- Extract audio using FFmpeg
- Upload to S3: `meetings/{meeting_id}/audio.wav`

**DynamoDB Update:**
- status: "audio_extracted"
- audio_duration: "3600s"

### Stage 3: Audio Chunking
```
AudioChunker Lambda → S3 (6 chunks)
```
**Data Flow:**
- Split audio.wav into 10-minute segments with 30s overlap
- Upload to S3: `meetings/{meeting_id}/chunks/chunk_0.wav` ... `chunk_5.wav`

**Chunk Metadata:**
```json
{
  "chunk_0": {"start": 0, "end": 600, "overlap_next": 30},
  "chunk_1": {"start": 570, "end": 1170, "overlap_next": 30},
  ...
}
```

### Stage 4: Parallel Transcription
```
Map State → 6x Transcriber Lambda → OpenAI Whisper API → S3
```
**Data Flow (per chunk):**
- Load chunk from S3
- Call Whisper API with params:
  ```json
  {
    "model": "whisper-1",
    "file": "chunk_0.wav",
    "language": "auto",
    "response_format": "verbose_json",
    "timestamp_granularities": ["segment", "word"]
  }
  ```
- Save transcript to S3: `meetings/{meeting_id}/transcripts/transcript_0.json`

**Transcript Format:**
```json
{
  "task": "transcribe",
  "language": "english",
  "duration": 600.0,
  "segments": [
    {
      "id": 0,
      "start": 0.0,
      "end": 5.2,
      "text": "Good morning everyone, let's start the standup.",
      "speaker": "SPEAKER_00",
      "words": [...]
    }
  ]
}
```

### Stage 5: Parallel Summarization
```
Map State → 6x Summarizer Lambda → GPT-4o Mini → S3
```
**Data Flow (per chunk):**
- Load transcript from S3
- Call GPT-4o Mini with prompt:
  ```
  You are analyzing a 10-minute segment of a meeting transcript.
  
  TRANSCRIPT:
  {transcript_text_with_speakers_and_timestamps}
  
  Generate:
  1. SUMMARY: Concise summary of key discussion points (2-3 sentences)
  2. ACTION ITEMS: List of actionable tasks mentioned
  
  Format:
  SUMMARY:
  [Your summary here]
  
  ACTION ITEMS:
  - Action: [task] | Owner: [person if mentioned] | Due: [date if mentioned]
  ```
- Save to S3: `meetings/{meeting_id}/summaries/summary_0.json`

**Summary Format:**
```json
{
  "chunk_id": 0,
  "time_range": "00:00-10:00",
  "summary": "Team discussed the product roadmap...",
  "action_items": [
    {
      "action": "Review API documentation",
      "owner": "John",
      "due_date": "2024-01-20"
    }
  ]
}
```

### Stage 6: Combine Results
```
ResultCombiner Lambda → DynamoDB
```
**Data Flow:**
- Load all 6 summaries from S3
- Concatenate summaries in chronological order
- Deduplicate action items (if same action mentioned multiple times)
- Store in DynamoDB:
  - meeting_id
  - full_transcript (all chunks combined)
  - final_summary (all chunk summaries)
  - action_items (deduplicated list)
  - processing_status: "completed"

### Stage 7: Notifications
```
NotificationSender Lambda → SES & Slack API
```
**Email (Plain Text):**
```
Subject: Meeting Intelligence Report - {meeting_name}

Meeting: {meeting_name}
Date: {date}
Duration: {duration}

SUMMARY:
{final_summary}

ACTION ITEMS:
{action_items_list}

---
Full transcript available in DynamoDB
```

**Slack Message:**
```
📊 Meeting Intelligence Report

*Meeting:* {meeting_name}
*Date:* {date}
*Duration:* {duration}

*Summary:*
{final_summary}

*Action Items:*
{action_items_list}
```

---

## Step Functions Workflow

### State Machine Definition (JSON)

```json
{
  "Comment": "Meeting Intelligence Processing Workflow",
  "StartAt": "DownloadVideo",
  "States": {
    "DownloadVideo": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:VideoDownloader",
      "Retry": [
        {
          "ErrorEquals": ["States.ALL"],
          "IntervalSeconds": 2,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error",
          "Next": "HandleFailure"
        }
      ],
      "Next": "ExtractAudio"
    },
    
    "ExtractAudio": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:AudioExtractor",
      "Retry": [
        {
          "ErrorEquals": ["States.ALL"],
          "IntervalSeconds": 2,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Next": "ChunkAudio"
    },
    
    "ChunkAudio": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:AudioChunker",
      "Retry": [
        {
          "ErrorEquals": ["States.ALL"],
          "IntervalSeconds": 2,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Next": "ParallelTranscription"
    },
    
    "ParallelTranscription": {
      "Type": "Map",
      "ItemsPath": "$.chunks",
      "MaxConcurrency": 6,
      "Iterator": {
        "StartAt": "TranscribeChunk",
        "States": {
          "TranscribeChunk": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:Transcriber",
            "Retry": [
              {
                "ErrorEquals": ["States.ALL"],
                "IntervalSeconds": 2,
                "MaxAttempts": 3,
                "BackoffRate": 2.0
              }
            ],
            "End": true
          }
        }
      },
      "ResultPath": "$.transcripts",
      "Next": "ParallelSummarization"
    },
    
    "ParallelSummarization": {
      "Type": "Map",
      "ItemsPath": "$.transcripts",
      "MaxConcurrency": 6,
      "Iterator": {
        "StartAt": "SummarizeChunk",
        "States": {
          "SummarizeChunk": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:Summarizer",
            "Retry": [
              {
                "ErrorEquals": ["States.ALL"],
                "IntervalSeconds": 2,
                "MaxAttempts": 3,
                "BackoffRate": 2.0
              }
            ],
            "End": true
          }
        }
      },
      "ResultPath": "$.summaries",
      "Next": "CombineResults"
    },
    
    "CombineResults": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:ResultCombiner",
      "Next": "SendNotifications"
    },
    
    "SendNotifications": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:NotificationSender",
      "Retry": [
        {
          "ErrorEquals": ["States.ALL"],
          "IntervalSeconds": 2,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Next": "Success"
    },
    
    "Success": {
      "Type": "Succeed"
    },
    
    "HandleFailure": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:FailureHandler",
      "Next": "Failure"
    },
    
    "Failure": {
      "Type": "Fail",
      "Error": "ProcessingFailed",
      "Cause": "Meeting processing workflow failed"
    }
  }
}
```

---

## Lambda Functions

### 1. WebhookHandler

**Purpose:** Validate webhook and start Step Functions

**Runtime:** Python 3.11  
**Timeout:** 30 seconds  
**Memory:** 256 MB

**Environment Variables:**
```
STEP_FUNCTIONS_ARN=arn:aws:states:region:account:stateMachine:MeetingIntelligence
DYNAMODB_TABLE=MeetingProcessing
WEBHOOK_SECRET=your_google_webhook_secret
```

**Code Outline:**
```python
import json
import boto3
import hashlib
from datetime import datetime

def lambda_handler(event, context):
    # 1. Validate webhook signature
    # 2. Extract file_id from webhook payload
    # 3. Generate meeting_id (UUID)
    # 4. Create DynamoDB entry
    # 5. Start Step Functions execution
    # 6. Return 200 OK
```

### 2. VideoDownloader

**Purpose:** Download video from Google Drive to S3

**Runtime:** Python 3.11  
**Timeout:** 15 minutes (900 seconds)  
**Memory:** 3008 MB (for large video files)

**Environment Variables:**
```
S3_BUCKET=meeting-intelligence-data
GOOGLE_SERVICE_ACCOUNT_KEY=base64_encoded_key
```

**Layers:**
- Google API Client libraries

**Code Outline:**
```python
import boto3
from googleapiclient.discovery import build
from google.oauth2 import service_account

def lambda_handler(event, context):
    meeting_id = event['meeting_id']
    file_id = event['file_id']
    
    # 1. Authenticate with Google Drive
    # 2. Download video to /tmp
    # 3. Upload to S3: meetings/{meeting_id}/original_video.mp4
    # 4. Return S3 path
```

### 3. AudioExtractor

**Purpose:** Extract audio from video using FFmpeg

**Runtime:** Python 3.11  
**Timeout:** 15 minutes  
**Memory:** 3008 MB

**Environment Variables:**
```
S3_BUCKET=meeting-intelligence-data
```

**Layers:**
- FFmpeg static binary layer

**Code Outline:**
```python
import boto3
import subprocess

def lambda_handler(event, context):
    meeting_id = event['meeting_id']
    video_s3_path = event['video_s3_path']
    
    # 1. Download video from S3 to /tmp
    # 2. Extract audio using FFmpeg:
    #    ffmpeg -i input.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 output.wav
    # 3. Upload audio to S3: meetings/{meeting_id}/audio.wav
    # 4. Get audio duration
    # 5. Return audio_s3_path, duration
```

### 4. AudioChunker

**Purpose:** Split audio into 10-minute chunks with overlap

**Runtime:** Python 3.11  
**Timeout:** 10 minutes  
**Memory:** 2048 MB

**Environment Variables:**
```
S3_BUCKET=meeting-intelligence-data
CHUNK_DURATION=600  # 10 minutes in seconds
OVERLAP_DURATION=30  # 30 seconds overlap
```

**Layers:**
- PyDub or FFmpeg

**Code Outline:**
```python
import boto3
from pydub import AudioSegment

def lambda_handler(event, context):
    meeting_id = event['meeting_id']
    audio_s3_path = event['audio_s3_path']
    duration = event['duration']
    
    # 1. Download audio from S3
    # 2. Calculate number of chunks (ceil(duration / 600))
    # 3. Split audio with 30s overlap:
    #    chunk_0: 0-600s
    #    chunk_1: 570-1170s (30s overlap with chunk_0)
    #    chunk_2: 1140-1740s
    # 4. Upload chunks to S3: meetings/{meeting_id}/chunks/chunk_{i}.wav
    # 5. Return array of chunk metadata
```

**Output:**
```json
{
  "chunks": [
    {
      "chunk_id": 0,
      "s3_path": "meetings/{meeting_id}/chunks/chunk_0.wav",
      "start_time": 0,
      "end_time": 600
    },
    ...
  ]
}
```

### 5. Transcriber

**Purpose:** Transcribe audio chunk using OpenAI Whisper

**Runtime:** Python 3.11  
**Timeout:** 5 minutes  
**Memory:** 512 MB

**Environment Variables:**
```
S3_BUCKET=meeting-intelligence-data
OPENAI_API_KEY=your_openai_key
```

**Code Outline:**
```python
import boto3
import openai

def lambda_handler(event, context):
    chunk_info = event  # {chunk_id, s3_path, start_time, end_time}
    
    # 1. Download chunk from S3 to /tmp
    # 2. Call Whisper API:
    transcript = openai.Audio.transcribe(
        model="whisper-1",
        file=audio_file,
        response_format="verbose_json",
        timestamp_granularities=["segment", "word"]
    )
    # 3. Add chunk metadata to transcript
    # 4. Upload to S3: meetings/{meeting_id}/transcripts/transcript_{chunk_id}.json
    # 5. Return transcript_s3_path
```

**Retry Logic:**
- Handles rate limits (429 errors)
- Exponential backoff
- Max 3 retries per chunk

### 6. Summarizer

**Purpose:** Generate summary and extract action items using GPT-4o Mini

**Runtime:** Python 3.11  
**Timeout:** 3 minutes  
**Memory:** 512 MB

**Environment Variables:**
```
S3_BUCKET=meeting-intelligence-data
OPENAI_API_KEY=your_openai_key
```

**Code Outline:**
```python
import boto3
import openai
import json

def lambda_handler(event, context):
    transcript_info = event  # {chunk_id, transcript_s3_path}
    
    # 1. Download transcript from S3
    # 2. Format transcript with speakers and timestamps
    # 3. Call GPT-4o Mini with structured prompt
    # 4. Parse response into summary and action_items
    # 5. Upload to S3: meetings/{meeting_id}/summaries/summary_{chunk_id}.json
    # 6. Return summary_s3_path
```

**Prompt Template:**
```
You are analyzing a 10-minute segment of a meeting transcript.

TRANSCRIPT:
[Segment with speakers and timestamps]

Generate:
1. SUMMARY: 2-3 sentence summary of key discussion points
2. ACTION ITEMS: Extract all actionable tasks mentioned

Format your response as:
SUMMARY:
[Your concise summary]

ACTION ITEMS:
- Action: [specific task] | Owner: [person name if mentioned] | Due: [date if mentioned]
- Action: [specific task] | Owner: [person name if mentioned] | Due: [date if mentioned]

If no action items found, write "None"
```

### 7. ResultCombiner

**Purpose:** Combine all summaries and action items

**Runtime:** Python 3.11  
**Timeout:** 2 minutes  
**Memory:** 1024 MB

**Environment Variables:**
```
S3_BUCKET=meeting-intelligence-data
DYNAMODB_TABLE=MeetingProcessing
```

**Code Outline:**
```python
import boto3
import json

def lambda_handler(event, context):
    meeting_id = event['meeting_id']
    summaries = event['summaries']  # Array of summary S3 paths
    
    # 1. Download all summaries from S3
    # 2. Combine transcripts in chronological order
    # 3. Concatenate summaries
    # 4. Deduplicate action items (fuzzy matching)
    # 5. Store in DynamoDB:
    #    - meeting_id
    #    - full_transcript
    #    - final_summary
    #    - action_items
    #    - status: "completed"
    # 6. Return combined results
```

**Deduplication Logic:**
```python
# Compare action items for similarity
# If >80% similar, keep only one
# Use simple string matching or embedding similarity
```

### 8. NotificationSender

**Purpose:** Send email via SES and message to Slack

**Runtime:** Python 3.11  
**Timeout:** 2 minutes  
**Memory:** 256 MB

**Environment Variables:**
```
SES_SENDER_EMAIL=noreply@yourdomain.com
EMAIL_RECIPIENTS=["user1@company.com", "user2@company.com"]
SLACK_WEBHOOK_URL=your_slack_webhook_url
```

**Code Outline:**
```python
import boto3
import requests
import json

def lambda_handler(event, context):
    meeting_id = event['meeting_id']
    final_summary = event['final_summary']
    action_items = event['action_items']
    
    # 1. Format email content (plain text)
    # 2. Send via SES
    # 3. Format Slack message (plain text)
    # 4. Send to Slack webhook
    # 5. Log any failures (don't retry)
```

**Error Handling:**
- If email fails: Log to CloudWatch, continue
- If Slack fails: Log to CloudWatch, continue
- Don't fail entire workflow for notification issues

### 9. FailureHandler

**Purpose:** Handle workflow failures and update DynamoDB

**Runtime:** Python 3.11  
**Timeout:** 1 minute  
**Memory:** 256 MB

**Code Outline:**
```python
import boto3

def lambda_handler(event, context):
    meeting_id = event['meeting_id']
    error = event['error']
    
    # 1. Update DynamoDB: status = "failed"
    # 2. Store error details
    # 3. Log to CloudWatch
```

---

## DynamoDB Schema

### Table: MeetingProcessing

**Primary Key:**
- Partition Key: `meeting_id` (String)

**Global Secondary Index 1:**
- GSI Name: `StatusIndex`
- Partition Key: `status` (String)
- Sort Key: `created_at` (Number - Unix timestamp)
- Projection: ALL
- Use case: Query all meetings by status

**Global Secondary Index 2:**
- GSI Name: `DateIndex`
- Partition Key: `date` (String - YYYY-MM-DD)
- Sort Key: `created_at` (Number)
- Projection: ALL
- Use case: Query meetings by date

**Attributes:**

```json
{
  "meeting_id": "550e8400-e29b-41d4-a716-446655440000",
  "file_id": "google_drive_file_id",
  "file_name": "Team Standup - 2024-01-15.mp4",
  "created_at": 1705334400,
  "updated_at": 1705336200,
  "status": "completed",  // initiated | downloading | processing | completed | failed
  "date": "2024-01-15",
  "duration_seconds": 3600,
  
  "s3_paths": {
    "video": "meetings/550e8400.../original_video.mp4",
    "audio": "meetings/550e8400.../audio.wav",
    "chunks": ["meetings/550e8400.../chunks/chunk_0.wav", ...],
    "transcripts": ["meetings/550e8400.../transcripts/transcript_0.json", ...],
    "summaries": ["meetings/550e8400.../summaries/summary_0.json", ...]
  },
  
  "full_transcript": {
    "chunks": [
      {
        "chunk_id": 0,
        "time_range": "00:00-10:00",
        "text": "Complete transcript text with speaker labels...",
        "segments": [...]
      }
    ]
  },
  
  "final_summary": "Comprehensive meeting summary combining all chunks...",
  
  "action_items": [
    {
      "action": "Review API documentation and provide feedback",
      "owner": "John Smith",
      "due_date": "2024-01-20",
      "mentioned_at": "00:15:30"
    }
  ],
  
  "processing_metadata": {
    "step_functions_execution_arn": "arn:aws:states:...",
    "transcription_cost": 0.36,  // USD
    "summarization_cost": 0.12,  // USD
    "total_processing_time": 420  // seconds
  },
  
  "error_info": {
    "failed_at": "transcription",
    "error_message": "Rate limit exceeded",
    "retry_count": 3
  }
}
```

**Table Configuration:**
- Billing Mode: On-Demand (or Provisioned with auto-scaling)
- Point-in-time Recovery: Enabled
- Encryption: AWS managed keys

---

## S3 Bucket Structure

### Bucket: meeting-intelligence-data

**Folder Structure:**
```
meetings/
├── {meeting_id_1}/
│   ├── original_video.mp4          # Downloaded from Google Drive
│   ├── audio.wav                    # Extracted audio
│   ├── chunks/
│   │   ├── chunk_0.wav              # 00:00-10:00
│   │   ├── chunk_1.wav              # 09:30-19:30
│   │   ├── chunk_2.wav              # 19:00-29:00
│   │   ├── chunk_3.wav              # 28:30-38:30
│   │   ├── chunk_4.wav              # 38:00-48:00
│   │   └── chunk_5.wav              # 47:30-60:00
│   ├── transcripts/
│   │   ├── transcript_0.json        # Whisper output for chunk 0
│   │   ├── transcript_1.json
│   │   ├── transcript_2.json
│   │   ├── transcript_3.json
│   │   ├── transcript_4.json
│   │   └── transcript_5.json
│   └── summaries/
│       ├── summary_0.json           # GPT-4o mini output for chunk 0
│       ├── summary_1.json
│       ├── summary_2.json
│       ├── summary_3.json
│       ├── summary_4.json
│       └── summary_5.json
│
└── {meeting_id_2}/
    └── ...
```

**Lifecycle Policy:**
- Transition to S3 Intelligent-Tiering after 30 days
- Delete original_video.mp4 and audio.wav after 90 days (keep transcripts/summaries)
- Or configure based on retention requirements

**Bucket Policy:**
- Only Lambda execution roles can read/write
- Encryption at rest: AES-256
- Versioning: Disabled (not needed for this use case)

---

## Google Drive Integration

### Setup Steps

#### 1. Create Google Cloud Project
```bash
# 1. Go to https://console.cloud.google.com/
# 2. Create new project: "meeting-intelligence"
# 3. Enable Google Drive API
```

#### 2. Create Service Account
```bash
# 1. Go to IAM & Admin > Service Accounts
# 2. Create service account: "meeting-processor"
# 3. Grant role: "Drive API User"
# 4. Create JSON key
# 5. Download and encode as base64:
cat service-account-key.json | base64 > encoded-key.txt
```

#### 3. Share Drive Folder
```bash
# 1. Create folder in Google Drive: "Meeting Recordings"
# 2. Share with service account email: meeting-processor@project-id.iam.gserviceaccount.com
# 3. Give "Editor" permissions
# 4. Note folder ID from URL: https://drive.google.com/drive/folders/{FOLDER_ID}
```

#### 4. Set Up Push Notifications

**Register Webhook:**
```python
from googleapiclient.discovery import build
from google.oauth2 import service_account

# Authenticate
credentials = service_account.Credentials.from_service_account_file('key.json')
service = build('drive', 'v3', credentials=credentials)

# Create notification channel
channel = {
    'id': 'meeting-intelligence-channel',
    'type': 'web_hook',
    'address': 'https://{api-gateway-url}/meeting-webhook',
    'expiration': 1234567890000,  # Unix timestamp in milliseconds
    'token': 'your-verification-token'
}

# Watch for changes in folder
watch_response = service.files().watch(
    fileId='{FOLDER_ID}',
    body=channel
).execute()

print(f"Channel created: {watch_response}")
```

**Renewal Script (Run monthly):**
```python
# Channels expire - renew before expiration
# Store channel_id and resource_id from watch_response
# Run this Lambda on CloudWatch Events (monthly)

def renew_channel(event, context):
    # Stop old channel
    service.channels().stop(
        body={
            'id': channel_id,
            'resourceId': resource_id
        }
    ).execute()
    
    # Create new channel (same code as above)
```

#### 5. Webhook Validation

**In WebhookHandler Lambda:**
```python
import hmac
import hashlib

def validate_webhook(headers, body):
    # Google sends X-Goog-Channel-Token header
    token = headers.get('X-Goog-Channel-Token')
    
    # Compare with your stored token
    if token != os.environ['WEBHOOK_SECRET']:
        return False
    
    # Additional validation: check X-Goog-Resource-State
    state = headers.get('X-Goog-Resource-State')
    if state not in ['sync', 'add', 'remove', 'update', 'trash', 'untrash', 'change']:
        return False
    
    return True
```

---

## Error Handling & Retries

### Retry Strategy

**Lambda-Level Retries:**
- All Lambdas configured with 3 retry attempts
- Exponential backoff: 2s, 4s, 8s
- Applies to: transient errors, rate limits, network issues

**Step Functions Retry Configuration:**
```json
"Retry": [
  {
    "ErrorEquals": ["States.ALL"],
    "IntervalSeconds": 2,
    "MaxAttempts": 3,
    "BackoffRate": 2.0
  }
]
```

**Chunk-Level Independence:**
- Failed chunks don't stop parallel processing
- If chunk 3 fails, chunks 0,1,2,4,5 still proceed
- Final summary notes missing chunks

### Error Scenarios

#### Scenario 1: Video Download Fails
```
Cause: Google Drive quota exceeded, network timeout
Action: Retry 3 times, then fail workflow
Manual Fix: Re-trigger via Step Functions console
```

#### Scenario 2: Whisper Rate Limit (429)
```
Cause: Too many API calls
Action: Automatic retry with exponential backoff
Max Retries: 3
Fallback: Skip chunk, note in final summary
```

#### Scenario 3: Audio Extraction Fails
```
Cause: Corrupted video file, unsupported codec
Action: Retry 3 times
Manual Fix: Download video manually, check format, re-upload
```

#### Scenario 4: GPT-4o Mini Timeout
```
Cause: Large transcript, slow API response
Action: Retry 3 times
Optimization: Consider chunking large transcripts further
```

#### Scenario 5: Notification Failure
```
Cause: SES quota exceeded, Slack webhook down
Action: Log error, don't retry (avoid duplicate notifications)
Manual Fix: Check CloudWatch logs, resend manually if needed
```

### Failure Tracking

**DynamoDB Updates:**
```json
{
  "status": "failed",
  "error_info": {
    "failed_at": "transcription",
    "failed_chunk": 3,
    "error_message": "OpenAI rate limit exceeded after 3 retries",
    "timestamp": 1705336200,
    "retry_count": 3
  }
}
```

**CloudWatch Alarms:**
- Alarm: `MeetingProcessingFailures`
- Metric: Custom metric from FailureHandler Lambda
- Threshold: > 3 failures in 1 hour
- Action: SNS notification to ops team

### Manual Retry Process

**Via Step Functions Console:**
1. Navigate to failed execution
2. Identify failed state
3. Click "Restart from failed state"
4. Or start new execution with same input

**Via Lambda:**
```python
# Trigger new execution for failed meeting
stepfunctions = boto3.client('stepfunctions')

stepfunctions.start_execution(
    stateMachineArn='arn:aws:states:...',
    name=f'retry-{meeting_id}-{timestamp}',
    input=json.dumps({
        'meeting_id': meeting_id,
        'file_id': file_id
    })
)
```

---

## Monitoring & Logging

### CloudWatch Logs

**Log Groups:**
```
/aws/lambda/WebhookHandler
/aws/lambda/VideoDownloader
/aws/lambda/AudioExtractor
/aws/lambda/AudioChunker
/aws/lambda/Transcriber
/aws/lambda/Summarizer
/aws/lambda/ResultCombiner
/aws/lambda/NotificationSender
/aws/lambda/FailureHandler
/aws/stepfunctions/MeetingIntelligence
```

**Retention:** 30 days (configurable)

**Log Insights Queries:**

```sql
-- Find all failed meetings in last 24 hours
fields @timestamp, meeting_id, error_message
| filter status = "failed"
| sort @timestamp desc
| limit 20

-- Track processing time per stage
fields meeting_id, stage, duration
| filter stage in ["download", "extract", "transcribe", "summarize"]
| stats avg(duration) by stage

-- Monitor API costs
fields meeting_id, transcription_cost, summarization_cost
| stats sum(transcription_cost) as total_whisper_cost,
        sum(summarization_cost) as total_gpt_cost
```

### Custom Metrics

**Publish from Lambdas:**
```python
import boto3
cloudwatch = boto3.client('cloudwatch')

# Example: Track processing time
cloudwatch.put_metric_data(
    Namespace='MeetingIntelligence',
    MetricData=[
        {
            'MetricName': 'ProcessingTime',
            'Value': duration_seconds,
            'Unit': 'Seconds',
            'Dimensions': [
                {'Name': 'Stage', 'Value': 'Transcription'}
            ]
        }
    ]
)
```

**Key Metrics:**
- `ProcessingTime` (per stage)
- `APICallCount` (Whisper, GPT-4o)
- `APIErrorRate` (rate limits, failures)
- `ChunkProcessingSuccess` (% of chunks successfully processed)
- `NotificationDelivery` (email/Slack success rate)

### CloudWatch Dashboard

**Widgets:**
1. Total Meetings Processed (last 7 days)
2. Success vs Failure Rate
3. Average Processing Time per Stage
4. API Cost Trends
5. Error Rate by Type
6. Concurrent Step Functions Executions

---

## Cost Estimation

### Assumptions
- **Meetings per day:** 10
- **Average duration:** 45 minutes
- **Working days:** 22/month
- **Total meetings/month:** 220

### Cost Breakdown

#### 1. AWS Lambda
```
WebhookHandler:     220 invocations × $0.0000002/invoke = $0.00
VideoDownloader:    220 × 5 min × 3GB × $0.0000166667 = $0.61
AudioExtractor:     220 × 3 min × 3GB × $0.0000166667 = $0.37
AudioChunker:       220 × 2 min × 2GB × $0.0000133333 = $0.20
Transcriber:        1320 (220×6) × 1 min × 512MB × $0.0000083333 = $0.09
Summarizer:         1320 × 1 min × 512MB × $0.0000083333 = $0.09
ResultCombiner:     220 × 1 min × 1GB × $0.0000166667 = $0.06
NotificationSender: 220 × 30s × 256MB × $0.0000041667 = $0.00
FailureHandler:     ~10 × 30s × 256MB × $0.0000041667 = $0.00

Total Lambda: ~$1.42/month
```

#### 2. AWS Step Functions
```
Standard Workflow: 220 executions × $0.025 = $5.50/month
State Transitions: ~2200 transitions × $0.000025 = $0.06/month

Total Step Functions: ~$5.56/month
```

#### 3. S3 Storage
```
Average meeting size:
- Video: 1.5GB
- Audio: 150MB
- Chunks: 150MB
- Transcripts: 5MB
- Summaries: 1MB
Total per meeting: ~1.8GB

Storage: 220 meetings × 1.8GB = 396GB
S3 Standard (first month): 396GB × $0.023 = $9.11
After lifecycle (Intelligent-Tiering): ~$4.00/month

Total S3: ~$9.11/month (first month), ~$4.00/month (steady state)
```

#### 4. DynamoDB
```
Write Capacity: 220 meetings × 5 writes/meeting = 1100 writes/month
Read Capacity: ~500 reads/month (queries, retrievals)

On-Demand Pricing:
Writes: 1100 × $1.25/million = $0.00
Reads: 500 × $0.25/million = $0.00

Storage: ~0.5GB × $0.25/GB = $0.13

Total DynamoDB: ~$0.13/month
```

#### 5. API Gateway
```
Requests: 220 webhooks
Pricing: 220 × $3.50/million = $0.00

Total API Gateway: ~$0.00/month
```

#### 6. OpenAI API Costs

**Whisper API:**
```
Audio per meeting: 45 min = 2700 seconds
Cost: $0.006 per minute
Per meeting: 45 × $0.006 = $0.27
Monthly: 220 × $0.27 = $59.40
```

**GPT-4o Mini API:**
```
Input tokens per chunk: ~4000 tokens (10-min transcript)
Output tokens per chunk: ~500 tokens (summary + actions)
Chunks per meeting: 5 (45 min / 10 min)

Input cost: 4000 × 6 × 220 × $0.150/1M = $0.79
Output cost: 500 × 6 × 220 × $0.600/1M = $0.40

Monthly: ~$1.19
```

**Total OpenAI: ~$60.59/month**

#### 7. AWS SES
```
Emails: 220 × 2 recipients = 440 emails
First 62,000 emails/month: Free (from EC2/Lambda)

Total SES: $0.00/month
```

#### 8. Slack API
```
Free (webhook-based)
```

### Total Monthly Cost

```
AWS Services:    $16.11
OpenAI APIs:     $60.59
----------------------------
TOTAL:           ~$76.70/month

Per Meeting:     ~$0.35
```

### Cost Optimization Tips

1. **Reduce Video Storage:**
   - Delete original videos after 30 days (save $7/month)
   - Store only transcripts and summaries long-term

2. **Batch Processing:**
   - Process multiple meetings together during off-peak hours
   - Reduces Lambda cold starts

3. **Use Reserved Capacity:**
   - If processing >500 meetings/month, consider Lambda reserved concurrency

4. **Optimize Prompts:**
   - Reduce input tokens by summarizing transcripts before sending to GPT
   - Could reduce GPT costs by 30-40%

5. **Use Spot Instances for Heavy Processing:**
   - For video/audio processing, consider EC2 Spot + Batch instead of Lambda
   - Potential 50% cost savings on compute

---

## Deployment Guide

### Prerequisites

1. **AWS Account** with appropriate permissions
2. **Google Cloud Project** with Drive API enabled
3. **OpenAI API Key**
4. **Slack Workspace** with webhook configured
5. **Domain for SES** (verified email address)

### Step 1: Infrastructure Setup

**Option A: AWS SAM Template**

Create `template.yaml`:
```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31

Parameters:
  GoogleServiceAccountKey:
    Type: String
    NoEcho: true
  OpenAIApiKey:
    Type: String
    NoEcho: true
  SlackWebhookUrl:
    Type: String
    NoEcho: true
  EmailRecipients:
    Type: CommaDelimitedList
  SenderEmail:
    Type: String

Resources:
  # S3 Bucket
  MeetingDataBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: meeting-intelligence-data
      LifecycleConfiguration:
        Rules:
          - Id: TransitionToIntelligentTiering
            Status: Enabled
            Transitions:
              - TransitionInDays: 30
                StorageClass: INTELLIGENT_TIERING
  
  # DynamoDB Table
  MeetingProcessingTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: MeetingProcessing
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: meeting_id
          AttributeType: S
        - AttributeName: status
          AttributeType: S
        - AttributeName: created_at
          AttributeType: N
        - AttributeName: date
          AttributeType: S
      KeySchema:
        - AttributeName: meeting_id
          KeyType: HASH
      GlobalSecondaryIndexes:
        - IndexName: StatusIndex
          KeySchema:
            - AttributeName: status
              KeyType: HASH
            - AttributeName: created_at
              KeyType: RANGE
          Projection:
            ProjectionType: ALL
        - IndexName: DateIndex
          KeySchema:
            - AttributeName: date
              KeyType: HASH
            - AttributeName: created_at
              KeyType: RANGE
          Projection:
            ProjectionType: ALL
  
  # Lambda Functions
  WebhookHandlerFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: WebhookHandler
      Runtime: python3.11
      Handler: webhook_handler.lambda_handler
      Timeout: 30
      MemorySize: 256
      Environment:
        Variables:
          DYNAMODB_TABLE: !Ref MeetingProcessingTable
          STEP_FUNCTIONS_ARN: !GetAtt MeetingIntelligenceStateMachine.Arn
      Policies:
        - DynamoDBCrudPolicy:
            TableName: !Ref MeetingProcessingTable
        - StepFunctionsExecutionPolicy:
            StateMachineName: !GetAtt MeetingIntelligenceStateMachine.Name
  
  # ... (Define all other Lambda functions similarly)
  
  # Step Functions State Machine
  MeetingIntelligenceStateMachine:
    Type: AWS::Serverless::StateMachine
    Properties:
      Name: MeetingIntelligence
      Type: STANDARD
      DefinitionUri: statemachine/definition.json
      DefinitionSubstitutions:
        VideoDownloaderArn: !GetAtt VideoDownloaderFunction.Arn
        AudioExtractorArn: !GetAtt AudioExtractorFunction.Arn
        # ... (all other Lambda ARNs)
      Policies:
        - LambdaInvokePolicy:
            FunctionName: !Ref VideoDownloaderFunction
        # ... (policies for all functions)
  
  # API Gateway
  MeetingWebhookApi:
    Type: AWS::Serverless::Api
    Properties:
      StageName: prod
      DefinitionBody:
        openapi: 3.0.0
        paths:
          /meeting-webhook:
            post:
              x-amazon-apigateway-integration:
                httpMethod: POST
                type: aws_proxy
                uri: !Sub arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${WebhookHandlerFunction.Arn}/invocations

Outputs:
  WebhookUrl:
    Value: !Sub https://${MeetingWebhookApi}.execute-api.${AWS::Region}.amazonaws.com/prod/meeting-webhook
  StateMachineArn:
    Value: !GetAtt MeetingIntelligenceStateMachine.Arn
```

**Deploy:**
```bash
sam build
sam deploy --guided \
  --parameter-overrides \
    GoogleServiceAccountKey=$GOOGLE_KEY \
    OpenAIApiKey=$OPENAI_KEY \
    SlackWebhookUrl=$SLACK_URL \
    EmailRecipients="user1@company.com,user2@company.com" \
    SenderEmail="noreply@yourdomain.com"
```

### Step 2: Lambda Code Deployment

**Directory Structure:**
```
meeting-intelligence/
├── template.yaml
├── statemachine/
│   └── definition.json
├── src/
│   ├── webhook_handler/
│   │   ├── lambda_handler.py
│   │   └── requirements.txt
│   ├── video_downloader/
│   │   ├── lambda_handler.py
│   │   └── requirements.txt
│   ├── audio_extractor/
│   │   ├── lambda_handler.py
│   │   └── requirements.txt
│   └── ... (all other functions)
└── layers/
    ├── ffmpeg/
    └── google-api/
```

**Example: VideoDownloader Lambda**

`src/video_downloader/lambda_handler.py`:
```python
import os
import json
import boto3
import base64
from googleapiclient.discovery import build
from google.oauth2 import service_account
from io import BytesIO

s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['DYNAMODB_TABLE'])

def lambda_handler(event, context):
    meeting_id = event['meeting_id']
    file_id = event['file_id']
    
    # Decode service account key
    key_json = base64.b64decode(os.environ['GOOGLE_SERVICE_ACCOUNT_KEY'])
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(key_json)
    )
    
    # Build Drive API client
    service = build('drive', 'v3', credentials=credentials)
    
    # Download file
    request = service.files().get_media(fileId=file_id)
    file_content = BytesIO()
    downloader = MediaIoBaseDownload(file_content, request)
    
    done = False
    while not done:
        status, done = downloader.next_chunk()
    
    # Upload to S3
    s3_key = f'meetings/{meeting_id}/original_video.mp4'
    s3.put_object(
        Bucket=os.environ['S3_BUCKET'],
        Key=s3_key,
        Body=file_content.getvalue()
    )
    
    # Update DynamoDB
    table.update_item(
        Key={'meeting_id': meeting_id},
        UpdateExpression='SET #s = :status, s3_paths.video = :s3path',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={
            ':status': 'video_downloaded',
            ':s3path': s3_key
        }
    )
    
    return {
        'meeting_id': meeting_id,
        'video_s3_path': s3_key
    }
```

`src/video_downloader/requirements.txt`:
```
google-api-python-client==2.100.0
google-auth==2.23.0
boto3==1.28.0
```

### Step 3: Google Drive Setup

**1. Create Service Account:**
```bash
# In Google Cloud Console
gcloud iam service-accounts create meeting-processor \
  --display-name="Meeting Intelligence Processor"

# Create key
gcloud iam service-accounts keys create key.json \
  --iam-account=meeting-processor@PROJECT_ID.iam.gserviceaccount.com

# Encode for Lambda
cat key.json | base64 > encoded_key.txt
```

**2. Share Folder:**
- Share Google Drive folder with service account email
- Grant "Editor" permissions

**3. Register Webhook:**
```python
# Run this script to set up webhook
from googleapiclient.discovery import build
from google.oauth2 import service_account

credentials = service_account.Credentials.from_service_account_file('key.json')
service = build('drive', 'v3', credentials=credentials)

channel = {
    'id': 'meeting-intelligence-prod',
    'type': 'web_hook',
    'address': 'https://{api-gateway-url}/meeting-webhook',
    'expiration': int((datetime.now() + timedelta(days=30)).timestamp() * 1000)
}

watch = service.files().watch(
    fileId='FOLDER_ID',
    body=channel
).execute()

print(f"Webhook registered: {watch}")
```

### Step 4: SES Configuration

**1. Verify Email:**
```bash
aws ses verify-email-identity --email-address noreply@yourdomain.com
```

**2. Move out of Sandbox (for production):**
- Request sending limit increase in AWS SES console
- Verify domain (optional, for better deliverability)

### Step 5: Slack Integration

**1. Create Slack App:**
- Go to https://api.slack.com/apps
- Create new app
- Enable Incoming Webhooks
- Add webhook to desired channel
- Copy webhook URL

### Step 6: Testing

**1. Manual Test:**
```bash
# Upload test video to Google Drive folder
# Monitor Step Functions execution in AWS Console
# Check DynamoDB for results
# Verify email and Slack notifications
```

**2. End-to-End Test:**
```python
# Simulate webhook trigger
import requests

payload = {
    "kind": "drive#change",
    "id": "test_file_id",
    "resourceId": "test_resource_id"
}

response = requests.post(
    'https://{api-gateway-url}/meeting-webhook',
    json=payload,
    headers={'X-Goog-Channel-Token': 'your-token'}
)

print(response.json())
```

### Step 7: Monitoring Setup

**CloudWatch Dashboard:**
```bash
# Create dashboard
aws cloudwatch put-dashboard \
  --dashboard-name MeetingIntelligence \
  --dashboard-body file://dashboard.json
```

**Alarms:**
```bash
# Create failure alarm
aws cloudwatch put-metric-alarm \
  --alarm-name MeetingProcessingFailures \
  --alarm-description "Alert when >3 meetings fail in 1 hour" \
  --metric-name ProcessingFailures \
  --namespace MeetingIntelligence \
  --statistic Sum \
  --period 3600 \
  --threshold 3 \
  --comparison-operator GreaterThanThreshold
```

---

## Security Considerations

### 1. Secrets Management

**Use AWS Secrets Manager:**
```python
import boto3
import json

def get_secret(secret_name):
    client = boto3.client('secretsmanager')
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response['SecretString'])

# In Lambda
openai_key = get_secret('openai-api-key')
```

**Store:**
- OpenAI API Key
- Google Service Account Key
- Slack Webhook URL
- Webhook verification tokens

### 2. IAM Roles

**Principle of Least Privilege:**

```yaml
# VideoDownloader needs:
- s3:PutObject (specific bucket)
- dynamodb:UpdateItem (specific table)

# Transcriber needs:
- s3:GetObject, s3:PutObject
- secrets:GetSecretValue (OpenAI key)

# NotificationSender needs:
- ses:SendEmail
- dynamodb:GetItem
```

### 3. Data Encryption

**At Rest:**
- S3: Server-side encryption (AES-256)
- DynamoDB: AWS managed keys
- Secrets Manager: Automatic encryption

**In Transit:**
- API Gateway: HTTPS only
- Lambda to S3: Encrypted by default
- OpenAI API: TLS 1.2+

### 4. Access Control

**S3 Bucket Policy:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": "arn:aws:s3:::meeting-intelligence-data/*",
      "Condition": {
        "Bool": {"aws:SecureTransport": "false"}
      }
    }
  ]
}
```

**DynamoDB:**
- Fine-grained access control via IAM
- Enable point-in-time recovery
- Audit access with CloudTrail

### 5. Webhook Security

**Validate All Requests:**
```python
def validate_webhook(event):
    # Check token
    token = event['headers'].get('X-Goog-Channel-Token')
    if token != os.environ['WEBHOOK_SECRET']:
        raise ValueError('Invalid token')
    
    # Check resource state
    state = event['headers'].get('X-Goog-Resource-State')
    if state not in ['add', 'update', 'change']:
        return False
    
    return True
```

### 6. API Rate Limiting

**OpenAI:**
- Implement exponential backoff
- Monitor rate limit headers
- Use circuit breaker pattern

**Google Drive:**
- Respect quota limits
- Implement request throttling

### 7. Data Retention

**Compliance:**
- Define retention policy (e.g., 90 days)
- Implement S3 lifecycle rules
- Provide deletion API for GDPR compliance

### 8. Audit Logging

**CloudTrail:**
- Enable for all S3, DynamoDB, Lambda access
- Retain logs for 1 year
- Set up alerts for suspicious activity

**Application Logs:**
- Log all API calls with timestamps
- Include meeting_id for traceability
- Sanitize sensitive data before logging

---

## Next Steps

### Phase 1: MVP (Weeks 1-2)
- [ ] Set up AWS infrastructure (SAM template)
- [ ] Implement core Lambda functions
- [ ] Create Step Functions workflow
- [ ] Set up Google Drive webhook
- [ ] Test with sample meeting

### Phase 2: Testing & Refinement (Week 3)
- [ ] End-to-end testing with various meeting lengths
- [ ] Optimize chunk overlap logic
- [ ] Improve error handling
- [ ] Set up monitoring and alerts

### Phase 3: Production Launch (Week 4)
- [ ] Security review
- [ ] Cost optimization
- [ ] Documentation
- [ ] User training
- [ ] Go live!

### Future Enhancements
- [ ] Real-time processing (process while meeting ongoing)
- [ ] Speaker identification (train model on company voices)
- [ ] Sentiment analysis (detect conflict, agreement)
- [ ] Integration with calendar (auto-assign action items)
- [ ] Multi-language summaries
- [ ] Custom summary templates per meeting type
- [ ] Searchable meeting archive (Elasticsearch)
- [ ] Analytics dashboard (meeting trends, topic analysis)

---

## Appendix

### A. Sample Prompts

**Summarization Prompt:**
```
You are analyzing a 10-minute segment of a business meeting transcript with speaker labels and timestamps.

TRANSCRIPT:
[00:00] SPEAKER_00: Good morning team. Let's review our Q1 progress.
[00:15] SPEAKER_01: We completed 80% of planned features.
...

Your task:
1. Write a concise 2-3 sentence summary of the main discussion points
2. Extract all action items mentioned

Format:
SUMMARY:
[Your summary]

ACTION ITEMS:
- Action: [specific task] | Owner: [person name] | Due: [date if mentioned]
- ...

If no action items, write "None"
```

**Action Item Combination Prompt:**
```
You have 6 summaries from different parts of a 1-hour meeting.
Combine and deduplicate action items.

SUMMARIES:
[Chunk summaries]

Rules:
- Merge duplicate/similar actions
- Preserve all unique actions
- Maintain owner and due date info
- Sort by priority if implied

Output format:
- Action: [task] | Owner: [name] | Due: [date] | Priority: [High/Medium/Low]
```

### B. FFmpeg Commands

**Extract Audio:**
```bash
ffmpeg -i input.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 output.wav
```

**Split Audio (10-min chunks with 30s overlap):**
```bash
# Chunk 0: 0-600s
ffmpeg -i input.wav -ss 0 -t 600 chunk_0.wav

# Chunk 1: 570-1170s (30s overlap)
ffmpeg -i input.wav -ss 570 -t 600 chunk_1.wav
```

**Get Duration:**
```bash
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 input.wav
```

### C. DynamoDB Query Examples

**Get All Completed Meetings:**
```python
response = table.query(
    IndexName='StatusIndex',
    KeyConditionExpression=Key('status').eq('completed')
)
```

**Get Meetings from Specific Date:**
```python
response = table.query(
    IndexName='DateIndex',
    KeyConditionExpression=Key('date').eq('2024-01-15')
)
```

**Get Meeting with Action Items:**
```python
response = table.get_item(
    Key={'meeting_id': meeting_id},
    ProjectionExpression='action_items, final_summary'
)
```

### D. Useful Links

- [Google Drive API - Push Notifications](https://developers.google.com/drive/api/guides/push)
- [OpenAI Whisper API Documentation](https://platform.openai.com/docs/guides/speech-to-text)
- [AWS Step Functions Best Practices](https://docs.aws.amazon.com/step-functions/latest/dg/best-practices.html)
- [FFmpeg Documentation](https://ffmpeg.org/documentation.html)
- [AWS SAM Reference](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/what-is-sam.html)

---

**End of Architecture Document**

*Version: 1.0*  
*Last Updated: 2024-01-15*  
*Author: AI Classroom - Meeting Intelligence Team*
