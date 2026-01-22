#!/bin/bash

# Test script to trigger the webhook endpoint
# This simulates what Google Drive sends

WEBHOOK_URL="https://nzdm4iwlw0.execute-api.ap-south-1.amazonaws.com/prod/meeting-webhook"
WEBHOOK_SECRET="0b58e48a7ab3783a420e0344574b06badd208bf12d44803cec804f85f8069758"

echo "Testing webhook endpoint..."
echo "URL: $WEBHOOK_URL"
echo ""

# Send a test webhook notification (simulating a folder update)
curl -X POST "$WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -H "X-Goog-Channel-Token: $WEBHOOK_SECRET" \
  -H "X-Goog-Resource-State: update" \
  -H "X-Goog-Changed: children" \
  -H "X-Goog-Resource-ID: test-resource-id" \
  -H "X-Goog-Resource-URI: https://www.googleapis.com/drive/v3/files/19AISXdj2EPreDaIDc98arD7Yu1xq11Tx" \
  -d '{}' \
  -v

echo ""
echo ""
echo "Check CloudWatch Logs:"
echo "aws logs tail /aws/lambda/MeetingIntel-WebhookHandler-prod --region ap-south-1 --since 2m --follow"
