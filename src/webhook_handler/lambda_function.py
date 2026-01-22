"""
Webhook Handler Lambda
Receives Google Drive webhook notifications and starts Step Functions workflow
"""

import json
import os
import boto3
import uuid
import base64
from datetime import datetime, timedelta
from decimal import Decimal
from googleapiclient.discovery import build
from google.oauth2 import service_account

dynamodb = boto3.resource('dynamodb')
stepfunctions = boto3.client('stepfunctions')
secretsmanager = boto3.client('secretsmanager')

DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
STATE_MACHINE_ARN = os.environ['STATE_MACHINE_ARN']
WEBHOOK_SECRET_NAME = os.environ['WEBHOOK_SECRET_NAME']
GOOGLE_SA_SECRET_NAME = os.environ.get('GOOGLE_SA_SECRET_NAME', 'meeting-intelligence/google-service-account')
FOLDER_ID_SECRET_NAME = os.environ.get('FOLDER_ID_SECRET_NAME', 'meeting-intelligence/google-drive-folder-id')

table = dynamodb.Table(DYNAMODB_TABLE)


def get_webhook_secret():
    """Retrieve webhook secret from Secrets Manager"""
    try:
        response = secretsmanager.get_secret_value(SecretId=WEBHOOK_SECRET_NAME)
        return response['SecretString']
    except Exception as e:
        print(f"Error retrieving webhook secret: {e}")
        return None


def get_google_credentials():
    """Retrieve and decode Google service account credentials"""
    try:
        response = secretsmanager.get_secret_value(SecretId=GOOGLE_SA_SECRET_NAME)
        secret_string = response['SecretString']
        decoded = base64.b64decode(secret_string)
        credentials_info = json.loads(decoded)
        credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        return credentials
    except Exception as e:
        print(f"Error retrieving Google credentials: {e}")
        return None


def get_folder_id():
    """Retrieve folder ID from Secrets Manager"""
    try:
        response = secretsmanager.get_secret_value(SecretId=FOLDER_ID_SECRET_NAME)
        return response['SecretString']
    except Exception as e:
        print(f"Error retrieving folder ID: {e}")
        return None


def get_recent_files_from_folder(folder_id, minutes_ago=5):
    """Query Google Drive for recently added video files in the folder"""
    try:
        credentials = get_google_credentials()
        if not credentials:
            print("Failed to get Google credentials")
            return []

        service = build('drive', 'v3', credentials=credentials)

        # Calculate time threshold (files added in last N minutes)
        time_threshold = (datetime.utcnow() - timedelta(minutes=minutes_ago)).isoformat() + 'Z'

        # Query for video files added recently
        query = f"'{folder_id}' in parents and mimeType contains 'video/' and createdTime > '{time_threshold}' and trashed = false"

        print(f"Querying Drive with: {query}")

        results = service.files().list(
            q=query,
            fields='files(id, name, mimeType, createdTime, size)',
            orderBy='createdTime desc',
            pageSize=10
        ).execute()

        files = results.get('files', [])
        print(f"Found {len(files)} recent video files")

        return files

    except Exception as e:
        print(f"Error querying Google Drive: {e}")
        import traceback
        traceback.print_exc()
        return []


def validate_webhook(headers, body):
    """Validate webhook request from Google Drive"""
    # Get token from headers
    token = headers.get('x-goog-channel-token') or headers.get('X-Goog-Channel-Token')

    # Get expected secret
    expected_secret = get_webhook_secret()

    if not expected_secret:
        print("WARNING: Unable to retrieve webhook secret")
        return True  # Allow for initial setup

    if token != expected_secret:
        print(f"Invalid webhook token. Expected: {expected_secret[:10]}..., Got: {token[:10] if token else 'None'}...")
        return False

    # Check resource state
    state = headers.get('x-goog-resource-state') or headers.get('X-Goog-Resource-State')
    valid_states = ['sync', 'add', 'remove', 'update', 'trash', 'untrash', 'change']

    if state not in valid_states:
        print(f"Invalid resource state: {state}")
        return False

    return True


