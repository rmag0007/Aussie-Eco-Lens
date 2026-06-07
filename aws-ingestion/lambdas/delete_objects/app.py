"""Track 1 - Delete Objects Lambda
Invoked by Track 4 from the public DELETE /files endpoint.
For each file_id:
  1. Look up the raw s3_key via the file_checksums GSI
  2. Delete the raw object (ecolens-raw)
  3. Delete the thumbnail (ecolens-thumbs)
  4. Delete all frame objects (ecolens-frames/{file_id}/*)
  5. Remove the row from file_checksums DynamoDB table
Idempotent: missing objects count as success.

Rubric line: 2.3.2 — storage cascade (Track 4 owns the DB side).

Input:
{"file_ids": ["uuid1", "uuid2", ...]}

Output:
{
  "deleted": ["uuid1"],
  "failed": [{"file_id": "uuid2", "reason": "..."}]
}
"""
import os
import json
import boto3
from botocore.exceptions import ClientError

s3 = boto3.client("s3")
ddb = boto3.client("dynamodb")

RAW_BUCKET = os.environ["RAW_BUCKET"]
THUMBS_BUCKET = os.environ["THUMBS_BUCKET"]
FRAMES_BUCKET = os.environ["FRAMES_BUCKET"]
CHECKSUMS_TABLE = os.environ["CHECKSUMS_TABLE"]


def query_checksum_row(file_id):
    """Find the checksum row for a given file_id via the by-file-id GSI."""
    resp = ddb.query(
        TableName=CHECKSUMS_TABLE,
        IndexName="by-file-id",
        KeyConditionExpression="file_id = :f",
        ExpressionAttributeValues={":f": {"S": file_id}},
        Limit=1,
    )
    items = resp.get("Items", [])
    if not items:
        return None
    item = items[0]
    return {
        "checksum": item["checksum"]["S"],
        "file_id": item["file_id"]["S"],
        "s3_key": item.get("s3_key", {}).get("S"),
    }


def derive_thumbnail_key(raw_key, file_id):
    """raw_key = uploads/{user_sub}/{file_id}.{ext}
       thumb   = thumbs/{user_sub}/{file_id}.jpg"""
    parts = raw_key.split("/")
    if len(parts) >= 3 and parts[0] == "uploads":
        user_sub = parts[1]
        return f"thumbs/{user_sub}/{file_id}.jpg"
    return None


def delete_object_safe(bucket, key):
    """Delete an S3 object. Treat 'NoSuchKey' as success."""
    try:
        s3.delete_object(Bucket=bucket, Key=key)
        print(f"deleted s3://{bucket}/{key}")
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404"):
            print(f"not found (ok) s3://{bucket}/{key}")
            return True
        print(f"failed to delete s3://{bucket}/{key}: {e}")
        return False


def delete_frames_prefix(file_id):
    """Delete every object under frames/{file_id}/ in a batch."""
    prefix = f"frames/{file_id}/"
    paginator = s3.get_paginator("list_objects_v2")
    deleted_count = 0
    for page in paginator.paginate(Bucket=FRAMES_BUCKET, Prefix=prefix):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if not keys:
            continue
        s3.delete_objects(Bucket=FRAMES_BUCKET, Delete={"Objects": keys})
        deleted_count += len(keys)
        print(f"deleted {len(keys)} frames under {prefix}")
    return deleted_count


def delete_checksum_row(checksum):
    ddb.delete_item(
        TableName=CHECKSUMS_TABLE,
        Key={"checksum": {"S": checksum}},
    )
    print(f"removed checksum row {checksum}")


def delete_one(file_id):
    """Cascade-delete everything tied to file_id. Returns (ok, reason_if_failed)."""
    row = query_checksum_row(file_id)
    if not row:
        # Already gone or never existed: idempotent success
        # but also try a best-effort frame cleanup in case of partial earlier state
        delete_frames_prefix(file_id)
        return True, None

    raw_key = row["s3_key"]
    if raw_key:
        delete_object_safe(RAW_BUCKET, raw_key)
        thumb_key = derive_thumbnail_key(raw_key, file_id)
        if thumb_key:
            delete_object_safe(THUMBS_BUCKET, thumb_key)

    delete_frames_prefix(file_id)
    delete_checksum_row(row["checksum"])
    return True, None


def lambda_handler(event, context):
    print("DELETE EVENT:", json.dumps(event))

    # Allow event to come either as a direct invoke payload OR an API Gateway body
    body = event
    if isinstance(event, dict) and "body" in event and isinstance(event["body"], str):
        try:
            body = json.loads(event["body"])
        except json.JSONDecodeError:
            return {"statusCode": 400, "body": json.dumps({"error": "Invalid JSON"})}

    file_ids = body.get("file_ids") or []
    if not isinstance(file_ids, list) or not file_ids:
        return {"deleted": [], "failed": [], "error": "file_ids required"}

    deleted, failed = [], []
    for fid in file_ids:
        try:
            ok, reason = delete_one(fid)
            if ok:
                deleted.append(fid)
            else:
                failed.append({"file_id": fid, "reason": reason or "unknown"})
        except Exception as e:
            print(f"Error deleting {fid}: {e}")
            failed.append({"file_id": fid, "reason": str(e)})

    result = {"deleted": deleted, "failed": failed}
    print("DELETE RESULT:", json.dumps(result))
    return result
