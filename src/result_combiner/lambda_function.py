"""
Result Combiner Lambda
Combines all summaries and action items into final report
"""

import json
import os
import boto3
from datetime import datetime
from difflib import SequenceMatcher
from decimal import Decimal

s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

S3_BUCKET = os.environ['S3_BUCKET']
DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']

table = dynamodb.Table(DYNAMODB_TABLE)


def decimal_to_int(obj):
    """Convert Decimal objects to int/float for JSON serialization"""
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    raise TypeError


def similarity(a, b):
    """Calculate similarity ratio between two strings"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def deduplicate_action_items(all_action_items):
    """Deduplicate action items using fuzzy matching"""
    if not all_action_items:
        return []

    deduplicated = []
    similarity_threshold = 0.8

    for item in all_action_items:
        action_text = item['action']

        # Check if similar action already exists
        is_duplicate = False
        for existing in deduplicated:
            if similarity(action_text, existing['action']) > similarity_threshold:
                # It's a duplicate - merge information
                is_duplicate = True
                # Keep more specific owner if available
                if item['owner'] != 'Unassigned' and existing['owner'] == 'Unassigned':
                    existing['owner'] = item['owner']
                # Keep more specific due date if available
                if item['due_date'] != 'Not specified' and existing['due_date'] == 'Not specified':
                    existing['due_date'] = item['due_date']
                # Add mentioned_at if not present
                if 'mentioned_at' in item and 'mentioned_at' not in existing:
                    existing['mentioned_at'] = item['mentioned_at']
                break

        if not is_duplicate:
            deduplicated.append(item)

    print(f"Deduplicated {len(all_action_items)} action items to {len(deduplicated)}")
    return deduplicated


def format_time(seconds):
    """Format seconds as HH:MM:SS"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"


