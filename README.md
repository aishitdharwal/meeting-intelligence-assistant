# Meeting Intelligence Assistant

Automated serverless system for transcribing and summarizing Google Meet recordings using AWS Lambda, Step Functions, OpenAI Whisper, and GPT-4o Mini.

## Architecture Overview

- **Trigger**: Google Drive webhook when new recording is uploaded
- **Processing**: Step Functions orchestrates 9 Lambda functions
- **Transcription**: OpenAI Whisper API with speaker diarization
- **Summarization**: GPT-4o Mini extracts summaries and action items
- **Storage**: S3 for files, DynamoDB for metadata
- **Notifications**: Slack (and optionally SES email)

## Prerequisites

You should already have:
- ✅ AWS Account with CLI configured
- ✅ AWS SAM CLI installed
- ✅ Google Cloud service account with Drive API access
- ✅ Google Drive folder ID (shared with service account)
- ✅ OpenAI API key
- ✅ Slack webhook URL

## Project Structure

```
meeting-intelligence-assistant/
├── template.yaml                 # SAM infrastructure template
├── samconfig.toml               # SAM deployment config (ap-south-1)
├── statemachine/
│   └── definition.asl.json      # Step Functions workflow
├── src/
│   ├── webhook_handler/         # Receives Google Drive webhooks
│   ├── video_downloader/        # Downloads video from Google Drive
│   ├── audio_extractor/         # Extracts audio using FFmpeg
│   ├── audio_chunker/           # Splits audio into 10-min chunks
│   ├── transcriber/             # Transcribes using Whisper
│   ├── summarizer/              # Summarizes using GPT-4o Mini
│   ├── result_combiner/         # Combines all results
│   ├── notification_sender/     # Sends Slack/email notifications
│   └── failure_handler/         # Handles errors
├── layers/
│   └── ffmpeg/                  # FFmpeg binaries for Lambda
└── config/
    ├── setup-secrets.sh         # Store secrets in AWS Secrets Manager
    └── setup-ffmpeg-layer.sh    # Download FFmpeg binaries
```

## Deployment Steps

### Step 1: Setup FFmpeg Layer

```bash
cd /Users/aishitdharwal/Documents/meeting-intelligence-assistant
./config/setup-ffmpeg-layer.sh
```

This downloads FFmpeg static binaries needed for audio extraction.

### Step 2: Store Secrets in AWS Secrets Manager

```bash
./config/setup-secrets.sh
```

You'll be prompted to enter:
- Path to Google service account JSON key
- Google Drive folder ID
- OpenAI API key
- Slack webhook URL

The script will:
- Base64 encode your Google credentials
- Store all secrets in AWS Secrets Manager (ap-south-1 region)
- Generate a webhook secret token (save this for later)

### Step 3: Build and Deploy with SAM

```bash
# Build the SAM application
sam build

# Deploy (first time - interactive)
sam deploy --guided

# During guided deployment, accept defaults or customize:
# - Stack name: meeting-intelligence-assistant
# - AWS Region: ap-south-1
# - Confirm changes before deploy: Y
# - Allow SAM CLI IAM role creation: Y
# - Disable rollback: N
# - Save arguments to configuration file: Y

# For subsequent deployments, just run:
sam deploy
```

### Step 4: Note Your Webhook URL

After deployment, SAM will output:
```
WebhookUrl: https://xxxxxxxxxx.execute-api.ap-south-1.amazonaws.com/prod/meeting-webhook
```

**Save this URL** - you'll need it to configure Google Drive webhooks.

### Step 5: Configure Google Drive Webhook

Create a Python script to register the webhook:

```python
# register_webhook.py
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime, timedelta

# Path to your service account key
SERVICE_ACCOUNT_FILE = 'path/to/your-service-account-key.json'
FOLDER_ID = 'your-google-drive-folder-id'
WEBHOOK_URL = 'https://xxxxxxxxxx.execute-api.ap-south-1.amazonaws.com/prod/meeting-webhook'
WEBHOOK_SECRET = 'your-webhook-secret-from-step-2'

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=['https://www.googleapis.com/auth/drive.readonly']
)

service = build('drive', 'v3', credentials=credentials)

# Register webhook
channel = {
    'id': 'meeting-intelligence-prod',
    'type': 'web_hook',
    'address': WEBHOOK_URL,
    'token': WEBHOOK_SECRET,
    'expiration': int((datetime.now() + timedelta(days=30)).timestamp() * 1000)
}

watch_response = service.files().watch(
    fileId=FOLDER_ID,
    body=channel
).execute()

print(f"Webhook registered successfully!")
print(f"Channel ID: {watch_response['id']}")
print(f"Resource ID: {watch_response['resourceId']}")
print(f"Expiration: {datetime.fromtimestamp(int(watch_response['expiration'])/1000)}")
```

Run it:
```bash
pip install google-api-python-client google-auth
python register_webhook.py
```

**Important**: Webhooks expire after 30 days. Set a reminder to renew monthly.

### Step 6: Test the System

1. Upload a video file to your Google Drive folder
2. Monitor the Step Functions execution in AWS Console
3. Check CloudWatch Logs for each Lambda function
4. Verify Slack notification is received
5. Check DynamoDB for final results

