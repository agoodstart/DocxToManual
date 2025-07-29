import json
import boto3
import os
import sys
from io import BytesIO
from tqdm import tqdm
from botocore.exceptions import BotoCoreError, ClientError

# Environment configuration
chapter_folder = os.environ.get("CHAPTER_FOLDER")
if not chapter_folder:
    print("CHAPTER_FOLDER environment variable is required.")
    sys.exit(1)

bucket = "teamcenter-doc-ingest"
source_prefix = f"ocr-text/{chapter_folder}/"
target_prefix = f"markdown/{chapter_folder}/"

# AWS clients
s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

CLAUDE_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"

def list_textract_files():
    try:
        response = s3.list_objects_v2(Bucket=bucket, Prefix=source_prefix)
        contents = response.get("Contents", [])
        return [obj["Key"] for obj in contents if obj["Key"].endswith("_textract.json")]
    except ClientError as e:
        print(f"[ERROR] Listing files: {e}")
        return []

def read_textract_from_s3(key):
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        data = json.load(response["Body"])
        lines = [b['Text'] for b in data.get('Blocks', []) if b.get('BlockType') == 'LINE' and 'Text' in b]
        return "\n".join(lines)
    except Exception as e:
        print(f"[ERROR] Reading {key}: {e}")
        return ""

def build_prompt(extracted_text):
    return f"""
You are a professional technical writer documenting a step in a virtualization guide. A screenshot was processed, and the following user interface texts were extracted from the image.

Your job is to:
1. Recognize what this step is about (e.g., customizing VM hardware).
2. Write clear instructions for the user to follow.
3. Include all relevant parameters (CPU, memory, disk, network, etc.).
4. Use formal, concise language suitable for IT documentation.
5. Do not include UI elements that are unrelated or unclear.

Here is the extracted UI text:
\"\"\"
{extracted_text}
\"\"\"

Write a configuration step for the manual.
""".strip()

def call_bedrock_claude(prompt):
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "temperature": 0.2,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    try:
        response = bedrock.invoke_model(
            modelId=CLAUDE_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body)
        )
        result = json.loads(response["body"].read())
        return result["content"][0]["text"].strip()
    except (BotoCoreError, ClientError, KeyError, IndexError) as e:
        print(f"[ERROR] Claude error: {e}")
        return ""

def upload_markdown_to_s3(filename, content):
    key = target_prefix + filename
    try:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="text/markdown"
        )
        print(f"[OK] Uploaded: s3://{bucket}/{key}")
    except ClientError as e:
        print(f"[ERROR] Upload failed for {filename}: {e}")

def main():
    print(f"[INFO] Processing files from: s3://{bucket}/{source_prefix}")
    keys = list_textract_files()
    if not keys:
        print("[WARN] No textract JSON files found.")
        return

    for key in tqdm(keys, desc="Generating Markdown"):
        base_name = os.path.basename(key).replace("_textract.json", "")
        extracted_text = read_textract_from_s3(key)
        if not extracted_text:
            continue

        prompt = build_prompt(extracted_text)
        markdown = call_bedrock_claude(prompt)
        if markdown:
            upload_markdown_to_s3(f"{base_name}.md", markdown)

if __name__ == "__main__":
    main()
