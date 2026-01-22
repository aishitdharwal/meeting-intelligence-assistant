# Quick Start Guide

Get your Meeting Intelligence Assistant running in 15 minutes.

## Step 1: Setup FFmpeg (2 min)

```bash
cd /Users/aishitdharwal/Documents/meeting-intelligence-assistant
./config/setup-ffmpeg-layer.sh
```

**What it does**: Downloads FFmpeg binaries needed for audio extraction from videos.

---

## Step 2: Store Your Secrets (3 min)

```bash
./config/setup-secrets.sh
```

**You'll need**:
- Path to your Google service account JSON key file
- Your Google Drive folder ID
- Your OpenAI API key
- Your Slack webhook URL

**Important**: Save the webhook secret token that's displayed at the end!

---

## Step 3: Deploy to AWS (5 min)

```bash
sam build
sam deploy --guided
```

**During deployment**:
- Accept most defaults
- Region: **ap-south-1**
- Allow IAM role creation: **Y**
- Save configuration: **Y**

**Important**: Copy the **WebhookUrl** from the outputs!

---

## Step 4: Register Google Drive Webhook (3 min)

Create `register_webhook.py`:

```python
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime, timedelta

# UPDATE THESE VALUES
SERVICE_ACCOUNT_FILE = '/path/to/your-service-account.json'
FOLDER_ID = 'your-folder-id-here'
WEBHOOK_URL = 'your-webhook-url-from-step-3'
WEBHOOK_SECRET = 'your-secret-from-step-2'

# Register the webhook
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=['https://www.googleapis.com/auth/drive.readonly']
)

service = build('drive', 'v3', credentials=credentials)

channel = {
    'id': 'meeting-intelligence-prod',
    'type': 'web_hook',
    'address': WEBHOOK_URL,
    'token': WEBHOOK_SECRET,
    'expiration': int((datetime.now() + timedelta(days=30)).timestamp() * 1000)
}

result = service.files().watch(fileId=FOLDER_ID, body=channel).execute()
print(f"✓ Webhook registered! Expires: {datetime.fromtimestamp(int(result['expiration'])/1000)}")
```

Run it:
```bash
pip install google-api-python-client google-auth
python register_webhook.py
```

---

## Step 5: Test It! (2 min)

1. **Upload a test video** (5-10 min recording) to your Google Drive folder
2. **Wait 10-15 minutes** for processing
3. **Check Slack** for the notification with summary and action items!

---

## Verify Everything Works

```bash
./config/check-status.sh
```

This shows:
- ✓ All AWS resources deployed
- ✓ Number of processed meetings
- ✓ Recent executions
- ✓ Webhook URL

---

## What Happens When You Upload a Video?

```
1. Google Drive → Webhook triggers
2. Video downloaded to S3
3. Audio extracted with FFmpeg
4. Audio split into 10-min chunks
5. Each chunk transcribed (in parallel) ← OpenAI Whisper
6. Each transcript summarized (in parallel) ← GPT-4o Mini
7. Results combined & deduplicated
8. Slack notification sent 🎉
```

**Total time**: ~10-15 minutes for a 1-hour meeting

---

## View Logs

```bash
# Webhook handler
aws logs tail /aws/lambda/MeetingIntel-WebhookHandler-prod --region ap-south-1 --follow

# Transcriber
aws logs tail /aws/lambda/MeetingIntel-Transcriber-prod --region ap-south-1 --follow

# All Step Functions executions
aws stepfunctions list-executions \
  --state-machine-arn $(aws cloudformation describe-stacks \
    --stack-name meeting-intelligence-assistant \
    --region ap-south-1 \
    --query 'Stacks[0].Outputs[?OutputKey==`StateMachineArn`].OutputValue' \
    --output text) \
  --region ap-south-1
```

---

## Check Meeting Results

```python
import boto3
import json

dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
table = dynamodb.Table('MeetingProcessing-prod')

# Get all completed meetings
response = table.query(
    IndexName='StatusIndex',
    KeyConditionExpression='#s = :status',
    ExpressionAttributeNames={'#s': 'status'},
    ExpressionAttributeValues={':status': 'completed'}
)

for meeting in response['Items']:
    print(f"\nMeeting: {meeting.get('file_name', 'Unknown')}")
    print(f"Status: {meeting['status']}")
    print(f"Action Items: {len(meeting.get('action_items', []))}")
    print(f"Summary: {meeting.get('final_summary', 'N/A')[:100]}...")
```

---

## Troubleshooting

### Webhook not triggering?
- Check webhook is registered: `aws apigateway get-rest-apis --region ap-south-1`
- Verify folder permissions: Service account has access to Drive folder

### Video download fails?
```bash
aws logs tail /aws/lambda/MeetingIntel-VideoDownloader-prod --region ap-south-1
```
- Verify service account credentials in Secrets Manager
- Check file ID is valid

### No transcription?
```bash
aws logs tail /aws/lambda/MeetingIntel-Transcriber-prod --region ap-south-1
```
- Check OpenAI API key is valid
- Verify you have API credits
- Look for rate limit errors (429)

### No Slack notification?
```bash
aws logs tail /aws/lambda/MeetingIntel-NotificationSender-prod --region ap-south-1
```
- Test Slack webhook URL manually
- Check webhook URL in Secrets Manager

---

## Costs

**Typical 45-min meeting**:
- AWS: ~$0.08
- OpenAI Whisper: ~$0.27
- OpenAI GPT-4o Mini: ~$0.01
- **Total: ~$0.36 per meeting**

**Monthly (220 meetings)**:
- AWS: ~$16
- OpenAI: ~$61
- **Total: ~$77/month**

---

## Important Reminders

### ⚠️ Webhook Expires in 30 Days
Set a calendar reminder to renew your Google Drive webhook:

```bash
# Renew webhook script (save this)
python register_webhook.py
```

### 💰 Monitor OpenAI Costs
Check your OpenAI usage: https://platform.openai.com/usage

---

## Next Steps

- ✅ Process your first meeting
- ✅ Check the summary quality
- ✅ Adjust prompts if needed (in `src/summarizer/lambda_function.py`)
- ✅ Set up CloudWatch alarms for failures (optional)
- ✅ Configure SES for email notifications (optional)

---

## Full Documentation

- [README.md](README.md) - Complete documentation
- [ARCHITECTURE.md](ARCHITECTURE.md) - Detailed architecture
- [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md) - Comprehensive deployment checklist

---

**🎉 That's it! Your Meeting Intelligence Assistant is live!**

Upload a video to your Google Drive folder and wait for the Slack notification with your meeting summary and action items.
