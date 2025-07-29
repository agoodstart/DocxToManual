import boto3
import os
import zipfile
import io
import time
import json
from PIL import Image

s3 = boto3.client('s3')
sfn = boto3.client('stepfunctions')

# Set your Step Function ARN here
STEP_FUNCTION_ARN = os.environ.get("STEP_FUNCTION_ARN")  # Optional: set via Lambda env var

def lambda_handler(event, context):
    start_time = time.time()

    bucket = event['Records'][0]['s3']['bucket']['name']
    key    = event['Records'][0]['s3']['object']['key']
    base_filename = os.path.splitext(os.path.basename(key))[0]
    target_prefix = f"extracted-images/{base_filename}/"

    if not key.lower().endswith('.docx'):
        print("Not a .docx file, skipping...")
        return

    print(f"[{time.time() - start_time:.2f}s] Processing: {bucket}/{key}")

    try:
        # Stream the .docx file directly
        response = s3.get_object(Bucket=bucket, Key=key)
        docx_stream = io.BytesIO(response['Body'].read())
    except Exception as e:
        print(f"[{time.time() - start_time:.2f}s] Failed to download DOCX: {e}")
        return

    try:
        with zipfile.ZipFile(docx_stream) as docx_zip:
            media_files = [f for f in docx_zip.namelist() if f.startswith("word/media/")]

            if not media_files:
                print(f"[{time.time() - start_time:.2f}s] No images found.")
                return

            print(f"[{time.time() - start_time:.2f}s] Found {len(media_files)} images")

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
                        print(f"[{time.time() - start_time:.2f}s] Uploaded {image_key} ({out_buffer.getbuffer().nbytes} bytes)")

                except Exception as img_err:
                    print(f"[{time.time() - start_time:.2f}s] Failed to process {media_file}: {img_err}")

    except zipfile.BadZipFile:
        print(f"[{time.time() - start_time:.2f}s] Not a valid .docx (corrupt ZIP).")
        return
    except Exception as e:
        print(f"[{time.time() - start_time:.2f}s] Unexpected error: {e}")
        return

    # All images extracted successfully — trigger Step Function
    try:
        input_payload = {
            "bucket": bucket,
            "section": base_filename,
            "image_prefix": target_prefix
        }

        response = sfn.start_execution(
            stateMachineArn=STEP_FUNCTION_ARN,
            input=json.dumps(input_payload)
        )
        print(f"[{time.time() - start_time:.2f}s] Step Function triggered: {response['executionArn']}")

    except Exception as sf_error:
        print(f"[{time.time() - start_time:.2f}s] Failed to trigger Step Function: {sf_error}")
