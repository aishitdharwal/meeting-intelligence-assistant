# Deployment Checklist

Use this checklist to deploy the Meeting Intelligence Assistant.

## ✅ Pre-Deployment (You already have these)

- [x] AWS Account with CLI configured (ap-south-1 region)
- [x] AWS SAM CLI installed
- [x] Google Cloud service account with Drive API access
- [x] Google Drive folder ID (shared with service account)
- [x] OpenAI API key
- [x] Slack webhook URL

## 📋 Deployment Steps

### 1. Setup FFmpeg Layer
```bash
cd /Users/aishitdharwal/Documents/meeting-intelligence-assistant
./config/setup-ffmpeg-layer.sh
```
- [ ] FFmpeg binaries downloaded to `layers/ffmpeg/bin/`
- [ ] Verified ffmpeg and ffprobe work

### 2. Store Secrets in AWS Secrets Manager
```bash
./config/setup-secrets.sh
```
- [ ] Google service account key stored
- [ ] Google Drive folder ID stored
- [ ] OpenAI API key stored
- [ ] Slack webhook URL stored
- [ ] Webhook secret generated and saved
- [ ] **IMPORTANT**: Save the webhook secret token shown at the end!

### 3. Build SAM Application
```bash
sam build
```
- [ ] Build completed successfully
- [ ] All 9 Lambda functions built
- [ ] FFmpeg layer packaged

### 4. Deploy to AWS
```bash
sam deploy --guided
```
Answer the prompts:
- Stack name: `meeting-intelligence-assistant`
- AWS Region: `ap-south-1`
- Confirm changes: `Y`
- Allow IAM role creation: `Y`
- Disable rollback: `N`
- Save config: `Y`

- [ ] Deployment completed successfully
- [ ] All resources created
- [ ] **IMPORTANT**: Copy the `WebhookUrl` from the outputs!

### 5. Test Initial Setup
```bash
# Check if resources exist
aws cloudformation describe-stacks --stack-name meeting-intelligence-assistant --region ap-south-1

# Check S3 bucket
aws s3 ls --region ap-south-1 | grep meeting-intelligence

# Check DynamoDB table
aws dynamodb describe-table --table-name MeetingProcessing-prod --region ap-south-1

# Check Lambda functions
aws lambda list-functions --region ap-south-1 | grep MeetingIntel
```
- [ ] CloudFormation stack exists
- [ ] S3 bucket created
- [ ] DynamoDB table created
- [ ] All 9 Lambda functions created
- [ ] Step Functions state machine created

### 6. Configure Google Drive Webhook

Create `register_webhook.py`:
```python
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime, timedelta

SERVICE_ACCOUNT_FILE = 'path/to/your-service-account-key.json'
FOLDER_ID = 'your-folder-id'
WEBHOOK_URL = 'your-webhook-url-from-step-4'
WEBHOOK_SECRET = 'your-webhook-secret-from-step-2'

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

watch_response = service.files().watch(
    fileId=FOLDER_ID,
    body=channel
).execute()

print(f"Webhook registered!")
print(f"Channel ID: {watch_response['id']}")
print(f"Resource ID: {watch_response['resourceId']}")
print(f"Expires: {datetime.fromtimestamp(int(watch_response['expiration'])/1000)}")
```

Run it:
```bash
pip install google-api-python-client google-auth
python register_webhook.py
```

- [ ] Webhook registration script created
- [ ] Script executed successfully
- [ ] Channel ID and Resource ID saved
- [ ] **Set calendar reminder** to renew webhook in 30 days

### 7. Test End-to-End

1. **Upload a test video**:
   - [ ] Upload a short meeting recording (5-10 minutes) to your Google Drive folder

2. **Monitor Step Functions**:
   ```bash
   # Get execution ARN from CloudWatch or Step Functions console
   aws stepfunctions describe-execution \
     --execution-arn "your-execution-arn" \
     --region ap-south-1
   ```
   - [ ] Execution started
   - [ ] Video downloaded
   - [ ] Audio extracted
   - [ ] Audio chunked
   - [ ] Transcription completed
   - [ ] Summarization completed
   - [ ] Results combined
   - [ ] Notification sent

3. **Check Results**:
   - [ ] Slack notification received
   - [ ] DynamoDB entry shows status "completed"
   - [ ] S3 bucket contains all files (video, audio, chunks, transcripts, summaries)

4. **View CloudWatch Logs**:
   ```bash
   # View recent logs for each Lambda
   aws logs tail /aws/lambda/MeetingIntel-WebhookHandler-prod --region ap-south-1 --follow
   aws logs tail /aws/lambda/MeetingIntel-Transcriber-prod --region ap-south-1 --follow
   ```
   - [ ] No errors in logs
   - [ ] All stages completed successfully

### 8. Verify Data in DynamoDB
```python
import boto3

dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
table = dynamodb.Table('MeetingProcessing-prod')

# Get latest meeting
response = table.scan(Limit=1)
meeting = response['Items'][0]

print(f"Meeting ID: {meeting['meeting_id']}")
print(f"Status: {meeting['status']}")
print(f"Action Items: {len(meeting.get('action_items', []))}")
```
- [ ] Meeting record exists
- [ ] Status is "completed"
- [ ] Final summary present
- [ ] Action items extracted

## 📝 Post-Deployment

### Save These Values
Document these for future reference:

| Item | Value |
|------|-------|
| Webhook URL | _________________________ |
| Webhook Secret | _________________________ |
| Google Channel ID | _________________________ |
| Google Resource ID | _________________________ |
| S3 Bucket Name | _________________________ |
| DynamoDB Table | MeetingProcessing-prod |
| AWS Region | ap-south-1 |
| Stack Name | meeting-intelligence-assistant |
| Webhook Renewal Date | _________________________ |

### Set Reminders
- [ ] **Calendar reminder**: Renew Google Drive webhook in 30 days
- [ ] **Monthly**: Review OpenAI API costs
- [ ] **Monthly**: Review AWS costs

### Monitoring Setup
- [ ] Create CloudWatch Dashboard (optional)
- [ ] Set up CloudWatch Alarms for failures (optional)
- [ ] Configure SNS notifications for errors (optional)

## 🎉 Deployment Complete!

Your Meeting Intelligence Assistant is now live and ready to process meetings.

To process a meeting:
1. Upload a video to your Google Drive folder
2. Wait 10-15 minutes for processing
3. Receive Slack notification with summary and action items

## 🔧 Troubleshooting

If something goes wrong:

1. **Check CloudWatch Logs**: Each Lambda has its own log group
2. **Check Step Functions**: View execution history in AWS Console
3. **Check DynamoDB**: Look for error messages in meeting records
4. **Verify Secrets**: Ensure all secrets are correctly stored in Secrets Manager

Common issues:
- **Webhook not triggering**: Check Google Drive webhook registration
- **Video download fails**: Verify service account has folder access
- **Transcription fails**: Check OpenAI API key and quota
- **No notifications**: Verify Slack webhook URL

## 📚 Resources

- [README.md](README.md) - Full documentation
- [ARCHITECTURE.md](ARCHITECTURE.md) - Detailed architecture
- AWS Console → CloudFormation → meeting-intelligence-assistant
- AWS Console → Step Functions → MeetingIntelligence-prod
- AWS Console → CloudWatch → Log groups

---

**Need help?** Check CloudWatch Logs for error messages.