def lambda_handler(event, context):
    """Main handler for result combination"""
    print(f"Received event: {json.dumps(event)}")

    try:
        # Extract data from event
        meeting_id = event.get('meeting_id')
        if not meeting_id:
            # Try to get from nested structure
            chunk_result = event.get('chunkResult', {})
            meeting_id = chunk_result.get('meeting_id')

        summaries = event.get('summaries', [])

        print(f"Processing meeting_id: {meeting_id}")
        print(f"Number of summaries: {len(summaries)}")

        # Filter out failed summaries
        successful_summaries = [s for s in summaries if s.get('status') == 'success']
        print(f"Successful summaries: {len(successful_summaries)}")

        if not successful_summaries:
            raise ValueError("No successful summaries to combine")

        # Sort summaries by chunk_id
        successful_summaries.sort(key=lambda x: x.get('chunk_id', 0))

        # Initialize cost and performance tracking
        total_transcription_cost = 0
        total_summarization_cost = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_transcription_time = 0
        total_summarization_time = 0

        # Aggregate transcription costs from event
        transcripts = event.get('transcripts', [])
        for transcript_result in transcripts:
            if transcript_result.get('status') == 'success':
                total_transcription_cost += transcript_result.get('cost', 0)
                total_transcription_time += transcript_result.get('processing_time_seconds', 0)

        # Download all summary files from S3
        all_summaries = []
        all_action_items = []

        for summary_meta in successful_summaries:
            try:
                s3_path = summary_meta['summary_s3_path']
                chunk_id = summary_meta['chunk_id']

                print(f"Downloading summary for chunk {chunk_id}: {s3_path}")
                summary_obj = s3.get_object(Bucket=S3_BUCKET, Key=s3_path)
                summary_data = json.loads(summary_obj['Body'].read().decode('utf-8'))

                all_summaries.append(summary_data)

                # Aggregate summarization costs and metrics
                total_summarization_cost += summary_meta.get('cost', 0)
                total_prompt_tokens += summary_meta.get('prompt_tokens', 0)
                total_completion_tokens += summary_meta.get('completion_tokens', 0)
                total_summarization_time += summary_meta.get('processing_time_seconds', 0)

                # Collect action items with metadata
                for action_item in summary_data.get('action_items', []):
                    action_item['mentioned_at'] = summary_data.get('time_range', f'Chunk {chunk_id}')
                    action_item['chunk_id'] = chunk_id
                    all_action_items.append(action_item)

            except Exception as e:
                print(f"Error downloading summary {chunk_id}: {e}")
                continue

        print(f"Downloaded {len(all_summaries)} summaries")
        print(f"Total action items before deduplication: {len(all_action_items)}")

        # Calculate total cost and metrics
        total_cost = total_transcription_cost + total_summarization_cost
        total_processing_time = total_transcription_time + total_summarization_time
        total_tokens = total_prompt_tokens + total_completion_tokens

        print(f"\nCost Summary:")
        print(f"  Transcription: ${total_transcription_cost:.4f}")
        print(f"  Summarization: ${total_summarization_cost:.4f}")
        print(f"  Total: ${total_cost:.4f}")
        print(f"\nToken Usage:")
        print(f"  Prompt tokens: {total_prompt_tokens}")
        print(f"  Completion tokens: {total_completion_tokens}")
        print(f"  Total tokens: {total_tokens}")
        print(f"\nProcessing Time:")
        print(f"  Transcription: {total_transcription_time:.1f}s")
        print(f"  Summarization: {total_summarization_time:.1f}s")
        print(f"  Total: {total_processing_time:.1f}s")

        # Combine summaries
        combined_summary_parts = []
        for summary in all_summaries:
            time_range = summary.get('time_range', 'Unknown')
            summary_text = summary.get('summary', '')
            combined_summary_parts.append(f"[{time_range}] {summary_text}")

        final_summary = '\n\n'.join(combined_summary_parts)

        # Deduplicate action items
        deduplicated_action_items = deduplicate_action_items(all_action_items)

        print(f"Final action items: {len(deduplicated_action_items)}")

        # Get meeting metadata from DynamoDB
        try:
            db_response = table.get_item(Key={'meeting_id': meeting_id})
            meeting_data = db_response.get('Item', {})
            file_name = meeting_data.get('file_name', 'Unknown Meeting')
            duration_seconds = meeting_data.get('duration_seconds', 0)

            # Convert Decimal to int if needed
            if isinstance(duration_seconds, Decimal):
                duration_seconds = int(duration_seconds)
        except Exception as e:
            print(f"Error retrieving meeting metadata: {e}")
            file_name = 'Unknown Meeting'
            duration_seconds = 0

        # Prepare final result
        final_result = {
            'meeting_id': meeting_id,
            'meeting_name': file_name,
            'duration_seconds': duration_seconds,
            'duration_formatted': format_time(duration_seconds),
            'final_summary': final_summary,
            'action_items': deduplicated_action_items,
            'total_chunks_processed': len(all_summaries),
            'cost_breakdown': {
                'transcription_cost': round(total_transcription_cost, 4),
                'summarization_cost': round(total_summarization_cost, 4),
                'total_cost': round(total_cost, 4),
                'currency': 'USD'
            },
            'usage_metrics': {
                'prompt_tokens': total_prompt_tokens,
                'completion_tokens': total_completion_tokens,
                'total_tokens': total_tokens
            },
            'performance_metrics': {
                'transcription_time_seconds': round(total_transcription_time, 1),
                'summarization_time_seconds': round(total_summarization_time, 1),
                'total_processing_time_seconds': round(total_processing_time, 1)
            },
            'completed_at': datetime.utcnow().isoformat()
        }

        # Upload final result to S3
        final_result_s3_key = f'meetings/{meeting_id}/final_result.json'
        print(f"Uploading final result to S3: {final_result_s3_key}")

        s3.put_object(
            Bucket=S3_BUCKET,
            Key=final_result_s3_key,
            Body=json.dumps(final_result, indent=2, default=decimal_to_int),
            ContentType='application/json',
            Metadata={
                'meeting_id': meeting_id
            }
        )

        # Update DynamoDB with final results
        print("Updating DynamoDB with final results...")
        table.update_item(
            Key={'meeting_id': meeting_id},
            UpdateExpression='''
                SET #s = :status,
                    final_summary = :summary,
                    action_items = :action_items,
                    final_result_s3_path = :result_path,
                    updated_at = :updated,
                    completed_at = :completed,
                    total_cost = :cost,
                    cost_breakdown = :cost_breakdown,
                    usage_metrics = :usage,
                    performance_metrics = :perf
            ''',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':status': 'completed',
                ':summary': final_summary,
                ':action_items': deduplicated_action_items,
                ':result_path': final_result_s3_key,
                ':updated': int(datetime.utcnow().timestamp()),
                ':completed': datetime.utcnow().isoformat(),
                ':cost': Decimal(str(round(total_cost, 4))),
                ':cost_breakdown': {
                    'transcription': Decimal(str(round(total_transcription_cost, 4))),
                    'summarization': Decimal(str(round(total_summarization_cost, 4)))
                },
                ':usage': {
                    'prompt_tokens': total_prompt_tokens,
                    'completion_tokens': total_completion_tokens,
                    'total_tokens': total_tokens
                },
                ':perf': {
                    'transcription_time': Decimal(str(round(total_transcription_time, 1))),
                    'summarization_time': Decimal(str(round(total_summarization_time, 1))),
                    'total_time': Decimal(str(round(total_processing_time, 1)))
                }
            }
        )

        print("Result combination complete")

        # Return result for notification step
        return {
            'meeting_id': meeting_id,
            'meeting_name': file_name,
            'duration': format_time(duration_seconds),
            'final_summary': final_summary,
            'action_items': deduplicated_action_items,
            'final_result_s3_path': final_result_s3_key,
            'cost_breakdown': final_result['cost_breakdown'],
            'usage_metrics': final_result['usage_metrics'],
            'performance_metrics': final_result['performance_metrics']
        }

    except Exception as e:
        print(f"Error in result combiner: {e}")
        import traceback
        traceback.print_exc()

        # Update status to failed
        if meeting_id:
            try:
                table.update_item(
                    Key={'meeting_id': meeting_id},
                    UpdateExpression='SET #s = :status, error_message = :error',
                    ExpressionAttributeNames={'#s': 'status'},
                    ExpressionAttributeValues={
                        ':status': 'failed',
                        ':error': str(e)
                    }
                )
            except Exception as update_error:
                print(f"Error updating status: {update_error}")

        raise
