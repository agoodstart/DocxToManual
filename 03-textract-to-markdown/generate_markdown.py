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

def list_text_files():
    try:
        response = s3.list_objects_v2(Bucket=bucket, Prefix=source_prefix)
        contents = response.get("Contents", [])
        return [obj["Key"] for obj in contents if obj["Key"].endswith(".txt")]
    except ClientError as e:
        print(f"[ERROR] Listing files: {e}")
        return []

def read_txt_from_s3(key):
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        return response["Body"].read().decode("utf-8")
    except Exception as e:
        print(f"[ERROR] Reading {key}: {e}")
        return ""

def build_prompt(extracted_text, chapter_context):
    return f"""
You are a professional technical writer responsible for documenting complex IT setup instructions, including but not limited to:

- Provisioning VMs and configuring hypervisors (e.g., vSphere)
- Installing operating systems and configuring hardware
- Installing and configuring middleware (Java, Tomcat)
- Installing and configuring databases (SQL Server, Oracle)
- Performing enterprise software installations (e.g., Teamcenter)
- Setting up deployment tools and automation (e.g., Deployment Center)
- Network configuration, licensing, and security settings

These individual files are verbose and low-level. Your job is to summarize them into a single, **clean and concise instruction manual** for the chapter titled: **{chapter_context}**.

A screenshot was processed using OCR. Your task is to:
1. Identify what the screenshot is instructing the user to do.
2. Write a precise, step-by-step instruction for that action.
3. Avoid hallucination; if unsure, provide only what is visible or implied.
4. Use clear, formal language suitable for technical documentation.
5. End with a helpful note if applicable (e.g., software dependencies, account permissions).

Here is the extracted UI text:
\"\"\"
{extracted_text}
\"\"\"

Write a documentation step for this screenshot.
""".strip()

def call_bedrock_claude(prompt, retries=3):
    for attempt in range(retries):
        try:
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "temperature": 0.2,
                "messages": [{"role": "user", "content": prompt}]
            }

            response = bedrock.invoke_model(
                modelId=CLAUDE_MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body)
            )
            result = json.loads(response["body"].read())
            return result["content"][0]["text"].strip()
        except (BotoCoreError, ClientError, KeyError, IndexError) as e:
            print(f"[Retry {attempt + 1}] Claude error: {e}")
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
    print(f"[INFO] Processing TXT files from: s3://{bucket}/{source_prefix}")
    keys = list_text_files()
    if not keys:
        print("[WARN] No .txt files found.")
        return

    for key in tqdm(keys, desc="Generating Markdown"):
        base_name = os.path.basename(key).replace(".txt", "")
        extracted_text = read_txt_from_s3(key)
        if not extracted_text.strip():
            print(f"[SKIP] {key} is empty.")
            continue

        prompt = build_prompt(extracted_text, chapter_folder)
        markdown = call_bedrock_claude(prompt)
        if markdown:
            upload_markdown_to_s3(f"{base_name}.md", markdown)

if __name__ == "__main__":
    main()