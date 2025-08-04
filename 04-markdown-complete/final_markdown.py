
import os
import json
import re
import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Constants
CLAUDE_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"
BUCKET_NAME = "teamcenter-doc-ingest"

# Required ENV variable
CHAPTER_FOLDER = os.environ.get("CHAPTER_FOLDER")
if not CHAPTER_FOLDER:
    print("[ERROR] CHAPTER_FOLDER environment variable not set.")
    exit(1)

SOURCE_PREFIX = f"markdown/{CHAPTER_FOLDER}/"
TARGET_KEY = f"final-output/{CHAPTER_FOLDER}.md"

# AWS clients
s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

# ---- Claude Invocation ----

def call_bedrock_claude(prompt):
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2048,
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
    except (BotoCoreError, ClientError, KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"[ERROR] Claude response parsing failed: {e}")
        return "[ERROR] Failed to get a response from Claude."

# ---- Markdown Handling ----

def extract_step_number(key):
    match = re.search(r"(\d+)", key)
    return int(match.group(1)) if match else 0

def list_markdown_files():
    try:
        response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=SOURCE_PREFIX)
        keys = [
            obj["Key"] for obj in response.get("Contents", [])
            if obj["Key"].endswith(".md")
        ]
        return sorted(keys, key=extract_step_number)
    except ClientError as e:
        print(f"[ERROR] Failed to list markdown files: {e}")
        return []

def download_markdown(key):
    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key=key)
        return response["Body"].read().decode("utf-8")
    except ClientError as e:
        print(f"[ERROR] Failed to download {key}: {e}")
        return ""

def combine_markdown_from_s3(keys):
    chapter_title = CHAPTER_FOLDER.replace("-", " ").title()
    combined = f"# Chapter - {chapter_title}\n\n"
    for key in keys:
        step_number = extract_step_number(key)
        content = download_markdown(key).strip()
        if content:
            combined += f"### Step {step_number}\n\n{content}\n\n---\n\n"
    return combined

# ---- Prompt Template ----

def build_claude_prompt(raw_markdown):
    chapter_context = CHAPTER_FOLDER.replace("-", " ").title()

    return f"""
You are a senior technical writer creating professional IT installation documentation for an enterprise environment.

The content below consists of **multiple detailed Markdown files** generated from screenshots. These describe steps taken inside tools like VMware vSphere or SQL Server during a provisioning or configuration workflow.

These individual files are verbose and low-level. Your job is to summarize them into a single, **clean and concise instruction manual** for the chapter titled: **{chapter_context}**.

## Your instructions:
1. **Do NOT copy every UI detail** - focus on the user's real goals and tasks.
2. **Group related steps** together logically. If 5 images show steps in a wizard, summarize the wizard flow into 1 section.
3. Use **headings** to structure the process (e.g., "Creating a New Virtual Machine", "Assigning Storage").
4. Remove **any repetition or redundant options**.
5. Use **professional, instructional tone**, like in official VMware or Microsoft installation guides.
6. Keep **valid Markdown formatting** with headings and numbered lists.

You are writing this for someone experienced in IT who needs **just enough instruction** to repeat the process confidently.

--- BEGIN RAW MARKDOWN (OCR GENERATED) ---
{raw_markdown}
--- END RAW MARKDOWN ---

Now return the **summarized, cleaned, and properly structured** instruction manual in valid Markdown. Do NOT include any text outside the Markdown output.
""".strip()

# ---- Upload Final Result ----

def upload_to_s3(key, content):
    try:
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="text/markdown"
        )
        print(f"✅ Uploaded to: s3://{BUCKET_NAME}/{key}")
    except ClientError as e:
        print(f"[ERROR] Upload failed: {e}")

# ---- Main Execution ----

if __name__ == "__main__":
    print(f"[INFO] Gathering Markdown files from: s3://{BUCKET_NAME}/{SOURCE_PREFIX}")
    markdown_keys = list_markdown_files()

    if not markdown_keys:
        print("[WARN] No markdown files found.")
        exit(0)

    print(f"[INFO] Downloading and combining {len(markdown_keys)} files...")
    raw_markdown = combine_markdown_from_s3(markdown_keys)

    print("[INFO] Sending prompt to Claude...")
    final_markdown = call_bedrock_claude(build_claude_prompt(raw_markdown))

    print("[INFO] Uploading final output...")
    upload_to_s3(TARGET_KEY, final_markdown)
