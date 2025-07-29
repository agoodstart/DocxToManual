import os
import json
import re
import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Claude model ID
CLAUDE_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"

# AWS client for Bedrock
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

def extract_step_number(filename):
    """Extracts step number from filename like 'step_03.md' or '03_disk.md'"""
    match = re.search(r"(\d+)", filename)
    return int(match.group(1)) if match else 0

def combine_markdown_files(source_dir):
    """Combines individual step markdowns into a single markdown string"""
    combined = ""
    files = sorted(
        [f for f in os.listdir(source_dir) if f.endswith(".md")],
        key=extract_step_number
    )
    for f in files:
        filepath = os.path.join(source_dir, f)
        step_number = extract_step_number(f)
        with open(filepath, "r", encoding="utf-8") as file:
            combined += f"### Step {step_number}\n\n"
            combined += file.read().strip() + "\n\n"
    return combined

# ---- Prompt Template ----

def build_claude_prompt(raw_markdown):
    return f"""
You are a technical documentation assistant.

Below is a series of markdown-formatted configuration steps that were generated from processed screenshots. These steps may be out of order, redundant, or inconsistently written.

Your task is to:
- Reorder the steps logically (e.g., provisioning order, dependencies)
- Remove any redundant or irrelevant content
- Keep instructions clear, formal, and concise
- Preserve important technical details
- Maintain valid Markdown formatting (headings, lists, code blocks)

Prepare the result so it can be used directly in a provisioning manual.

--- BEGIN DRAFT ---
{raw_markdown}
--- END DRAFT ---
""".strip()

# ---- Main Execution ----

if __name__ == "__main__":
    input_dir = "generated_steps"
    output_file = "01-provisioning.md"

    print("[INFO] Combining markdown files...")
    raw_markdown = combine_markdown_files(input_dir)

    print("[INFO] Building prompt and sending to Claude...")
    prompt = build_claude_prompt(raw_markdown)
    final_markdown = call_bedrock_claude(prompt)

    with open(output_file, "w", encoding="utf-8") as out:
        out.write(final_markdown)

    print(f"✅ Refined provisioning section saved to: {output_file}")