def lambda_handler(event, context):
    """Main handler for webhook notifications"""
    print(f"Received event: {json.dumps(event)}")

    try:
        # Extract headers
        headers = event.get('headers', {})

        # Handle initial sync notification
        resource_state = headers.get('x-goog-resource-state') or headers.get('X-Goog-Resource-State')
        if resource_state == 'sync':
            print("Received sync notification - webhook setup successful")
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'Sync notification received'})
            }

        # Validate webhook
        if not validate_webhook(headers, event.get('body', '')):
            return {
                'statusCode': 403,
                'body': json.dumps({'error': 'Invalid webhook signature'})
            }

        # Parse body
        body = event.get('body', '{}')
        if isinstance(body, str):
            body = json.loads(body) if body else {}

        # Extract file information from headers
        resource_id = headers.get('x-goog-resource-id') or headers.get('X-Goog-Resource-Id')
        resource_uri = headers.get('x-goog-resource-uri') or headers.get('X-Goog-Resource-Uri')
        changed = headers.get('x-goog-changed') or headers.get('X-Goog-Changed', '')

        print(f"Resource ID: {resource_id}")
        print(f"Resource URI: {resource_uri}")
        print(f"Changed: {changed}")

        # Check if this is a folder-level notification (changed="children")
        # This happens when files are added to the folder
        if changed == 'children' or (resource_state in ['update', 'change'] and not resource_uri):
            print("Detected folder-level notification - querying for new files")

            folder_id = get_folder_id()
            if not folder_id:
                print("ERROR: Could not retrieve folder ID")
                return {
                    'statusCode': 500,
                    'body': json.dumps({'error': 'Could not retrieve folder ID'})
                }

            # Query for recent video files
            recent_files = get_recent_files_from_folder(folder_id, minutes_ago=5)

            if not recent_files:
                print("No recent video files found")
                return {
                    'statusCode': 200,
                    'body': json.dumps({'message': 'No new video files found'})
                }

            # Process each new file
            processed_count = 0
            for file in recent_files:
                file_id = file['id']
                file_name = file['name']

                # Check if we've already processed this file
                try:
                    existing = table.query(
                        IndexName='StatusIndex',
                        KeyConditionExpression='#s = :status',
                        FilterExpression='file_id = :fid',
                        ExpressionAttributeNames={'#s': 'status'},
                        ExpressionAttributeValues={
                            ':status': 'initiated',
                            ':fid': file_id
                        },
                        Limit=1
                    )
                    if existing.get('Items'):
                        print(f"File {file_id} already processed - skipping")
                        continue
                except Exception as e:
                    print(f"Error checking existing file: {e}")

                # Process this file
                meeting_id = str(uuid.uuid4())
                current_timestamp = int(datetime.utcnow().timestamp())
                current_date = datetime.utcnow().strftime('%Y-%m-%d')

                print(f"Processing file: {file_name} (ID: {file_id})")

                # Create DynamoDB entry
                try:
                    table.put_item(
                        Item={
                            'meeting_id': meeting_id,
                            'file_id': file_id,
                            'file_name': file_name,
                            'status': 'initiated',
                            'created_at': current_timestamp,
                            'updated_at': current_timestamp,
                            'date': current_date
                        }
                    )
                except Exception as e:
                    print(f"Error creating DynamoDB entry: {e}")
                    continue

                # Start Step Functions execution
                try:
                    execution_name = f"meeting-{meeting_id}"
                    execution_input = {
                        'meeting_id': meeting_id,
                        'file_id': file_id,
                        'timestamp': current_timestamp
                    }

                    response = stepfunctions.start_execution(
                        stateMachineArn=STATE_MACHINE_ARN,
                        name=execution_name,
                        input=json.dumps(execution_input)
                    )

                    execution_arn = response['executionArn']
                    print(f"Started Step Functions execution: {execution_arn}")

                    # Update DynamoDB with execution ARN
                    table.update_item(
                        Key={'meeting_id': meeting_id},
                        UpdateExpression='SET execution_arn = :arn, #s = :status',
                        ExpressionAttributeNames={'#s': 'status'},
                        ExpressionAttributeValues={
                            ':arn': execution_arn,
                            ':status': 'processing'
                        }
                    )

                    processed_count += 1

                except Exception as e:
                    print(f"Error starting Step Functions: {e}")
                    table.update_item(
                        Key={'meeting_id': meeting_id},
                        UpdateExpression='SET #s = :status, error_message = :error',
                        ExpressionAttributeNames={'#s': 'status'},
                        ExpressionAttributeValues={
                            ':status': 'failed',
                            ':error': str(e)
                        }
                    )

            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': f'Processed {processed_count} new files',
                    'files_found': len(recent_files)
                })
            }

        # Extract file ID from resource URI or body (for direct file notifications)
        file_id = None
        if resource_uri:
            # Extract file ID from URI like: https://www.googleapis.com/drive/v3/files/FILE_ID
            parts = resource_uri.rstrip('/').split('/')
            if len(parts) > 0:
                potential_id = parts[-1].split('?')[0]  # Remove query params if any
                # Check if it looks like a file ID (not a folder ID from resource_uri)
                if len(potential_id) > 10 and potential_id != get_folder_id():
                    file_id = potential_id

        if not file_id and body:
            file_id = body.get('id') or body.get('fileId')

        if not file_id:
            print("WARNING: Could not extract file_id - already handled via folder query")
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'Handled via folder query'})
            }

        # Only process if it's a file addition or change
        if resource_state not in ['add', 'update', 'change']:
            print(f"Ignoring resource state: {resource_state}")
            return {
                'statusCode': 200,
                'body': json.dumps({'message': f'Ignoring state: {resource_state}'})
            }

        # Generate meeting ID
        meeting_id = str(uuid.uuid4())
        current_timestamp = int(datetime.utcnow().timestamp())
        current_date = datetime.utcnow().strftime('%Y-%m-%d')

        print(f"Generated meeting_id: {meeting_id}")
        print(f"File ID: {file_id}")

        # Create initial DynamoDB entry
        try:
            table.put_item(
                Item={
                    'meeting_id': meeting_id,
                    'file_id': file_id,
                    'status': 'initiated',
                    'created_at': current_timestamp,
                    'updated_at': current_timestamp,
                    'date': current_date,
                    'resource_id': resource_id or '',
                    'resource_uri': resource_uri or ''
                }
            )
            print(f"Created DynamoDB entry for meeting_id: {meeting_id}")
        except Exception as e:
            print(f"Error creating DynamoDB entry: {e}")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Failed to create database entry'})
            }

        # Start Step Functions execution
        try:
            execution_name = f"meeting-{meeting_id}"
            execution_input = {
                'meeting_id': meeting_id,
                'file_id': file_id,
                'timestamp': current_timestamp
            }

            response = stepfunctions.start_execution(
                stateMachineArn=STATE_MACHINE_ARN,
                name=execution_name,
                input=json.dumps(execution_input)
            )

            execution_arn = response['executionArn']
            print(f"Started Step Functions execution: {execution_arn}")

            # Update DynamoDB with execution ARN
            table.update_item(
                Key={'meeting_id': meeting_id},
                UpdateExpression='SET execution_arn = :arn, #s = :status',
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={
                    ':arn': execution_arn,
                    ':status': 'processing'
                }
            )

        except Exception as e:
            print(f"Error starting Step Functions: {e}")
            # Update status to failed
            table.update_item(
                Key={'meeting_id': meeting_id},
                UpdateExpression='SET #s = :status, error_message = :error',
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={
                    ':status': 'failed',
                    ':error': str(e)
                }
            )
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Failed to start processing'})
            }

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Meeting processing started',
                'meeting_id': meeting_id,
                'execution_arn': execution_arn
            })
        }

    except Exception as e:
        print(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error'})
        }
