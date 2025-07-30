import boto3
import os
import zipfile
import io
import time
import json
from PIL import Image
from botocore.exceptions import ClientError

s3 = boto3.client('s3')
eventbridge = boto3.client('events')

def lambda_handler(event, context):
    start_time = time.time()

    # Step 1: Extract S3 event metadata
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = event['Records'][0]['s3']['object']['key']
    base_filename = os.path.splitext(os.path.basename(key))[0]
    target_prefix = f"extracted-images/{base_filename}/"

    if not key.lower().endswith('.docx'):
        print(f"[{elapsed(start_time)}] Not a .docx file, skipping.")
        return

    print(f"[{elapsed(start_time)}] Processing: s3://{bucket}/{key}")

    # Step 2: Download .docx from S3
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        docx_stream = io.BytesIO(response['Body'].read())
    except Exception as e:
        print(f"[{elapsed(start_time)}] Failed to download DOCX: {e}")
        return

    # Step 3: Extract and upload images
    try:
        with zipfile.ZipFile(docx_stream) as docx_zip:
            media_files = [f for f in docx_zip.namelist() if f.startswith("word/media/")]

            if not media_files:
                print(f"[{elapsed(start_time)}] No images found.")
                return

            print(f"[{elapsed(start_time)}] Found {len(media_files)} images")

            for i, media_file in enumerate(media_files, start=1):
                try:
                    img_bytes = docx_zip.read(media_file)
                    with Image.open(io.BytesIO(img_bytes)) as img:
                        img = img.convert("RGB")  # Ensures compatibility
                        out_buffer = io.BytesIO()
                        img.save(out_buffer, format='PNG')
                        out_buffer.seek(0)

                        image_key = f"{target_prefix}image_{i}.png"
                        s3.put_object(
                            Bucket=bucket,
                            Key=image_key,
                            Body=out_buffer,
                            ContentType='image/png'
                        )
                        print(f"[{elapsed(start_time)}] Uploaded {image_key} ({out_buffer.getbuffer().nbytes} bytes)")

                except Exception as img_err:
                    print(f"[{elapsed(start_time)}] Failed to process {media_file}: {img_err}")

            # Step 4: Trigger EventBridge only if images were processed
            send_chapter_processed_event(base_filename, start_time)

    except zipfile.BadZipFile:
        print(f"[{elapsed(start_time)}] Not a valid .docx (corrupt ZIP).")
    except Exception as e:
        print(f"[{elapsed(start_time)}] Unexpected error: {e}")

def send_chapter_processed_event(chapter_folder, start_time):
    try:
        response = eventbridge.put_events(
            Entries=[
                {
                    "Source": "teamcenter-doc",
                    "DetailType": "ChapterProcessed",
                    "Detail": json.dumps({"chapter_folder": chapter_folder}),
                    "EventBusName": "default"
                }
            ]
        )
        print(f"[{elapsed(start_time)}] EventBridge event sent for chapter: {chapter_folder}")
    except Exception as e:
        print(f"[{elapsed(start_time)}] Failed to send EventBridge event: {e}")

def elapsed(start_time):
    return f"{time.time() - start_time:.2f}s"
