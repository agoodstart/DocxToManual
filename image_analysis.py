import boto3
import os
import json
import sys
from tqdm import tqdm

# AWS clients
s3 = boto3.client('s3')
rekognition = boto3.client('rekognition')
textract = boto3.client('textract')

# Dynamic input: folder path based on DOCX name (e.g., "01-provisioning")
def get_prefix_from_argument():
    if len(sys.argv) < 2:
        print("Usage: python script.py <chapter-folder>")
        sys.exit(1)
    return sys.argv[1]

bucket = 'teamcenter-doc-ingest'
chapter_folder = get_prefix_from_argument()  # e.g., '01-provisioning'
prefix = f"extracted-images/{chapter_folder}/"

# Output dir per chapter
output_dir = os.path.join('output_results', chapter_folder)
os.makedirs(output_dir, exist_ok=True)

def list_png_files(bucket, prefix):
    response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    return [obj['Key'] for obj in response.get('Contents', []) if obj['Key'].endswith('.png')]

def analyze_image(bucket, key):
    s3_image = {'S3Object': {'Bucket': bucket, 'Name': key}}

    rekognition_response = rekognition.detect_labels(
        Image=s3_image,
        MaxLabels=10,
        MinConfidence=75
    )

    textract_response = textract.detect_document_text(
        Document=s3_image
    )

    return rekognition_response, textract_response

def save_json(data, filename):
    with open(os.path.join(output_dir, filename), 'w') as f:
        json.dump(data, f, indent=2)

def summarize(key, rekog, textx):
    print(f"\n--- {key} ---")
    print("Rekognition Labels:")
    for label in rekog['Labels']:
        print(f" - {label['Name']} ({label['Confidence']:.1f}%)")

    print("First few lines of detected text:")
    lines = [b['Text'] for b in textx['Blocks'] if b['BlockType'] == 'LINE']
    for line in lines[:3]:
        print(f" - {line}")
    if len(lines) > 3:
        print(" - ...")

def main():
    print(f"Analyzing images in S3: s3://{bucket}/{prefix}")
    image_keys = list_png_files(bucket, prefix)

    if not image_keys:
        print("No .png images found.")
        return

    for key in tqdm(image_keys, desc="Processing images"):
        rekog_data, textract_data = analyze_image(bucket, key)

        short_name = os.path.basename(key).replace('.png', '')
        save_json(rekog_data, f"{short_name}_rekognition.json")
        save_json(textract_data, f"{short_name}_textract.json")

        summarize(key, rekog_data, textract_data)

if __name__ == "__main__":
    main()
