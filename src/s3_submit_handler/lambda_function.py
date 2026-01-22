import json
import os
import boto3
import re
import uuid
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
stepfunctions = boto3.client('stepfunctions')

DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
STATE_MACHINE_ARN = os.environ['STATE_MACHINE_ARN']

table = dynamodb.Table(DYNAMODB_TABLE)


def validate_s3_uri(s3_uri):
    """Validate S3 URI format."""
    if not s3_uri:
        raise ValueError("s3_uri parameter is required")

    if not isinstance(s3_uri, str):
        raise ValueError("s3_uri must be a string")

    # Validate format: s3://bucket/key
    if not re.match(r'^s3://[^/]+/.+$', s3_uri):
        raise ValueError(
            "Invalid S3 URI format. Expected format: s3://bucket-name/path/to/file"
        )

    return s3_uri.strip()


def create_cors_response(status_code, body):
    """Create API Gateway response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'
        },
        'body': json.dumps(body)
    }


def lambda_handler(event, context):
    """
    API Gateway handler for S3 video submission.

    Expected input (API Gateway event with body):
    {
        "s3_uri": "s3://bucket/path/to/video.mp4"
    }

    Response:
    {
        "meeting_id": "uuid",
        "execution_arn": "arn:aws:states:...",
        "status": "initiated",
        "message": "Processing started successfully"
    }
    """
    print(f"Received event: {json.dumps(event)}")

    # Handle OPTIONS request for CORS preflight
    if event.get('httpMethod') == 'OPTIONS':
        return create_cors_response(200, {'message': 'OK'})

    try:
        # Parse request body
        body = event.get('body', '{}')
        if isinstance(body, str):
            body = json.loads(body)

        print(f"Parsed body: {json.dumps(body)}")

        # Extract and validate s3_uri
        s3_uri = validate_s3_uri(body.get('s3_uri'))
        print(f"Validated S3 URI: {s3_uri}")

        # Generate unique meeting_id
        meeting_id = str(uuid.uuid4())
        current_timestamp = int(datetime.utcnow().timestamp())
        current_date = datetime.utcnow().strftime('%Y-%m-%d')

        print(f"Generated meeting_id: {meeting_id}")

        # Create initial DynamoDB entry
        table.put_item(
            Item={
                'meeting_id': meeting_id,
                'file_id': 's3-upload',
                'file_name': s3_uri.split('/')[-1],
                'status': 'initiated',
                'created_at': current_timestamp,
                'updated_at': current_timestamp,
                'date': current_date,
                'source_s3_uri': s3_uri
            }
        )
        print(f"Created DynamoDB entry for meeting_id: {meeting_id}")

        # Start Step Functions execution
        execution_input = {
            'meeting_id': meeting_id,
            's3_uri': s3_uri,
            'timestamp': current_timestamp
        }

        execution_name = f"meeting-{meeting_id}"
        print(f"Starting Step Functions execution: {execution_name}")

        response = stepfunctions.start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            name=execution_name,
            input=json.dumps(execution_input)
        )

        execution_arn = response['executionArn']
        print(f"Step Functions execution started: {execution_arn}")

        # Update DynamoDB with execution ARN
        table.update_item(
            Key={'meeting_id': meeting_id},
            UpdateExpression='SET execution_arn = :arn, #s = :status, updated_at = :updated',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':arn': execution_arn,
                ':status': 'processing',
                ':updated': int(datetime.utcnow().timestamp())
            }
        )

        # Return success response
        result = {
            'meeting_id': meeting_id,
            'execution_arn': execution_arn,
            'status': 'initiated',
            'message': 'Processing started successfully'
        }

        print(f"Success: {json.dumps(result)}")
        return create_cors_response(200, result)

    except ValueError as e:
        error_msg = str(e)
        print(f"Validation error: {error_msg}")
        return create_cors_response(400, {
            'error': error_msg
        })

    except json.JSONDecodeError as e:
        error_msg = "Invalid JSON in request body"
        print(f"JSON decode error: {e}")
        return create_cors_response(400, {
            'error': error_msg
        })

    except Exception as e:
        error_msg = f"Internal server error: {str(e)}"
        print(f"Error: {error_msg}")
        import traceback
        traceback.print_exc()

        return create_cors_response(500, {
            'error': 'Failed to start processing. Please try again.'
        })
