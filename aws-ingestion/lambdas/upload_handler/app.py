"""Track 1 - Upload Handler Lambda
Returns a presigned PUT URL the UI uses to upload a file directly to S3.
Implements the API endpoint half of rubric 2.1.1.

Flow:
  UI → POST /upload-url with {filename, content_type, owner_sub?}
  Lambda generates a file_id (UUID) and s3_key, then returns a
  short-lived presigned PUT URL.
  UI → PUT (upload_url) with the file bytes.
  S3 ObjectCreated event fires → ingest-trigger Lambda runs.
"""
import os
import json
import uuid
from urllib.parse import unquote_plus

import boto3

s3 = boto3.client("s3")

RAW_BUCKET = os.environ["RAW_BUCKET"]
PUT_EXPIRY_SECONDS = 300  # 5 minutes is plenty for a single upload

# Whitelist allowed file types so people can't dump random files in the bucket.
ALLOWED_EXTS = {
    "jpg", "jpeg", "png", "webp", "bmp",
    "mp4", "mov", "avi", "mkv", "webm",
}


def _resp(status, body):
    """Wrap any payload in API-Gateway-shaped response with CORS headers."""
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            # CORS so browser-based UIs can hit this from another origin
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        },
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    # Handle CORS preflight (browsers send OPTIONS before POST)
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return _resp(200, {"ok": True})

    # Parse JSON body
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _resp(400, {"error": "Invalid JSON body"})

    filename = body.get("filename", "").strip()
    content_type = body.get("content_type", "application/octet-stream")
    # owner_sub will come from the Cognito JWT once Track 2 wires authoriser.
    # For now, accept it from the body so we can test without auth.
    owner_sub = body.get("owner_sub", "anonymous")

    if not filename or "." not in filename:
        return _resp(400, {"error": "Filename with extension required"})

    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTS:
        return _resp(400, {"error": f"Unsupported file type .{ext}"})

    # Generate IDs and the destination key
    file_id = str(uuid.uuid4())
    s3_key = f"uploads/{owner_sub}/{file_id}.{ext}"

    # Presign a PUT URL for the exact key + content type
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": RAW_BUCKET,
            "Key": s3_key,
            "ContentType": content_type,
        },
        ExpiresIn=PUT_EXPIRY_SECONDS,
    )

    return _resp(200, {
        "upload_url": upload_url,
        "file_id": file_id,
        "s3_bucket": RAW_BUCKET,
        "s3_key": s3_key,
        "expires_in_seconds": PUT_EXPIRY_SECONDS,
    })
