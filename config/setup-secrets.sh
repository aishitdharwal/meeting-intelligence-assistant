#!/bin/bash

# Setup script for storing secrets in AWS Secrets Manager
# Run this script before deploying the SAM template

set -e

echo "=========================================="
echo "Meeting Intelligence - Secrets Setup"
echo "=========================================="
echo ""

# Check if AWS CLI is configured
if ! aws sts get-caller-identity &> /dev/null; then
    echo "Error: AWS CLI is not configured or credentials are invalid"
    exit 1
fi

echo "✓ AWS CLI configured"
echo ""

# Function to create or update secret
create_or_update_secret() {
    local secret_name=$1
    local secret_value=$2

    if aws secretsmanager describe-secret --secret-id "$secret_name" &> /dev/null; then
        echo "Updating existing secret: $secret_name"
        aws secretsmanager update-secret \
            --secret-id "$secret_name" \
            --secret-string "$secret_value" > /dev/null
    else
        echo "Creating new secret: $secret_name"
        aws secretsmanager create-secret \
            --name "$secret_name" \
            --secret-string "$secret_value" > /dev/null
    fi
}

# 1. Google Service Account Key
echo "1. Setting up Google Service Account Key"
read -p "Enter path to your Google service account JSON key: " GOOGLE_KEY_PATH

if [ ! -f "$GOOGLE_KEY_PATH" ]; then
    echo "Error: File not found at $GOOGLE_KEY_PATH"
    exit 1
fi

GOOGLE_KEY_BASE64=$(cat "$GOOGLE_KEY_PATH" | base64)
create_or_update_secret "meeting-intelligence/google-service-account" "$GOOGLE_KEY_BASE64"
echo "✓ Google service account key stored"
echo ""

# 2. Google Drive Folder ID
echo "2. Setting up Google Drive Folder ID"
read -p "Enter your Google Drive folder ID: " FOLDER_ID
create_or_update_secret "meeting-intelligence/google-drive-folder-id" "$FOLDER_ID"
echo "✓ Google Drive folder ID stored"
echo ""

# 3. OpenAI API Key
echo "3. Setting up OpenAI API Key"
read -s -p "Enter your OpenAI API key: " OPENAI_KEY
echo ""
create_or_update_secret "meeting-intelligence/openai-api-key" "$OPENAI_KEY"
echo "✓ OpenAI API key stored"
echo ""

# 4. Slack Webhook URL
echo "4. Setting up Slack Webhook URL"
read -p "Enter your Slack webhook URL: " SLACK_URL
create_or_update_secret "meeting-intelligence/slack-webhook-url" "$SLACK_URL"
echo "✓ Slack webhook URL stored"
echo ""

# 5. Webhook Secret (generate random)
echo "5. Generating webhook secret token"
WEBHOOK_SECRET=$(openssl rand -hex 32)
create_or_update_secret "meeting-intelligence/webhook-secret" "$WEBHOOK_SECRET"
echo "✓ Webhook secret generated and stored"
echo ""

# 6. Email Recipients (optional - we'll skip SES for now)
echo "6. Email Recipients (skipping for now - will setup SES later)"
create_or_update_secret "meeting-intelligence/email-recipients" '["placeholder@example.com"]'
echo "✓ Placeholder email recipients stored"
echo ""

echo "=========================================="
echo "✓ All secrets stored successfully!"
echo "=========================================="
echo ""
echo "Secrets stored in AWS Secrets Manager:"
echo "  - meeting-intelligence/google-service-account"
echo "  - meeting-intelligence/google-drive-folder-id"
echo "  - meeting-intelligence/openai-api-key"
echo "  - meeting-intelligence/slack-webhook-url"
echo "  - meeting-intelligence/webhook-secret"
echo "  - meeting-intelligence/email-recipients"
echo ""
echo "Your webhook secret token: $WEBHOOK_SECRET"
echo "Save this token - you'll need it when setting up Google Drive webhooks"
echo ""
echo "Next step: Run 'sam build && sam deploy --guided'"
