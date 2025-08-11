import boto3
import os
import zipfile
import io
import time
import json
from botocore.exceptions import ClientError

# AWS clients
s3 = boto3.client('s3')
eventbridge = boto3.client('events')
dynamodb = boto3.resource('dynamodb')
task_table = dynamodb.Table('TaskTracker')

def lambda_handler(event, context):
    start_time = time.time()

    print(f"[{elapsed(start_time)}] S3 download failed: {e}")

def elapsed(start_time):
    return f"{time.time() - start_time:.2f}s"