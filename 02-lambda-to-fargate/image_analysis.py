import boto3
import os
import json
import sys
from tqdm import tqdm

# AWS clients
s3 = boto3.client('s3')
textract = boto3.client('textract')

# Get chapter folder from environment variable
chapter_folder = os.environ.get("CHAPTER_FOLDER")
if not chapter_folder:
    print("CHAPTER_FOLDER environment variable is required.")
    sys.exit(1)

bucket = 'teamcenter-doc-ingest'
prefix = f"extracted-images/{chapter_folder}/"

def list_png_files(bucket, prefix):
    response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    return [obj['Key'] for obj in response.get('Contents', []) if obj['Key'].endswith('.png')]

def analyze_image(bucket, key):
    return textract.detect_document_text(Document={'S3Object': {'Bucket': bucket, 'Name': key}})

def extract_ordered_lines(textract_data):
    lines = [
        {
            "text": block["Text"],
            "top": block["Geometry"]["BoundingBox"]["Top"]
        }
        for block in textract_data.get("Blocks", [])
        if block.get("BlockType") == "LINE" and "Text" in block
    ]
    return sorted(lines, key=lambda x: x["top"])

def detect_numbered_steps(ordered_lines):
    steps = []
    skip_next = False
    for i, line in enumerate(ordered_lines):
        if skip_next:
            skip_next = False
            continue
        if line["text"].strip() in {"1", "2", "3", "4", "5", "6", "7", "8"}:
            label = line["text"].strip()
            if i + 1 < len(ordered_lines):
                next_line = ordered_lines[i + 1]
                steps.append(f"{label}. {next_line['text']}")
                skip_next = True
        else:
            steps.append(line["text"])
    return steps

def save_txt_to_s3(steps, filename):
    key = f"ocr-text/{chapter_folder}/{filename}.txt"
    body = "\n".join(steps)
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType='text/plain'
    )
    print(f"[OK] Uploaded text: {key}")

def main():
    print(f"Analyzing: s3://{bucket}/{prefix}")
    keys = list_png_files(bucket, prefix)

    for key in tqdm(keys, desc="Processing images"):
        textract_data = analyze_image(bucket, key)
        ordered_lines = extract_ordered_lines(textract_data)
        steps = detect_numbered_steps(ordered_lines)

        base_name = os.path.basename(key).replace('.png', '')
        save_txt_to_s3(steps, base_name)

if __name__ == "__main__":
    main()
