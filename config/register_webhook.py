#!/usr/bin/env python3
"""
Google Drive Webhook Registration Script
Run this after deploying the SAM application to register the webhook
"""

from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime, timedelta

# =============================================================================
# CONFIGURATION - UPDATE THESE VALUES
# =============================================================================

# Path to your Google service account JSON key file
SERVICE_ACCOUNT_FILE = '/Users/aishitdharwal/Downloads/sigma-cortex-477317-d9-42aa4c26f153.json'

# Your Google Drive folder ID (the folder where meeting recordings are uploaded)
FOLDER_ID = '19AISXdj2EPreDaIDc98arD7Yu1xq11Tx'

# Your webhook URL from SAM deployment output
WEBHOOK_URL = 'https://nzdm4iwlw0.execute-api.ap-south-1.amazonaws.com/prod/meeting-webhook'

# Your webhook secret token from setup-secrets.sh output
WEBHOOK_SECRET = '723a1db5554f605a3ccc1a00a05bf213d2ce77a0f2d2df64143cfcc17cbbd519'

# =============================================================================

def register_webhook():
    """Register Google Drive webhook for push notifications"""

    print("=" * 60)
    print("Google Drive Webhook Registration")
    print("=" * 60)
    print()

    # Validate inputs
    if SERVICE_ACCOUNT_FILE == '/path/to/your-service-account-key.json':
        print("❌ ERROR: Please update SERVICE_ACCOUNT_FILE with your actual file path")
        return

    if FOLDER_ID == 'your-google-drive-folder-id':
        print("❌ ERROR: Please update FOLDER_ID with your actual Google Drive folder ID")
        return

    if 'xxxxxxxxxx' in WEBHOOK_URL:
        print("❌ ERROR: Please update WEBHOOK_URL with your actual API Gateway URL")
        return

    if WEBHOOK_SECRET == 'your-webhook-secret-token-here':
        print("❌ ERROR: Please update WEBHOOK_SECRET with your actual secret token")
        return

    print("Configuration:")
    print(f"  Service Account: {SERVICE_ACCOUNT_FILE}")
    print(f"  Folder ID: {FOLDER_ID}")
    print(f"  Webhook URL: {WEBHOOK_URL}")
    print(f"  Webhook Secret: {WEBHOOK_SECRET[:10]}...")
    print()

    # Authenticate with Google
    print("Authenticating with Google Drive API...")
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        service = build('drive', 'v3', credentials=credentials)
        print("✓ Authentication successful")
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        return

    print()

    # Verify folder access
    print("Verifying folder access...")
    try:
        folder = service.files().get(fileId=FOLDER_ID, fields='name,id').execute()
        print(f"✓ Folder found: '{folder['name']}' (ID: {folder['id']})")
    except Exception as e:
        print(f"❌ Cannot access folder: {e}")
        print()
        print("Make sure:")
        print("  1. The folder ID is correct")
        print("  2. The folder is shared with the service account email")
        return

    print()

    # Register webhook
    print("Registering webhook with Google Drive...")
    try:
        channel = {
            'id': f'meeting-intelligence-{datetime.now().strftime("%Y%m%d-%H%M%S")}',
            'type': 'web_hook',
            'address': WEBHOOK_URL,
            'token': WEBHOOK_SECRET,
            'expiration': int((datetime.now() + timedelta(days=30)).timestamp() * 1000)
        }

        watch_response = service.files().watch(
            fileId=FOLDER_ID,
            body=channel
        ).execute()

        expiration_date = datetime.fromtimestamp(int(watch_response['expiration']) / 1000)

        print("✓ Webhook registered successfully!")
        print()
        print("Webhook Details:")
        print(f"  Channel ID: {watch_response['id']}")
        print(f"  Resource ID: {watch_response['resourceId']}")
        print(f"  Expiration: {expiration_date.strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        print("⚠️  IMPORTANT: Set a calendar reminder to renew the webhook before it expires!")
        print(f"    Renewal date: {expiration_date.strftime('%Y-%m-%d')}")
        print()
        print("To renew, simply run this script again.")
        print()

        # Save renewal info
        with open('webhook_info.txt', 'w') as f:
            f.write(f"Channel ID: {watch_response['id']}\n")
            f.write(f"Resource ID: {watch_response['resourceId']}\n")
            f.write(f"Expiration: {expiration_date.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Registered: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        print("✓ Webhook details saved to: webhook_info.txt")
        print()

    except Exception as e:
        print(f"❌ Webhook registration failed: {e}")
        return

    print("=" * 60)
    print("✓ Setup Complete!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Upload a test video to your Google Drive folder")
    print("  2. Wait 10-15 minutes for processing")
    print("  3. Check Slack for the notification")
    print()


if __name__ == '__main__':
    register_webhook()
