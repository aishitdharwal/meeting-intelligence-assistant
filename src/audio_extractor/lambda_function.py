"""
Audio Extractor Lambda
Extracts audio from video using FFmpeg
"""

import json
import os
import boto3
import subprocess
from datetime import datetime

s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

S3_BUCKET = os.environ['S3_BUCKET']
DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']

table = dynamodb.Table(DYNAMODB_TABLE)

# FFmpeg binary path in Lambda layer
FFMPEG_PATH = '/opt/bin/ffmpeg'
FFPROBE_PATH = '/opt/bin/ffprobe'


def update_status(meeting_id, status, **kwargs):
    """Update meeting status in DynamoDB"""
    try:
        update_expr = 'SET #s = :status, updated_at = :updated'
        expr_attr_names = {'#s': 'status'}
        expr_attr_values = {
            ':status': status,
            ':updated': int(datetime.utcnow().timestamp())
        }

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


def get_video_duration(video_path):
    """Get video duration in seconds using ffprobe"""
    try:
        cmd = [
            FFPROBE_PATH,
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        duration = float(result.stdout.strip())
        return duration
    except Exception as e:
        print(f"Error getting video duration: {e}")
        return None


def extract_audio(video_path, audio_path):
    """Extract audio from video using FFmpeg"""
    try:
        # FFmpeg command to extract audio
        # -vn: no video
        # -acodec pcm_s16le: PCM 16-bit little-endian (WAV format)
        # -ar 16000: 16kHz sample rate (optimal for Whisper)
        # -ac 1: mono audio
        cmd = [
            FFMPEG_PATH,
            '-i', video_path,
            '-vn',
            '-acodec', 'pcm_s16le',
            '-ar', '16000',
            '-ac', '1',
            '-y',  # overwrite output file
            audio_path
        ]

        print(f"Running FFmpeg command: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=600  # 10 minute timeout
        )

        print("FFmpeg stdout:", result.stdout)
        if result.stderr:
            print("FFmpeg stderr:", result.stderr)

        return True

    except subprocess.TimeoutExpired:
        print("FFmpeg process timed out")
        return False
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg failed with return code {e.returncode}")
        print("stdout:", e.stdout)
        print("stderr:", e.stderr)
        return False
    except Exception as e:
        print(f"Error extracting audio: {e}")
        return False


def lambda_handler(event, context):
    """Main handler for audio extraction"""
    print(f"Received event: {json.dumps(event)}")

    video_local_path = None
    audio_local_path = None

    try:
        # Extract data from event
        download_result = event.get('downloadResult', {})
        meeting_id = download_result['meeting_id']
        video_s3_path = download_result['video_s3_path']

        print(f"Processing meeting_id: {meeting_id}")
        print(f"Video S3 path: {video_s3_path}")

        # Update status
        update_status(meeting_id, 'extracting_audio')

        # Prepare local file paths
        video_local_path = f'/tmp/video_{meeting_id}.mp4'
        audio_local_path = f'/tmp/audio_{meeting_id}.wav'

        # Download video from S3
        print(f"Downloading video from S3: {video_s3_path}")
        s3.download_file(S3_BUCKET, video_s3_path, video_local_path)

        video_size = os.path.getsize(video_local_path)
        print(f"Video downloaded: {video_size / 1024 / 1024:.2f} MB")

        # Get video duration
        print("Getting video duration...")
        duration = get_video_duration(video_local_path)
        if duration:
            print(f"Video duration: {duration:.2f} seconds ({duration / 60:.2f} minutes)")

            # Check if video is too long (max 1 hour)
            if duration > 3600:
                raise ValueError(f"Video duration ({duration / 60:.2f} minutes) exceeds maximum of 60 minutes")
        else:
            print("WARNING: Could not determine video duration")
            duration = 0

        # Extract audio
        print("Extracting audio with FFmpeg...")
        success = extract_audio(video_local_path, audio_local_path)

        if not success:
            raise RuntimeError("Failed to extract audio from video")

        audio_size = os.path.getsize(audio_local_path)
        print(f"Audio extracted: {audio_size / 1024 / 1024:.2f} MB")

        # Upload audio to S3
        audio_s3_key = f'meetings/{meeting_id}/audio.wav'
        print(f"Uploading audio to S3: {audio_s3_key}")

        s3.upload_file(
            audio_local_path,
            S3_BUCKET,
            audio_s3_key,
            ExtraArgs={
                'ContentType': 'audio/wav',
                'Metadata': {
                    'meeting_id': meeting_id,
                    'duration_seconds': str(int(duration))
                }
            }
        )

        print(f"Audio uploaded to S3: s3://{S3_BUCKET}/{audio_s3_key}")

        # Update DynamoDB
        update_status(
            meeting_id,
            'audio_extracted',
            audio_s3_path=audio_s3_key,
            audio_s3_bucket=S3_BUCKET,
            duration_seconds=int(duration)
        )

        # Prepare result for next step
        result = {
            'meeting_id': meeting_id,
            'audio_s3_path': audio_s3_key,
            'audio_s3_bucket': S3_BUCKET,
            'duration_seconds': int(duration)
        }

        print(f"Audio extraction complete. Result: {json.dumps(result)}")
        return result

    except Exception as e:
        print(f"Error in audio extractor: {e}")
        import traceback
        traceback.print_exc()

        # Update status to failed
        if 'downloadResult' in event and 'meeting_id' in event['downloadResult']:
            update_status(
                event['downloadResult']['meeting_id'],
                'failed',
                error_stage='audio_extraction',
                error_message=str(e)
            )

        raise

    finally:
        # Cleanup temporary files
        if video_local_path and os.path.exists(video_local_path):
            try:
                os.remove(video_local_path)
                print(f"Cleaned up: {video_local_path}")
            except Exception as e:
                print(f"Error cleaning up video file: {e}")

        if audio_local_path and os.path.exists(audio_local_path):
            try:
                os.remove(audio_local_path)
                print(f"Cleaned up: {audio_local_path}")
            except Exception as e:
                print(f"Error cleaning up audio file: {e}")
