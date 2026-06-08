"""Track 1 - Upload Handler Lambda
Returns a presigned PUT URL the UI uses to upload a file directly to S3.
Implements the API endpoint half of rubric 2.1.1.

Flow:
  UI → POST /upload-url with {filename, content_type, owner_sub}
       + Authorization: Bearer <Cognito ID token>
  Lambda generates a file_id (UUID) and s3_key, returns a
  short-lived presigned PUT URL, and stores the user's JWT in a
  small DynamoDB table keyed by file_id (TTL 2 hours).
  UI → PUT (upload_url) with the file bytes.
  S3 ObjectCreated event fires → ingest-trigger Lambda runs, which
  looks up the JWT by file_id and forwards it to Track 3.
"""
import os
import json
import time
import uuid

import boto3

s3 = boto3.client("s3")
ddb = boto3.client("dynamodb")

RAW_BUCKET = os.environ["RAW_BUCKET"]
UPLOAD_TOKENS_TABLE = os.environ.get("UPLOAD_TOKENS_TABLE")
CHECKSUMS_TABLE = os.environ.get("CHECKSUMS_TABLE", "file_checksums")

PUT_EXPIRY_SECONDS = 300        # 5 min for upload
TOKEN_TTL_SECONDS = 2 * 3600    # 2 hours — JWT lives long enough for ingest

ALLOWED_EXTS = {
    "jpg", "jpeg", "png", "webp", "bmp",
    "mp4", "mov", "avi", "mkv", "webm",
}


def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        },
        "body": json.dumps(body),
    }


def extract_bearer(event):
    """Pull the raw JWT out of the Authorization header."""
    headers = event.get("headers") or {}
    # API Gateway HTTP API lowercases header names
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def store_token(file_id, jwt):
    """Stash file_id → jwt in DynamoDB so ingest-trigger can read it later."""
    if not UPLOAD_TOKENS_TABLE or not jwt:
        return
    ddb.put_item(
        TableName=UPLOAD_TOKENS_TABLE,
        Item={
            "file_id": {"S": file_id},
            "jwt": {"S": jwt},
            "expires_at": {"N": str(int(time.time()) + TOKEN_TTL_SECONDS)},
        },
    )


def lambda_handler(event, context):
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return _resp(200, {"ok": True})

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _resp(400, {"error": "Invalid JSON body"})

    filename = body.get("filename", "").strip()
    content_type = body.get("content_type", "application/octet-stream")
    owner_sub = body.get("owner_sub", "anonymous")
    checksum = (body.get("checksum") or "").strip().lower()

    if not filename or "." not in filename:
        return _resp(400, {"error": "Filename with extension required"})

    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTS:
        return _resp(400, {"error": f"Unsupported file type .{ext}"})

    # Pre-upload dedup check: if the client supplied a SHA-256 and we've
    # already seen it, reject before generating a presigned URL.
    if checksum:
        try:
            existing = ddb.get_item(
                TableName=CHECKSUMS_TABLE,
                Key={"checksum": {"S": checksum}},
            )
            if "Item" in existing:
                existing_id = existing["Item"].get("file_id", {}).get("S")
                return _resp(409, {
                    "duplicate": True,
                    "error": "File already exists",
                    "existing_file_id": existing_id,
                })
        except Exception as e:
            print(f"WARN: dedup pre-check failed: {e}")

    file_id = str(uuid.uuid4())
    s3_key = f"uploads/{owner_sub}/{file_id}.{ext}"

    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": RAW_BUCKET,
            "Key": s3_key,
            "ContentType": content_type,
        },
        ExpiresIn=PUT_EXPIRY_SECONDS,
    )

    # Capture the user's JWT so ingest-trigger can forward it to Track 3.
    jwt = extract_bearer(event)
    if jwt:
        try:
            store_token(file_id, jwt)
        except Exception as e:
            print(f"WARN: could not store token for {file_id}: {e}")
    else:
        print(f"WARN: no Authorization header on upload-url request for {file_id}")

    return _resp(200, {
        "upload_url": upload_url,
        "file_id": file_id,
        "s3_bucket": RAW_BUCKET,
        "s3_key": s3_key,
        "expires_in_seconds": PUT_EXPIRY_SECONDS,
    })
