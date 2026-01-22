"""
Summarizer Lambda
Generates summaries and extracts action items using GPT-4o Mini
"""

import json
import os
import boto3
import time
from openai import OpenAI

s3 = boto3.client('s3')
secretsmanager = boto3.client('secretsmanager')

S3_BUCKET = os.environ['S3_BUCKET']
OPENAI_API_KEY_SECRET_NAME = os.environ['OPENAI_API_KEY_SECRET_NAME']

# Initialize OpenAI client
openai_client = None


def get_openai_client():
    """Get OpenAI client with API key from Secrets Manager"""
    global openai_client
    if openai_client is None:
        try:
            response = secretsmanager.get_secret_value(SecretId=OPENAI_API_KEY_SECRET_NAME)
            api_key = response['SecretString']
            openai_client = OpenAI(api_key=api_key)
            print("OpenAI client initialized")
        except Exception as e:
            print(f"Error retrieving OpenAI API key: {e}")
            raise
    return openai_client


def format_transcript_for_summary(transcript_data):
    """Format transcript with timestamps for better summarization"""
    segments = transcript_data.get('segments', [])

    if not segments:
        # If no segments, return full text
        return transcript_data.get('text', '')

    formatted_lines = []
    for segment in segments:
        start = segment.get('start', 0)
        text = segment.get('text', '').strip()
        # Format as [MM:SS] text
        minutes = int(start // 60)
        seconds = int(start % 60)
        formatted_lines.append(f"[{minutes:02d}:{seconds:02d}] {text}")

    return '\n'.join(formatted_lines)


def generate_summary(transcript_text, chunk_id, time_range):
    """Generate summary and action items using GPT-4o Mini"""
    client = get_openai_client()

    prompt = f"""You are analyzing a segment of a business meeting transcript with timestamps.

TRANSCRIPT (Time range: {time_range}):
{transcript_text}

Your task:
1. Write a concise 2-3 sentence summary of the main discussion points in this segment
2. Extract all action items mentioned (tasks, follow-ups, assignments)

Format your response EXACTLY as follows:

SUMMARY:
[Your 2-3 sentence summary here]

ACTION ITEMS:
- Action: [specific task] | Owner: [person name if mentioned, otherwise "Unassigned"] | Due: [date if mentioned, otherwise "Not specified"]
- Action: [specific task] | Owner: [person name if mentioned, otherwise "Unassigned"] | Due: [date if mentioned, otherwise "Not specified"]

If there are no action items, write:
ACTION ITEMS:
None

Important:
- Be specific and concise
- Only include actual action items that were discussed
- Preserve important details like names, dates, and specific requirements
- Use the Owner and Due format consistently"""

    max_retries = 3
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            print(f"Generating summary for chunk {chunk_id} (attempt {attempt + 1}/{max_retries})...")

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that summarizes meeting transcripts and extracts action items."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1000
            )

            summary_text = response.choices[0].message.content
            print(f"Summary generated for chunk {chunk_id}")
            return summary_text

        except Exception as e:
            error_msg = str(e)
            print(f"Summary generation attempt {attempt + 1} failed: {error_msg}")

            # Retry logic for rate limits and server errors
            if ('429' in error_msg or 'rate_limit' in error_msg.lower() or
                any(code in error_msg for code in ['500', '502', '503', '504'])):
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    print(f"Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    continue

            if attempt == max_retries - 1:
                raise

    raise RuntimeError(f"Failed to generate summary for chunk {chunk_id} after {max_retries} attempts")


def parse_summary_response(response_text):
    """Parse the GPT response into summary and action items"""
    try:
        # Split by sections
        parts = response_text.split('ACTION ITEMS:')

        if len(parts) != 2:
            print("WARNING: Could not parse response format properly")
            return {
                'summary': response_text,
                'action_items': []
            }

        # Extract summary
        summary_part = parts[0].replace('SUMMARY:', '').strip()

        # Extract action items
        action_items_part = parts[1].strip()

        action_items = []
        if action_items_part.lower() != 'none':
            for line in action_items_part.split('\n'):
                line = line.strip()
                if line.startswith('-') or line.startswith('•'):
                    # Parse format: - Action: [task] | Owner: [person] | Due: [date]
                    line = line.lstrip('-•').strip()

                    action_dict = {
                        'action': '',
                        'owner': 'Unassigned',
                        'due_date': 'Not specified'
                    }

                    parts = line.split('|')
                    for part in parts:
                        part = part.strip()
                        if part.startswith('Action:'):
                            action_dict['action'] = part.replace('Action:', '').strip()
                        elif part.startswith('Owner:'):
                            action_dict['owner'] = part.replace('Owner:', '').strip()
                        elif part.startswith('Due:'):
                            action_dict['due_date'] = part.replace('Due:', '').strip()

                    if action_dict['action']:
                        action_items.append(action_dict)

        return {
            'summary': summary_part,
            'action_items': action_items
        }

    except Exception as e:
        print(f"Error parsing summary response: {e}")
        return {
            'summary': response_text,
            'action_items': []
        }


def lambda_handler(event, context):
    """Main handler for summarization"""
    print(f"Received event: {json.dumps(event)}")

    try:
        # Check if this is a failed transcription
        if event.get('status') == 'failed':
            print(f"Skipping summarization - transcription failed for chunk {event.get('chunk_id')}")
            return {
                'chunk_id': event.get('chunk_id', -1),
                'meeting_id': event.get('meeting_id', 'unknown'),
                'status': 'skipped',
                'reason': 'Transcription failed'
            }

        # Extract transcript information
        chunk_id = event['chunk_id']
        meeting_id = event['meeting_id']
        transcript_s3_path = event['transcript_s3_path']
        start_time = event['start_time']
        end_time = event['end_time']

        # Format time range
        start_min = int(start_time // 60)
        end_min = int(end_time // 60)
        time_range = f"{start_min:02d}:{int(start_time % 60):02d} - {end_min:02d}:{int(end_time % 60):02d}"

        print(f"Processing chunk {chunk_id} for meeting {meeting_id}")
        print(f"Time range: {time_range}")

        # Download transcript from S3
        print(f"Downloading transcript from S3: {transcript_s3_path}")
        transcript_obj = s3.get_object(Bucket=S3_BUCKET, Key=transcript_s3_path)
        transcript_data = json.loads(transcript_obj['Body'].read().decode('utf-8'))

        # Format transcript
        formatted_transcript = format_transcript_for_summary(transcript_data)
        print(f"Formatted transcript length: {len(formatted_transcript)} characters")

        # Generate summary
        summary_response = generate_summary(formatted_transcript, chunk_id, time_range)

        # Parse response
        parsed_summary = parse_summary_response(summary_response)

        print(f"Summary: {parsed_summary['summary'][:100]}...")
        print(f"Action items found: {len(parsed_summary['action_items'])}")

        # Create summary object
        summary_data = {
            'chunk_id': chunk_id,
            'meeting_id': meeting_id,
            'time_range': time_range,
            'start_time': start_time,
            'end_time': end_time,
            'summary': parsed_summary['summary'],
            'action_items': parsed_summary['action_items'],
            'raw_response': summary_response
        }

        # Upload summary to S3
        summary_s3_key = f'meetings/{meeting_id}/summaries/summary_{chunk_id}.json'
        print(f"Uploading summary to S3: {summary_s3_key}")

        s3.put_object(
            Bucket=S3_BUCKET,
            Key=summary_s3_key,
            Body=json.dumps(summary_data, indent=2),
            ContentType='application/json',
            Metadata={
                'meeting_id': meeting_id,
                'chunk_id': str(chunk_id)
            }
        )

        # Prepare result
        result = {
            'chunk_id': chunk_id,
            'meeting_id': meeting_id,
            'summary_s3_path': summary_s3_key,
            'summary_s3_bucket': S3_BUCKET,
            'time_range': time_range,
            'action_items_count': len(parsed_summary['action_items']),
            'status': 'success'
        }

        print(f"Summarization complete for chunk {chunk_id}")
        return result

    except Exception as e:
        print(f"Error in summarizer: {e}")
        import traceback
        traceback.print_exc()

        # Return error result
        return {
            'chunk_id': event.get('chunk_id', -1),
            'meeting_id': event.get('meeting_id', 'unknown'),
            'status': 'failed',
            'error': str(e)
        }
