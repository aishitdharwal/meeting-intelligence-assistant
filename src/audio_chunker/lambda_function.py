"""
Audio Chunker Lambda
Splits audio into 10-minute chunks with 30-second overlap
"""

import json
import os
import boto3
import subprocess
import math

s3 = boto3.client('s3')

S3_BUCKET = os.environ['S3_BUCKET']
CHUNK_DURATION = int(os.environ.get('CHUNK_DURATION', 600))  # 10 minutes
OVERLAP_DURATION = int(os.environ.get('OVERLAP_DURATION', 30))  # 30 seconds

# FFmpeg binary path in Lambda layer
FFMPEG_PATH = '/opt/bin/ffmpeg'


def split_audio_chunk(input_path, output_path, start_time, duration):
    """Split audio file into a chunk using FFmpeg"""
    try:
        cmd = [
            FFMPEG_PATH,
            '-i', input_path,
            '-ss', str(start_time),
            '-t', str(duration),
            '-acodec', 'copy',  # Copy codec for faster processing
            '-y',
            output_path
        ]

        print(f"Splitting chunk: start={start_time}s, duration={duration}s")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=120
        )

        return True

    except subprocess.TimeoutExpired:
        print(f"FFmpeg timeout for chunk at {start_time}s")
        return False
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg error: {e.stderr}")
        return False
    except Exception as e:
        print(f"Error splitting audio chunk: {e}")
        return False


def lambda_handler(event, context):
    """Main handler for audio chunking"""
    print(f"Received event: {json.dumps(event)}")

    audio_local_path = None
    chunk_files = []

    try:
        # Extract data from event
        audio_result = event.get('audioResult', {})
        meeting_id = audio_result['meeting_id']
        audio_s3_path = audio_result['audio_s3_path']
        duration_seconds = audio_result['duration_seconds']

        print(f"Processing meeting_id: {meeting_id}")
        print(f"Audio S3 path: {audio_s3_path}")
        print(f"Duration: {duration_seconds} seconds ({duration_seconds / 60:.2f} minutes)")

        # Download audio from S3
        audio_local_path = f'/tmp/audio_{meeting_id}.wav'
        print(f"Downloading audio from S3...")
        s3.download_file(S3_BUCKET, audio_s3_path, audio_local_path)

        audio_size = os.path.getsize(audio_local_path)
        print(f"Audio downloaded: {audio_size / 1024 / 1024:.2f} MB")

        # Calculate number of chunks
        # Each chunk is CHUNK_DURATION seconds, with OVERLAP_DURATION overlap
        num_chunks = math.ceil(duration_seconds / CHUNK_DURATION)
        print(f"Creating {num_chunks} chunks")

        chunks_metadata = []

        # Create chunks
        for i in range(num_chunks):
            # Calculate start time
            # First chunk starts at 0
            # Subsequent chunks overlap by OVERLAP_DURATION seconds
            if i == 0:
                start_time = 0
            else:
                start_time = (i * CHUNK_DURATION) - OVERLAP_DURATION

            # Calculate duration for this chunk
            remaining = duration_seconds - start_time
            chunk_duration = min(CHUNK_DURATION, remaining)

            # Skip if chunk would be too short (< 10 seconds)
            if chunk_duration < 10:
                print(f"Skipping chunk {i}: too short ({chunk_duration}s)")
                continue

            # Create chunk
            chunk_local_path = f'/tmp/chunk_{i}.wav'
            chunk_files.append(chunk_local_path)

            print(f"Creating chunk {i}: start={start_time}s, duration={chunk_duration}s")
            success = split_audio_chunk(
                audio_local_path,
                chunk_local_path,
                start_time,
                chunk_duration
            )

            if not success:
                raise RuntimeError(f"Failed to create chunk {i}")

            chunk_size = os.path.getsize(chunk_local_path)
            print(f"Chunk {i} created: {chunk_size / 1024 / 1024:.2f} MB")

            # Upload chunk to S3
            chunk_s3_key = f'meetings/{meeting_id}/chunks/chunk_{i}.wav'
            print(f"Uploading chunk {i} to S3: {chunk_s3_key}")

            s3.upload_file(
                chunk_local_path,
                S3_BUCKET,
                chunk_s3_key,
                ExtraArgs={
                    'ContentType': 'audio/wav',
                    'Metadata': {
                        'meeting_id': meeting_id,
                        'chunk_id': str(i),
                        'start_time': str(start_time),
                        'duration': str(int(chunk_duration))
                    }
                }
            )

            # Store chunk metadata
            chunks_metadata.append({
                'chunk_id': i,
                's3_path': chunk_s3_key,
                's3_bucket': S3_BUCKET,
                'start_time': start_time,
                'end_time': start_time + chunk_duration,
                'duration': int(chunk_duration),
                'meeting_id': meeting_id
            })

            print(f"Chunk {i} uploaded successfully")

        # Prepare result
        result = {
            'meeting_id': meeting_id,
            'chunks': chunks_metadata,
            'total_chunks': len(chunks_metadata),
            'total_duration': duration_seconds
        }

        print(f"Audio chunking complete. Created {len(chunks_metadata)} chunks")
        print(f"Result: {json.dumps(result, indent=2)}")

        return result

    except Exception as e:
        print(f"Error in audio chunker: {e}")
        import traceback
        traceback.print_exc()
        raise

    finally:
        # Cleanup temporary files
        if audio_local_path and os.path.exists(audio_local_path):
            try:
                os.remove(audio_local_path)
                print(f"Cleaned up: {audio_local_path}")
            except Exception as e:
                print(f"Error cleaning up audio file: {e}")

        for chunk_file in chunk_files:
            if os.path.exists(chunk_file):
                try:
                    os.remove(chunk_file)
                    print(f"Cleaned up: {chunk_file}")
                except Exception as e:
                    print(f"Error cleaning up chunk file: {e}")
