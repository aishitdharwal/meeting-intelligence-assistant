"""
Transcriber Lambda
Transcribes audio chunks using OpenAI Whisper API
"""

import json
import os
import boto3
import time
from openai import OpenAI
from common.openai_pricing import calculate_whisper_cost

s3 = boto3.client('s3')
secretsmanager = boto3.client('secretsmanager')

S3_BUCKET = os.environ['S3_BUCKET']
OPENAI_API_KEY_SECRET_NAME = os.environ['OPENAI_API_KEY_SECRET_NAME']

# Initialize OpenAI client (will be set in handler)
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


def transcribe_audio(audio_file_path, chunk_id):
    """Transcribe audio using OpenAI Whisper API with retry logic"""
    client = get_openai_client()

    max_retries = 3
    retry_delay = 2  # seconds

    for attempt in range(max_retries):
        try:
            print(f"Transcribing chunk {chunk_id} (attempt {attempt + 1}/{max_retries})...")

            with open(audio_file_path, 'rb') as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"]
                )

            print(f"Transcription successful for chunk {chunk_id}")
            return transcript

        except Exception as e:
            error_msg = str(e)
            print(f"Transcription attempt {attempt + 1} failed: {error_msg}")

            # Check if it's a rate limit error
            if '429' in error_msg or 'rate_limit' in error_msg.lower():
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                    print(f"Rate limited. Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    continue

            # Check if it's a timeout or server error
            elif any(code in error_msg for code in ['500', '502', '503', '504', 'timeout']):
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    print(f"Server error. Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    continue

            # If it's the last attempt or a different error, raise
            if attempt == max_retries - 1:
                print(f"All retry attempts exhausted for chunk {chunk_id}")
                raise

    raise RuntimeError(f"Failed to transcribe chunk {chunk_id} after {max_retries} attempts")


def lambda_handler(event, context):
    """Main handler for transcription"""
    print(f"Received event: {json.dumps(event)}")

    audio_local_path = None

    try:
        # Extract chunk information
        chunk_id = event['chunk_id']
        s3_path = event['s3_path']
        s3_bucket = event.get('s3_bucket', S3_BUCKET)
        meeting_id = event['meeting_id']
        start_time = event['start_time']
        end_time = event['end_time']

        print(f"Processing chunk {chunk_id} for meeting {meeting_id}")
        print(f"Time range: {start_time}s - {end_time}s")
        print(f"S3 path: s3://{s3_bucket}/{s3_path}")

        # Download audio chunk from S3
        audio_local_path = f'/tmp/chunk_{chunk_id}_{meeting_id}.wav'
        print(f"Downloading chunk from S3...")
        s3.download_file(s3_bucket, s3_path, audio_local_path)

        chunk_size = os.path.getsize(audio_local_path)
        print(f"Chunk downloaded: {chunk_size / 1024 / 1024:.2f} MB")

        # Transcribe audio with timing
        transcription_start_time = time.time()
        transcript = transcribe_audio(audio_local_path, chunk_id)
        transcription_processing_time = time.time() - transcription_start_time
        print(f"Transcription processing time: {transcription_processing_time:.2f}s")

        # Convert transcript to dict
        transcript_dict = {
            'text': transcript.text,
            'language': getattr(transcript, 'language', 'unknown'),
            'duration': getattr(transcript, 'duration', 0),
            'segments': []
        }

        # Process segments if available
        if hasattr(transcript, 'segments') and transcript.segments:
            for segment in transcript.segments:
                segment_dict = {
                    'id': segment.id,
                    'start': segment.start,
                    'end': segment.end,
                    'text': segment.text
                }
                transcript_dict['segments'].append(segment_dict)

            print(f"Transcribed {len(transcript_dict['segments'])} segments")

        print(f"Transcript text length: {len(transcript_dict['text'])} characters")
        print(f"Language detected: {transcript_dict['language']}")

        # Add chunk metadata
        transcript_dict['chunk_id'] = chunk_id
        transcript_dict['meeting_id'] = meeting_id
        transcript_dict['start_time'] = start_time
        transcript_dict['end_time'] = end_time

        # Calculate transcription cost
        duration = transcript_dict['duration']
        transcription_cost = calculate_whisper_cost(duration)
        print(f"Transcription cost: ${transcription_cost:.4f} for {duration:.1f}s of audio")

        # Upload transcript to S3
        transcript_s3_key = f'meetings/{meeting_id}/transcripts/transcript_{chunk_id}.json'
        print(f"Uploading transcript to S3: {transcript_s3_key}")

        s3.put_object(
            Bucket=S3_BUCKET,
            Key=transcript_s3_key,
            Body=json.dumps(transcript_dict, indent=2),
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
            'transcript_s3_path': transcript_s3_key,
            'transcript_s3_bucket': S3_BUCKET,
            'start_time': start_time,
            'end_time': end_time,
            'text_length': len(transcript_dict['text']),
            'language': transcript_dict['language'],
            'duration': duration,
            'cost': transcription_cost,
            'model': 'whisper-1',
            'processing_time_seconds': transcription_processing_time,
            'status': 'success'
        }

        print(f"Transcription complete for chunk {chunk_id}")
        print(f"Result: {json.dumps(result)}")

        return result

    except Exception as e:
        print(f"Error in transcriber: {e}")
        import traceback
        traceback.print_exc()

        # Return error result (don't raise - let workflow continue)
        return {
            'chunk_id': event.get('chunk_id', -1),
            'meeting_id': event.get('meeting_id', 'unknown'),
            'status': 'failed',
            'error': str(e)
        }

    finally:
        # Cleanup temporary files
        if audio_local_path and os.path.exists(audio_local_path):
            try:
                os.remove(audio_local_path)
                print(f"Cleaned up: {audio_local_path}")
            except Exception as e:
                print(f"Error cleaning up audio file: {e}")
