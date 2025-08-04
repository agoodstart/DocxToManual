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

# Output dir per chapter
output_dir = os.path.join('output_results', chapter_folder)
os.makedirs(output_dir, exist_ok=True)

def list_png_files(bucket, prefix):
    response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    return [obj['Key'] for obj in response.get('Contents', []) if obj['Key'].endswith('.png')]

def analyze_image(bucket, key):
    s3_image = {'S3Object': {'Bucket': bucket, 'Name': key}}

    # Only use Textract
    textract_response = textract.detect_document_text(Document=s3_image)
    return textract_response

def extract_ordered_text(textract_response):
    """
    Returns a list of lines sorted top-to-bottom for better structure.
    """
    lines = [
        {
            "text": block["Text"],
            "top": block["Geometry"]["BoundingBox"]["Top"]
        }
        for block in textract_response.get("Blocks", [])
        if block.get("BlockType") == "LINE" and "Text" in block
    ]

    # Sort by vertical position
    sorted_lines = sorted(lines, key=lambda x: x["top"])
    return [line["text"] for line in sorted_lines]

def save_json_to_s3(data, filename):
    key = f"ocr-text/{chapter_folder}/{filename}"
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data, indent=2),
        ContentType='application/json'
    )
    print(f"[OK] Uploaded: s3://{bucket}/{key}")

def summarize(key, text_lines):
    print(f"\n--- {key} ---")
    print("First few lines of detected text:")
    for line in text_lines[:3]:
        print(f" - {line}")
    if len(text_lines) > 3:
        print(" - ...")

def main():
    print(f"[INFO] Analyzing images in: s3://{bucket}/{prefix}")
    image_keys = list_png_files(bucket, prefix)

    if not image_keys:
        print("[WARN] No .png images found.")
        return

    for key in tqdm(image_keys, desc="Processing images"):
        textract_data = analyze_image(bucket, key)

        # Extract readable and sorted lines
        sorted_text_lines = extract_ordered_text(textract_data)

        # Save full Textract output
        short_name = os.path.basename(key).replace('.png', '')
        save_json_to_s3(textract_data, f"{short_name}_textract.json")

        # Optional: also save ordered plain text file (optional)
        plain_text_key = f"ocr-text/{chapter_folder}/{short_name}.txt"
        s3.put_object(
            Bucket=bucket,
            Key=plain_text_key,
            Body="\n".join(sorted_text_lines).encode("utf-8"),
            ContentType='text/plain'
        )
        print(f"[OK] Uploaded plain text: s3://{bucket}/{plain_text_key}")

        # Log preview
        summarize(key, sorted_text_lines)

if __name__ == "__main__":
    main()