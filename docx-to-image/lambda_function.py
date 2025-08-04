import boto3
import os
import zipfile
import io
import time
import json
from PIL import Image
from botocore.exceptions import ClientError

# AWS clients
s3 = boto3.client('s3')
eventbridge = boto3.client('events')
dynamodb = boto3.resource('dynamodb')
task_table = dynamodb.Table('TaskTracker')

def lambda_handler(event, context):
    start_time = time.time()

    # Step 1: Get S3 event info
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = event['Records'][0]['s3']['object']['key']
    chapter_name = os.path.splitext(os.path.basename(key))[0]
    target_prefix = f"extracted-images/{chapter_name}/"

    if not key.lower().endswith(".docx"):
        print(f"[{elapsed(start_time)}] Not a DOCX. Skipping.")
        return

    # Step 2: Download .docx
    try:
        docx_stream = io.BytesIO(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
    except ClientError as e:
        print(f"[{elapsed(start_time)}] S3 download failed: {e}")
        return

    # Step 3: Extract and upload images
    try:
        with zipfile.ZipFile(docx_stream) as docx_zip:
            media_files = [f for f in docx_zip.namelist() if f.startswith("word/media/")]
            if not media_files:
                print(f"[{elapsed(start_time)}] No images found.")
                return

            print(f"[{elapsed(start_time)}] Found {len(media_files)} image(s).")

            for i, media_file in enumerate(media_files, start=1):
                img_data = docx_zip.read(media_file)

                try:
                    img = Image.open(io.BytesIO(img_data))
                    img_format = img.format.upper()

                    output_key = f"{target_prefix}image_{i}.png"

                    if img_format == "PNG":
                        s3.put_object(
                            Bucket=bucket,
                            Key=output_key,
                            Body=img_data,
                            ContentType="image/png"
                        )
                        print(f"[{elapsed(start_time)}] Uploaded original PNG: {output_key}")
                    else:
                        out_buffer = io.BytesIO()
                        img.convert("RGB").save(out_buffer, format="PNG")
                        out_buffer.seek(0)
                        s3.put_object(
                            Bucket=bucket,
                            Key=output_key,
                            Body=out_buffer,
                            ContentType="image/png"
                        )
                        print(f"[{elapsed(start_time)}] Converted and uploaded {img_format} as PNG: {output_key}")
                except Exception as e:
                    print(f"[{elapsed(start_time)}] Failed to process {media_file}: {e}")

        # Step 4: Mark chapter as complete in DynamoDB
        # update_task_tracker(chapter_name)

        # Step 5: Fire EventBridge
        # trigger_eventbridge(chapter_name, start_time)

    except zipfile.BadZipFile:
        print(f"[{elapsed(start_time)}] Corrupted .docx file.")
    except Exception as e:
        print(f"[{elapsed(start_time)}] Error: {e}")

def update_task_tracker(chapter):
    try:
        task_table.put_item(Item={
            "chapter": chapter,
            "status": "images_extracted",
            "timestamp": int(time.time())
        })
        print(f"[TRACKER] Marked chapter '{chapter}' as extracted.")
    except Exception as e:
        print(f"[TRACKER] Failed to write to DynamoDB: {e}")

def trigger_eventbridge(chapter, start_time):
    try:
        eventbridge.put_events(Entries=[{
            "Source": "teamcenter-doc",
            "DetailType": "ChapterProcessed",
            "Detail": json.dumps({"chapter_folder": chapter}),
            "EventBusName": "default"
        }])
        print(f"[{elapsed(start_time)}] Event sent for {chapter}.")
    except Exception as e:
        print(f"[{elapsed(start_time)}] EventBridge error: {e}")

def elapsed(start_time):
    return f"{time.time() - start_time:.2f}s"