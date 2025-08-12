import os
import io
import json
import time
import hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote_plus

import boto3
from botocore.exceptions import ClientError

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

# ENV
INTAKE_TABLE = os.environ.get("INTAKE_TABLE", "IntakeTracker")
IDEMPOTENCY_TTL_SECONDS = int(os.environ.get("IDEMPOTENCY_TTL_SECONDS", "600"))  # 10 min default
STAGED_PREFIX = os.environ.get("STAGED_PREFIX", "staged/")
RAW_PREFIX = os.environ.get("RAW_PREFIX", "intake-raw/")
ACCEPT_SUFFIX = os.environ.get("ACCEPT_SUFFIX", ".docx")

table = dynamodb.Table(INTAKE_TABLE)

def _now_utc_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _job_id():
    # timestamp + short random for uniqueness
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

def _hash_stream(body: bytes) -> str:
    h = hashlib.sha256()
    h.update(body)
    return h.hexdigest()

def _get_event_bucket_key(event):
    """
    Supports:
    - EventBridge S3 'Object Created' event (recommended)
    - Manual invoke with { "bucket": "...", "key": "..." }
    """
    if "detail" in event and "bucket" in event["detail"]:
        bucket = event["detail"]["bucket"]["name"]
        key = unquote_plus(event["detail"]["object"]["key"])
        etag = event["detail"]["object"].get("etag")
        size = event["detail"]["object"].get("size")
        return bucket, key, etag, size
    # manual/test
    return event["bucket"], event["key"], None, None

def lambda_handler(event, context):
    start = time.time()
    bucket, key, etag, size = _get_event_bucket_key(event)

    if not key.lower().endswith(ACCEPT_SUFFIX):
        print(f"Skip non-{ACCEPT_SUFFIX}: {key}")
        return {"skipped": True, "reason": "suffix_mismatch", "key": key}

    if not key.startswith(RAW_PREFIX):
        print(f"Skip key outside {RAW_PREFIX}: {key}")
        return {"skipped": True, "reason": "prefix_mismatch", "key": key}

    basename = os.path.splitext(os.path.basename(key))[0]  # e.g., provisioning
    job_id = _job_id()
    staged_key = f"{STAGED_PREFIX}{basename}/{job_id}/source{ACCEPT_SUFFIX}"

    # Fetch metadata and (optionally) the body to compute sha256 if no ETag
    try:
        head = s3.head_object(Bucket=bucket, Key=key)
        meta = head.get("Metadata", {})  # x-amz-meta-*
        # Optional user-supplied metadata
        purpose = meta.get("purpose")
        labels_raw = meta.get("labels", "")
        labels = [l.strip() for l in labels_raw.split(",") if l.strip()] if labels_raw else []
        source_etag = (head.get("ETag") or "").strip('"') or (etag or "")
        content_length = head.get("ContentLength") or size or 0
    except ClientError as e:
        raise RuntimeError(f"head_object failed for s3://{bucket}/{key}: {e}")

    # If we don't trust ETag (multi-part), or want stronger idempotency, compute sha256
    # For most docx sizes this is cheap; toggle via env if you want to skip
    compute_sha256 = os.environ.get("COMPUTE_SHA256", "true").lower() == "true"
    source_sha256 = None
    if compute_sha256:
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
            body = obj["Body"].read()
            source_sha256 = _hash_stream(body)
        except ClientError as e:
            raise RuntimeError(f"get_object failed for sha256: {e}")

    # Idempotency guard: create a short-lived lock item per (basename, hash)
    # Prevents duplicate staging if many events arrive at once.
    # PK: IDEMPOTENCY#<basename>
    # SK: HASH#<etag_or_sha256>
    id_hash = source_sha256 or source_etag or f"size:{content_length}"
    id_pk = f"IDEMPOTENCY#{basename}"
    id_sk = f"HASH#{id_hash}"
    ttl = int(time.time()) + IDEMPOTENCY_TTL_SECONDS

    try:
        table.put_item(
            Item={
                "PK": id_pk,
                "SK": id_sk,
                "basename": basename,
                "doc_hash": id_hash,
                "created_at": _now_utc_iso(),
                "ttl": ttl,
                "source_bucket": bucket,
                "source_key": key,
            },
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
        print(f"Idempotency lock created for {basename} {id_hash}")
    except ClientError as e:
        # ConditionalCheckFailedException → lock exists → skip duplicate
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            print(f"Duplicate intake suppressed for {basename} {id_hash}")
            return {"skipped": True, "reason": "duplicate", "basename": basename}
        raise

    # Stage the doc: copy under a job-scoped path (never overwrite intake)
    try:
        s3.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": key},
            Key=staged_key,
            MetadataDirective="COPY",  # retain user metadata
        )
        print(f"Staged to s3://{bucket}/{staged_key}")
    except ClientError as e:
        # Cleanup idempotency lock on failure
        _cleanup_idempotency_lock(id_pk, id_sk)
        raise RuntimeError(f"Failed to stage object: {e}")

    # Write intake record (STAGED)
    # PK: DOC#<basename>, SK: JOB#<job_id>
    intake_item = {
        "PK": f"DOC#{basename}",
        "SK": f"JOB#{job_id}",
        "doc_basename": basename,
        "job_id": job_id,
        "state": "STAGED",
        "source_bucket": bucket,
        "source_key": key,
        "staged_bucket": bucket,
        "staged_key": staged_key,
        "source_etag": source_etag,
        "source_sha256": source_sha256,
        "content_length": content_length,
        "purpose": purpose,
        "labels": labels,
        "created_at": _now_utc_iso(),
        "updated_at": _now_utc_iso(),
    }

    try:
        table.put_item(
            Item=intake_item,
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
        print(f"Intake record created: DOC#{basename} / JOB#{job_id}")
    except ClientError as e:
        # If somehow job_id collides (unlikely), clean staged copy & idempotency lock
        _cleanup_idempotency_lock(id_pk, id_sk)
        _cleanup_staged_object(bucket, staged_key)
        raise

    elapsed = time.time() - start
    return {
        "ok": True,
        "state": "STAGED",
        "job_id": job_id,
        "doc_basename": basename,
        "bucket": bucket,
        "staged_key": staged_key,
        "source_key": key,
        "labels": labels,
        "purpose": purpose,
        "elapsed_sec": round(elapsed, 3),
    }

def _cleanup_idempotency_lock(pk, sk):
    try:
        table.delete_item(Key={"PK": pk, "SK": sk})
    except Exception:
        pass

def _cleanup_staged_object(bucket, key):
    try:
        s3.delete_object(Bucket=bucket, Key=key)
    except Exception:
        pass
