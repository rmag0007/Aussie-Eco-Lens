"""Track 1 - Upload Status Lambda
Returns the current tagging status + S3 locations for a file_id.

Route: GET /upload-status/{file_id}

Response (success):
  {
    "file_id": "...",
    "status": "tagged",
    "tags": {"dingo": 1},
    "tag_list": ["dingo"],
    "tagged_at": "...",
    "media_type": "image",
    "owner_sub": "...",
    "s3_bucket": "...",
    "s3_key": "uploads/.../...jpg",
    "s3_url": "https://...&X-Amz-Signature=...",       (presigned, 1h)
    "thumbnail_bucket": "...",
    "thumbnail_key": "thumbs/.../...jpg",
    "thumbnail_url": "https://...&X-Amz-Signature=...",  (presigned, 1h)
  }

Response (pending):
  {"file_id": "...", "status": "pending"}

Response (tagger error):
  {"file_id": "...", "status": "tagger_http_500", "error_message": "..."}
"""
import os
import json
import boto3

ddb = boto3.client("dynamodb")
s3 = boto3.client("s3")

TAGGING_RESULTS_TABLE = os.environ["TAGGING_RESULTS_TABLE"]
PRESIGN_EXPIRY = 3600  # 1 hour


def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        },
        "body": json.dumps(body),
    }


def presign(bucket, key):
    """Generate a fresh GET presigned URL. Logged-and-skipped on failure."""
    if not bucket or not key:
        return None
    try:
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=PRESIGN_EXPIRY,
        )
    except Exception as e:
        print(f"WARN: could not presign s3://{bucket}/{key}: {e}")
        return None


def lambda_handler(event, context):
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return _resp(200, {"ok": True})

    file_id = (event.get("pathParameters") or {}).get("file_id", "").strip()
    if not file_id:
        return _resp(400, {"error": "file_id path parameter required"})

    try:
        resp = ddb.get_item(
            TableName=TAGGING_RESULTS_TABLE,
            Key={"file_id": {"S": file_id}},
        )
    except Exception as e:
        return _resp(500, {"error": f"db read failed: {e}"})

    item = resp.get("Item")
    if not item:
        return _resp(200, {"file_id": file_id, "status": "pending"})

    out = {
        "file_id": file_id,
        "status": item.get("status", {}).get("S", "tagged"),
    }

    # Parse the JSON-encoded tag fields
    if "tags" in item:
        try:
            out["tags"] = json.loads(item["tags"]["S"])
        except Exception:
            out["tags"] = {}
    if "tag_list" in item:
        try:
            out["tag_list"] = json.loads(item["tag_list"]["S"])
        except Exception:
            out["tag_list"] = []

    # Plain string fields
    for k in ("tagged_at", "media_type", "owner_sub",
              "s3_bucket", "s3_key", "thumbnail_bucket", "thumbnail_key",
              "error_message"):
        if k in item:
            out[k] = item[k]["S"]

    # Generate fresh presigned URLs (1h) for raw + thumbnail.
    s3_bucket = out.get("s3_bucket")
    s3_key = out.get("s3_key")
    if s3_bucket and s3_key:
        url = presign(s3_bucket, s3_key)
        if url:
            out["s3_url"] = url

    thumb_bucket = out.get("thumbnail_bucket")
    thumb_key = out.get("thumbnail_key")
    if thumb_bucket and thumb_key:
        url = presign(thumb_bucket, thumb_key)
        if url:
            out["thumbnail_url"] = url

    return _resp(200, out)