## System Components

### Lambda Functions

| Function | Timeout | Memory | Purpose |
|----------|---------|--------|---------|
| WebhookHandler | 30s | 256MB | Receives webhook, starts Step Functions |
| VideoDownloader | 15m | 3GB | Downloads video from Google Drive |
| AudioExtractor | 15m | 3GB | Extracts audio using FFmpeg |
| AudioChunker | 10m | 2GB | Splits audio into 10-min chunks |
| Transcriber | 5m | 512MB | Transcribes audio with Whisper API |
| Summarizer | 3m | 512MB | Generates summaries with GPT-4o Mini |
| ResultCombiner | 2m | 1GB | Combines all results |
| NotificationSender | 2m | 256MB | Sends Slack/email notifications |
| FailureHandler | 1m | 256MB | Handles failures |

### Data Flow

```
Google Drive → Webhook → API Gateway → WebhookHandler
                                           ↓
                                    Step Functions
                                           ↓
VideoDownloader → AudioExtractor → AudioChunker
                                           ↓
                        6× Transcriber (parallel)
                                           ↓
                        6× Summarizer (parallel)
                                           ↓
                    ResultCombiner → NotificationSender
                                           ↓
                                        Slack
```

### Storage

**S3 Bucket**: `meeting-intelligence-data-{AWS::AccountId}`
```
meetings/{meeting_id}/
├── original_video.mp4
├── audio.wav
├── chunks/
│   ├── chunk_0.wav
│   ├── chunk_1.wav
│   └── ...
├── transcripts/
│   ├── transcript_0.json
│   ├── transcript_1.json
│   └── ...
├── summaries/
│   ├── summary_0.json
│   ├── summary_1.json
│   └── ...
└── final_result.json
```

**DynamoDB Table**: `MeetingProcessing-prod`
- Primary Key: `meeting_id`
- GSI: `StatusIndex` (status + created_at)
- GSI: `DateIndex` (date + created_at)

## Monitoring

### CloudWatch Logs
```bash
# View webhook handler logs
aws logs tail /aws/lambda/MeetingIntel-WebhookHandler-prod --follow

# View transcriber logs
aws logs tail /aws/lambda/MeetingIntel-Transcriber-prod --follow

# View Step Functions execution logs
aws logs tail /aws/vendedlogs/states/MeetingIntelligence-prod --follow
```

### Check Meeting Status
```python
import boto3

dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
table = dynamodb.Table('MeetingProcessing-prod')

response = table.get_item(Key={'meeting_id': 'your-meeting-id'})
print(response['Item'])
```

### Query by Status
```python
response = table.query(
    IndexName='StatusIndex',
    KeyConditionExpression='#s = :status',
    ExpressionAttributeNames={'#s': 'status'},
    ExpressionAttributeValues={':status': 'completed'}
)
```

## Cost Estimation

For 220 meetings/month (10 per day, 45 min average):

| Service | Cost/Month |
|---------|------------|
| AWS Lambda | ~$1.42 |
| Step Functions | ~$5.56 |
| S3 Storage | ~$9.11 (first month), ~$4.00 (steady) |
| DynamoDB | ~$0.13 |
| API Gateway | ~$0.00 |
| OpenAI Whisper | ~$59.40 |
| OpenAI GPT-4o Mini | ~$1.19 |
| **Total** | **~$77/month** |

**Per meeting**: ~$0.35

## Troubleshooting

### Webhook not triggering
1. Check webhook is registered: Use Google Drive API to list channels
2. Verify webhook URL is correct
3. Check API Gateway logs in CloudWatch
4. Ensure webhook secret matches

### Video download fails
1. Check service account has access to Drive folder
2. Verify service account credentials in Secrets Manager
3. Check Lambda execution role has S3 write permissions
4. Review VideoDownloader CloudWatch logs

### Transcription fails
1. Check OpenAI API key is valid
2. Verify audio file is in correct format (WAV, 16kHz)
3. Check for rate limiting (429 errors)
4. Review Transcriber CloudWatch logs

### No Slack notifications
1. Verify Slack webhook URL in Secrets Manager
2. Test webhook URL manually with curl
3. Check NotificationSender CloudWatch logs

## Updating the System

```bash
# Make changes to Lambda code
# Then rebuild and deploy
sam build
sam deploy
```

## Cleanup

To delete all resources:
```bash
sam delete

# Also delete secrets
aws secretsmanager delete-secret --secret-id meeting-intelligence/google-service-account --force-delete-without-recovery
aws secretsmanager delete-secret --secret-id meeting-intelligence/openai-api-key --force-delete-without-recovery
aws secretsmanager delete-secret --secret-id meeting-intelligence/slack-webhook-url --force-delete-without-recovery
aws secretsmanager delete-secret --secret-id meeting-intelligence/webhook-secret --force-delete-without-recovery
aws secretsmanager delete-secret --secret-id meeting-intelligence/google-drive-folder-id --force-delete-without-recovery
aws secretsmanager delete-secret --secret-id meeting-intelligence/email-recipients --force-delete-without-recovery
```

## Support

For issues or questions, check:
1. CloudWatch Logs for error messages
2. Step Functions execution history
3. DynamoDB meeting records

## License

MIT
