import json
import os
import boto3
import re
import uuid
from datetime import datetime
from urllib.parse import urlparse

s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

S3_BUCKET = os.environ['S3_BUCKET']
DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
MAX_FILE_SIZE_MB = int(os.environ.get('MAX_FILE_SIZE_MB', 500))

table = dynamodb.Table(DYNAMODB_TABLE)

# Allowed video file extensions
ALLOWED_EXTENSIONS = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v']


def parse_s3_uri(s3_uri):
    """
    Parse S3 URI and extract bucket and key.
    Expected format: s3://bucket-name/path/to/file
    """
    match = re.match(r'^s3://([^/]+)/(.+)$', s3_uri)
    if not match:
        raise ValueError(f"Invalid S3 URI format: {s3_uri}. Expected: s3://bucket-name/path/to/file")

    bucket = match.group(1)
    key = match.group(2)
    return bucket, key


def validate_file_extension(filename):
    """Validate that file has allowed video extension."""
    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Invalid file type: {ext}. Allowed video formats: {', '.join(ALLOWED_EXTENSIONS)}"
        )


def get_file_metadata(bucket, key):
    """Get file metadata from S3."""
    try:
        response = s3.head_object(Bucket=bucket, Key=key)
        return {
            'size': response['ContentLength'],
            'content_type': response.get('ContentType', ''),
            'last_modified': response['LastModified']
        }
    except s3.exceptions.ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404':
            raise FileNotFoundError(f"S3 object not found: s3://{bucket}/{key}")
        elif error_code == '403':
            raise PermissionError(f"Access denied to S3 object: s3://{bucket}/{key}")
        else:
            raise


def validate_file_size(file_size):
    """Validate file size against maximum allowed."""
    max_size_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
    if file_size > max_size_bytes:
        size_mb = file_size / (1024 * 1024)
        raise ValueError(
            f"File size {size_mb:.1f}MB exceeds maximum allowed size of {MAX_FILE_SIZE_MB}MB"
        )


def update_status(meeting_id, status, **kwargs):
    """Update meeting status in DynamoDB."""
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


def lambda_handler(event, context):
    """
    Lambda handler to process S3 URI and copy video to processing bucket.

    Expected input:
    {
        "meeting_id": "uuid",
        "s3_uri": "s3://bucket/path/to/video.mp4",
        "timestamp": 1234567890
    }

    Output (matches VideoDownloader format):
    {
        "meeting_id": "uuid",
        "file_id": "s3-upload",
        "file_name": "video.mp4",
        "video_s3_path": "meetings/{meeting_id}/original_video.mp4",
        "video_s3_bucket": "processing-bucket",
        "file_size": 12345678
    }
    """
    print(f"Received event: {json.dumps(event)}")

    try:
        # Extract parameters
        meeting_id = event.get('meeting_id')
        s3_uri = event.get('s3_uri')

        if not meeting_id:
            raise ValueError("Missing required parameter: meeting_id")
        if not s3_uri:
            raise ValueError("Missing required parameter: s3_uri")

        print(f"Processing S3 URI: {s3_uri} for meeting_id: {meeting_id}")

        # Parse S3 URI
        source_bucket, source_key = parse_s3_uri(s3_uri)
        print(f"Parsed - Bucket: {source_bucket}, Key: {source_key}")

        # Extract filename
        file_name = os.path.basename(source_key)
        print(f"File name: {file_name}")

        # Validate file extension
        validate_file_extension(file_name)
        print(f"File extension validated: {file_name}")

        # Get file metadata and validate
        metadata = get_file_metadata(source_bucket, source_key)
        file_size = metadata['size']
        print(f"File size: {file_size} bytes ({file_size / (1024*1024):.2f} MB)")

        # Validate file size
        validate_file_size(file_size)
        print("File size validated")

        # Update status to downloading
        update_status(meeting_id, 'downloading', source_s3_uri=s3_uri)

        # Copy file to processing bucket
        destination_key = f'meetings/{meeting_id}/original_video{os.path.splitext(file_name)[1]}'
        print(f"Copying to: s3://{S3_BUCKET}/{destination_key}")

        copy_source = {
            'Bucket': source_bucket,
            'Key': source_key
        }

        s3.copy_object(
            CopySource=copy_source,
            Bucket=S3_BUCKET,
            Key=destination_key
        )

        print(f"Successfully copied file to processing bucket")

        # Update status to processing
        update_status(
            meeting_id,
            'processing',
            video_s3_path=destination_key,
            file_size=file_size
        )

        # Return output matching VideoDownloader format
        result = {
            'meeting_id': meeting_id,
            'file_id': 's3-upload',
            'file_name': file_name,
            'video_s3_path': destination_key,
            'video_s3_bucket': S3_BUCKET,
            'file_size': file_size
        }

        print(f"Successfully processed. Result: {json.dumps(result)}")
        return result

    except ValueError as e:
        error_msg = str(e)
        print(f"Validation error: {error_msg}")
        update_status(meeting_id, 'failed', error_message=error_msg)
        raise

    except FileNotFoundError as e:
        error_msg = str(e)
        print(f"File not found error: {error_msg}")
        update_status(meeting_id, 'failed', error_message=error_msg)
        raise

    except PermissionError as e:
        error_msg = str(e)
        print(f"Permission error: {error_msg}")
        update_status(meeting_id, 'failed', error_message=error_msg)
        raise

    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        print(f"Error: {error_msg}")
        import traceback
        traceback.print_exc()

        if meeting_id:
            update_status(meeting_id, 'failed', error_message=error_msg)

        raise
