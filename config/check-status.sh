#!/bin/bash

# Quick status check script for Meeting Intelligence Assistant
# Run this to verify your deployment is working

set -e

REGION="ap-south-1"
STACK_NAME="meeting-intelligence-assistant"

echo "=========================================="
echo "Meeting Intelligence - Status Check"
echo "=========================================="
echo ""

# Check AWS CLI
if ! aws sts get-caller-identity &> /dev/null; then
    echo "❌ AWS CLI not configured or credentials invalid"
    exit 1
fi

echo "✓ AWS CLI configured"
echo "  Account: $(aws sts get-caller-identity --query Account --output text)"
echo "  Region: $REGION"
echo ""

# Check CloudFormation Stack
echo "Checking CloudFormation stack..."
if aws cloudformation describe-stacks --stack-name $STACK_NAME --region $REGION &> /dev/null; then
    STACK_STATUS=$(aws cloudformation describe-stacks \
        --stack-name $STACK_NAME \
        --region $REGION \
        --query 'Stacks[0].StackStatus' \
        --output text)
    echo "✓ Stack status: $STACK_STATUS"

    if [ "$STACK_STATUS" != "CREATE_COMPLETE" ] && [ "$STACK_STATUS" != "UPDATE_COMPLETE" ]; then
        echo "⚠️  Warning: Stack is not in a complete state"
    fi
else
    echo "❌ Stack not found. Run 'sam deploy' first."
    exit 1
fi
echo ""

# Check S3 Bucket
echo "Checking S3 bucket..."
BUCKET_NAME=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`S3BucketName`].OutputValue' \
    --output text)

if [ -n "$BUCKET_NAME" ]; then
    echo "✓ S3 bucket: $BUCKET_NAME"
    OBJECT_COUNT=$(aws s3 ls s3://$BUCKET_NAME/meetings/ --recursive 2>/dev/null | wc -l | tr -d ' ')
    echo "  Objects in meetings/: $OBJECT_COUNT"
else
    echo "⚠️  Could not retrieve bucket name"
fi
echo ""

# Check DynamoDB Table
echo "Checking DynamoDB table..."
TABLE_NAME="MeetingProcessing-prod"
if aws dynamodb describe-table --table-name $TABLE_NAME --region $REGION &> /dev/null; then
    echo "✓ DynamoDB table: $TABLE_NAME"
    ITEM_COUNT=$(aws dynamodb scan \
        --table-name $TABLE_NAME \
        --region $REGION \
        --select COUNT \
        --query 'Count' \
        --output text 2>/dev/null || echo "0")
    echo "  Total meetings: $ITEM_COUNT"
else
    echo "❌ DynamoDB table not found"
fi
echo ""

# Check Lambda Functions
echo "Checking Lambda functions..."
LAMBDA_COUNT=$(aws lambda list-functions \
    --region $REGION \
    --query 'Functions[?contains(FunctionName, `MeetingIntel`)].FunctionName' \
    --output text 2>/dev/null | wc -w | tr -d ' ')
echo "✓ Lambda functions: $LAMBDA_COUNT/9"

if [ "$LAMBDA_COUNT" -lt 9 ]; then
    echo "⚠️  Expected 9 Lambda functions, found $LAMBDA_COUNT"
fi
echo ""

# Check Step Functions
echo "Checking Step Functions..."
STATE_MACHINE_ARN=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`StateMachineArn`].OutputValue' \
    --output text)

if [ -n "$STATE_MACHINE_ARN" ]; then
    echo "✓ State machine exists"

    # Get recent executions
    EXEC_COUNT=$(aws stepfunctions list-executions \
        --state-machine-arn "$STATE_MACHINE_ARN" \
        --region $REGION \
        --max-results 10 \
        --query 'executions | length(@)' \
        --output text 2>/dev/null || echo "0")
    echo "  Recent executions: $EXEC_COUNT"

    if [ "$EXEC_COUNT" -gt 0 ]; then
        echo ""
        echo "  Latest execution:"
        aws stepfunctions list-executions \
            --state-machine-arn "$STATE_MACHINE_ARN" \
            --region $REGION \
            --max-results 1 \
            --query 'executions[0].[name,status,startDate]' \
            --output text
    fi
else
    echo "⚠️  Could not retrieve state machine ARN"
fi
echo ""

# Check Secrets
echo "Checking AWS Secrets..."
SECRETS=(
    "meeting-intelligence/google-service-account"
    "meeting-intelligence/openai-api-key"
    "meeting-intelligence/slack-webhook-url"
    "meeting-intelligence/webhook-secret"
    "meeting-intelligence/google-drive-folder-id"
)

SECRET_COUNT=0
for secret in "${SECRETS[@]}"; do
    if aws secretsmanager describe-secret --secret-id "$secret" --region $REGION &> /dev/null; then
        ((SECRET_COUNT++))
    fi
done

echo "✓ Secrets configured: $SECRET_COUNT/5"

if [ "$SECRET_COUNT" -lt 5 ]; then
    echo "⚠️  Some secrets missing. Run './config/setup-secrets.sh'"
fi
echo ""

# Get Webhook URL
echo "Webhook URL:"
WEBHOOK_URL=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`WebhookUrl`].OutputValue' \
    --output text)
echo "$WEBHOOK_URL"
echo ""

# Check recent meetings
echo "Recent meetings (last 5):"
aws dynamodb scan \
    --table-name $TABLE_NAME \
    --region $REGION \
    --max-items 5 \
    --query 'Items[].[meeting_id.S,status.S,created_at.N]' \
    --output text 2>/dev/null | \
    while read -r meeting_id status created_at; do
        if [ -n "$meeting_id" ]; then
            DATE=$(date -r "$created_at" "+%Y-%m-%d %H:%M" 2>/dev/null || echo "Unknown")
            echo "  $meeting_id | $status | $DATE"
        fi
    done || echo "  No meetings found"
echo ""

echo "=========================================="
echo "Status check complete!"
echo "=========================================="
echo ""
echo "To view logs:"
echo "  aws logs tail /aws/lambda/MeetingIntel-WebhookHandler-prod --region $REGION --follow"
echo ""
echo "To test webhook:"
echo "  Upload a video to your Google Drive folder"
