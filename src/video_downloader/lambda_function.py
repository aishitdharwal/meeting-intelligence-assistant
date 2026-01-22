"""
Video Downloader Lambda
Downloads video from Google Drive and uploads to S3
"""

import json
import os
import boto3
import base64
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account
from io import BytesIO

s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
secretsmanager = boto3.client('secretsmanager')

S3_BUCKET = os.environ['S3_BUCKET']
DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
GOOGLE_SA_SECRET_NAME = os.environ['GOOGLE_SA_SECRET_NAME']

table = dynamodb.Table(DYNAMODB_TABLE)


def get_google_credentials():
    """Retrieve and decode Google service account credentials"""
    try:
        response = secretsmanager.get_secret_value(SecretId=GOOGLE_SA_SECRET_NAME)
        secret_string = response['SecretString']

        # Decode base64
        decoded = base64.b64decode(secret_string)
        credentials_info = json.loads(decoded)

        # Create credentials
        credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )

        return credentials
    except Exception as e:
        print(f"Error retrieving Google credentials: {e}")
        raise


def update_status(meeting_id, status, **kwargs):
    """Update meeting status in DynamoDB"""
    try:
        update_expr = 'SET #s = :status, updated_at = :updated'
        expr_attr_names = {'#s': 'status'}
        expr_attr_values = {
            ':status': status,
            ':updated': int(datetime.utcnow().timestamp())
        }

        # Add any additional attributes
        for key, value in kwargs.items():
            update_expr += f', {key} = :{key}'
            expr_attr_values[f':{key}'] = value

        table.update_item(
            Key={'meeting_id': meeting_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_attr_names,
            ExpressionAttributeValues=expr_attr_values
        )
    except Exception as e:
        print(f"Error updating status: {e}")


def lambda_handler(event, context):
    """Main handler for video download"""
    print(f"Received event: {json.dumps(event)}")

    try:
        meeting_id = event['meeting_id']
        file_id = event['file_id']

        print(f"Processing meeting_id: {meeting_id}, file_id: {file_id}")

        # Update status to downloading
        update_status(meeting_id, 'downloading')

        # Get Google Drive credentials
        print("Retrieving Google credentials...")
        credentials = get_google_credentials()

        # Build Drive API service
        print("Building Drive API service...")
        service = build('drive', 'v3', credentials=credentials)

        # Get file metadata
        print(f"Fetching file metadata for file_id: {file_id}")
        file_metadata = service.files().get(
            fileId=file_id,
            fields='name,size,mimeType,createdTime'
        ).execute()

        file_name = file_metadata.get('name', 'unknown.mp4')
        file_size = int(file_metadata.get('size', 0))
        mime_type = file_metadata.get('mimeType', '')

        print(f"File name: {file_name}")
        print(f"File size: {file_size} bytes ({file_size / 1024 / 1024:.2f} MB)")
        print(f"MIME type: {mime_type}")

        # Check if it's a video file
        if not mime_type.startswith('video/'):
            print(f"WARNING: File MIME type is {mime_type}, not a video")

        # Download file to memory (streaming)
        print("Downloading file from Google Drive...")
        request = service.files().get_media(fileId=file_id)
        file_content = BytesIO()
        downloader = MediaIoBaseDownload(file_content, request, chunksize=10*1024*1024)

        done = False
        downloaded_bytes = 0
        while not done:
            status, done = downloader.next_chunk()
            if status:
                downloaded_bytes = int(status.resumable_progress)
                progress = int(status.progress() * 100)
                print(f"Download progress: {progress}% ({downloaded_bytes / 1024 / 1024:.2f} MB)")

        print(f"Download complete: {downloaded_bytes / 1024 / 1024:.2f} MB")

        # Upload to S3
        s3_key = f'meetings/{meeting_id}/original_video.mp4'
        print(f"Uploading to S3: {S3_BUCKET}/{s3_key}")

        file_content.seek(0)  # Reset file pointer
        s3.upload_fileobj(
            file_content,
            S3_BUCKET,
            s3_key,
            ExtraArgs={
                'ContentType': mime_type,
                'Metadata': {
                    'original_filename': file_name,
                    'meeting_id': meeting_id,
                    'file_id': file_id
                }
            }
        )

        print(f"Upload to S3 complete: s3://{S3_BUCKET}/{s3_key}")

        # Update DynamoDB
        update_status(
            meeting_id,
            'video_downloaded',
            file_name=file_name,
            file_size=file_size,
            video_s3_path=s3_key,
            video_s3_bucket=S3_BUCKET
        )

        # Return result for next step
        result = {
            'meeting_id': meeting_id,
            'file_id': file_id,
            'file_name': file_name,
            'video_s3_path': s3_key,
            'video_s3_bucket': S3_BUCKET,
            'file_size': file_size
        }

        print(f"Video download complete. Result: {json.dumps(result)}")
        return result

    except Exception as e:
        print(f"Error in video downloader: {e}")
        import traceback
        traceback.print_exc()

        # Update status to failed
        if 'meeting_id' in event:
            update_status(
                event['meeting_id'],
                'failed',
                error_stage='video_download',
                error_message=str(e)
            )

        raise
