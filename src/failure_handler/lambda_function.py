"""
Failure Handler Lambda
Handles workflow failures and updates DynamoDB
"""

import json
import os
import boto3
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
cloudwatch = boto3.client('cloudwatch')

DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
table = dynamodb.Table(DYNAMODB_TABLE)


def publish_failure_metric(meeting_id, error_stage):
    """Publish failure metric to CloudWatch"""
    try:
        cloudwatch.put_metric_data(
            Namespace='MeetingIntelligence',
            MetricData=[
                {
                    'MetricName': 'ProcessingFailures',
                    'Value': 1,
                    'Unit': 'Count',
                    'Timestamp': datetime.utcnow(),
                    'Dimensions': [
                        {
                            'Name': 'Stage',
                            'Value': error_stage
                        }
                    ]
                }
            ]
        )
        print(f"Published failure metric for stage: {error_stage}")
    except Exception as e:
        print(f"Error publishing CloudWatch metric: {e}")


def lambda_handler(event, context):
    """Main handler for failure handling"""
    print(f"Received event: {json.dumps(event)}")

    try:
        # Extract meeting_id from various possible locations
        meeting_id = None

        # Try direct access
        meeting_id = event.get('meeting_id')

        # Try nested structures
        if not meeting_id and 'downloadResult' in event:
            meeting_id = event['downloadResult'].get('meeting_id')

        if not meeting_id and 'audioResult' in event:
            meeting_id = event['audioResult'].get('meeting_id')

        if not meeting_id and 'chunkResult' in event:
            meeting_id = event['chunkResult'].get('meeting_id')

        if not meeting_id:
            print("WARNING: Could not extract meeting_id from event")
            return {
                'status': 'error',
                'message': 'Could not determine meeting_id'
            }

        # Extract error information
        error_info = event.get('error', {})
        error_message = error_info.get('Error', 'Unknown error')
        error_cause = error_info.get('Cause', 'No cause provided')

        # Try to parse cause if it's JSON
        try:
            if error_cause.startswith('{'):
                cause_json = json.loads(error_cause)
                error_message = cause_json.get('errorMessage', error_message)
        except:
            pass

        # Determine error stage from the event
        error_stage = 'unknown'
        if 'downloadResult' not in event:
            error_stage = 'video_download'
        elif 'audioResult' not in event:
            error_stage = 'audio_extraction'
        elif 'chunkResult' not in event:
            error_stage = 'audio_chunking'
        elif 'transcripts' not in event:
            error_stage = 'transcription'
        elif 'summaries' not in event:
            error_stage = 'summarization'
        elif 'finalResult' not in event:
            error_stage = 'result_combination'
        else:
            error_stage = 'notification'

        print(f"Handling failure for meeting: {meeting_id}")
        print(f"Error stage: {error_stage}")
        print(f"Error message: {error_message}")

        # Update DynamoDB
        update_timestamp = int(datetime.utcnow().timestamp())

        try:
            table.update_item(
                Key={'meeting_id': meeting_id},
                UpdateExpression='''
                    SET #s = :status,
                        error_stage = :error_stage,
                        error_message = :error_message,
                        error_timestamp = :timestamp,
                        updated_at = :updated
                ''',
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={
                    ':status': 'failed',
                    ':error_stage': error_stage,
                    ':error_message': str(error_message)[:1000],  # Limit length
                    ':timestamp': update_timestamp,
                    ':updated': update_timestamp
                }
            )
            print("Updated DynamoDB with failure information")
        except Exception as e:
            print(f"Error updating DynamoDB: {e}")

        # Publish CloudWatch metric
        publish_failure_metric(meeting_id, error_stage)

        # Log structured error for CloudWatch Insights
        print(json.dumps({
            'event_type': 'processing_failure',
            'meeting_id': meeting_id,
            'error_stage': error_stage,
            'error_message': error_message,
            'timestamp': datetime.utcnow().isoformat()
        }))

        return {
            'meeting_id': meeting_id,
            'status': 'failed',
            'error_stage': error_stage,
            'error_message': error_message,
            'timestamp': datetime.utcnow().isoformat()
        }

    except Exception as e:
        print(f"Error in failure handler: {e}")
        import traceback
        traceback.print_exc()

        # Return error but don't raise - we're already in error handling
        return {
            'status': 'error',
            'message': 'Failure handler encountered an error',
            'error': str(e)
        }
