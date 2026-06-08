"""Track 1 - Ingest Trigger Lambda
Fires when a new object lands in ecolens-raw/uploads/*.
Implements checksum dedup (rubric 2.1.1) and emits the upload-event JSON.
"""
import os, json, hashlib, uuid
import urllib.request
import urllib.error
from datetime import datetime, timezone
from urllib.parse import unquote_plus
import boto3

s3 = boto3.client("s3")
ddb = boto3.client("dynamodb")
lambda_client = boto3.client("lambda")

PRESIGN_EXPIRY_SECONDS = 3600  # 1h — enough time for Track 3 to fetch


def presign(bucket, key, expires=PRESIGN_EXPIRY_SECONDS):
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires,
    )


RAW_BUCKET = os.environ["RAW_BUCKET"]
THUMBS_BUCKET = os.environ["THUMBS_BUCKET"]
FRAMES_BUCKET = os.environ["FRAMES_BUCKET"]
CHECKSUMS_TABLE = os.environ["CHECKSUMS_TABLE"]
THUMBNAIL_FUNCTION_NAME = os.environ.get("THUMBNAIL_FUNCTION_NAME")
VIDEO_FRAMES_FUNCTION_NAME = os.environ.get("VIDEO_FRAMES_FUNCTION_NAME")
TAGGER_URL = os.environ.get("TAGGER_URL")  # Track 3 Azure Function endpoint

IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "bmp"}
VIDEO_EXTS = {"mp4", "mov", "avi", "mkv", "webm"}


def sha256_of_s3_object(bucket, key):
    h = hashlib.sha256()
    body = s3.get_object(Bucket=bucket, Key=key)["Body"]
    for chunk in iter(lambda: body.read(8192), b""):
        h.update(chunk)
    return h.hexdigest()


def checksum_seen(checksum):
    resp = ddb.get_item(
        TableName=CHECKSUMS_TABLE,
        Key={"checksum": {"S": checksum}},
    )
    return "Item" in resp


def record_checksum(checksum, file_id, s3_key):
    ddb.put_item(
        TableName=CHECKSUMS_TABLE,
        Item={
            "checksum": {"S": checksum},
            "file_id": {"S": file_id},
            "s3_key": {"S": s3_key},
        },
    )


def media_type_from_key(key):
    ext = key.rsplit(".", 1)[-1].lower()
    if ext in IMAGE_EXTS: return "image"
    if ext in VIDEO_EXTS: return "video"
    return "unknown"


def parse_user_sub(key):
    parts = key.split("/")
    return parts[1] if len(parts) >= 2 and parts[0] == "uploads" else "unknown"


def invoke_thumbnail(src_bucket, src_key, file_id, owner_sub):
    """Synchronously invoke the thumbnail Lambda. Returns its parsed payload."""
    if not THUMBNAIL_FUNCTION_NAME:
        print("THUMBNAIL_FUNCTION_NAME not configured; skipping thumbnail")
        return None
    payload = {
        "src_bucket": src_bucket,
        "src_key": src_key,
        "file_id": file_id,
        "owner_sub": owner_sub,
    }
    resp = lambda_client.invoke(
        FunctionName=THUMBNAIL_FUNCTION_NAME,
        InvocationType="RequestResponse",   # synchronous
        Payload=json.dumps(payload).encode("utf-8"),
    )
    body = json.loads(resp["Payload"].read())
    if resp.get("FunctionError"):
        print("Thumbnail Lambda error:", body)
        return None
    return body


def deliver_to_tagger(upload_event):
    """POST the upload-event JSON to Track 3's Azure Function.
    Failure is logged but doesn't fail the whole ingest (event is still in CloudWatch).
    """
    if not TAGGER_URL:
        print("TAGGER_URL not configured; skipping delivery")
        return False
    try:
        data = json.dumps(upload_event).encode("utf-8")
        req = urllib.request.Request(
            TAGGER_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(f"Tagger delivery OK ({resp.status}): {resp.read(200)!r}")
            return True
    except urllib.error.HTTPError as e:
        body = e.read(500).decode("utf-8", errors="replace")
        print(f"Tagger delivery FAILED {e.code}: {body}")
        return False
    except Exception as e:
        print(f"Tagger delivery ERROR: {e}")
        return False


def invoke_video_frames(src_bucket, src_key, file_id, owner_sub):
    """Synchronously invoke the video-frames Lambda. Returns its parsed payload."""
    if not VIDEO_FRAMES_FUNCTION_NAME:
        print("VIDEO_FRAMES_FUNCTION_NAME not configured; skipping frames")
        return None
    payload = {
        "src_bucket": src_bucket,
        "src_key": src_key,
        "file_id": file_id,
        "owner_sub": owner_sub,
    }
    resp = lambda_client.invoke(
        FunctionName=VIDEO_FRAMES_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    body = json.loads(resp["Payload"].read())
    if resp.get("FunctionError"):
        print("VideoFrames Lambda error:", body)
        return None
    return body


def lambda_handler(event, context):
    print("RAW EVENT:", json.dumps(event))
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])

        if not key.startswith("uploads/"):
            print(f"Skipping non-upload key: {key}")
            continue

        media_type = media_type_from_key(key)
        if media_type == "unknown":
            print(f"Unsupported extension: {key}")
            continue

        checksum = sha256_of_s3_object(bucket, key)
        print(f"Checksum for {key}: {checksum}")

        if checksum_seen(checksum):
            print(f"DUPLICATE: {key} (checksum={checksum}). Deleting.")
            s3.delete_object(Bucket=bucket, Key=key)
            continue

        file_id = str(uuid.uuid4())
        owner_sub = parse_user_sub(key)
        record_checksum(checksum, file_id, key)

        # Generate thumbnail for images (rubric 2.1.2)
        thumbnail_key = None
        thumbnail_url = None
        if media_type == "image":
            thumb_result = invoke_thumbnail(bucket, key, file_id, owner_sub)
            if thumb_result and thumb_result.get("thumbnail_key"):
                thumbnail_key = thumb_result["thumbnail_key"]
                thumbnail_url = presign(THUMBS_BUCKET, thumbnail_key)

        # Extract frames at 1 fps for videos (rubric 2.1.2)
        frames = []
        if media_type == "video":
            frames_result = invoke_video_frames(bucket, key, file_id, owner_sub)
            if frames_result and frames_result.get("frames"):
                for f in frames_result["frames"]:
                    frames.append({
                        "second": f["second"],
                        "s3_bucket": f["s3_bucket"],
                        "s3_key": f["s3_key"],
                        "s3_url": presign(f["s3_bucket"], f["s3_key"]),
                    })
                # Use the first frame as a poster/thumbnail for the video
                if frames:
                    thumbnail_key = frames[0]["s3_key"]
                    thumbnail_url = frames[0]["s3_url"]

        upload_event = {
            "file_id": file_id,
            "owner_sub": owner_sub,
            "s3_bucket": bucket,
            "s3_key": key,
            "s3_url": presign(bucket, key),
            "thumbnail_bucket": THUMBS_BUCKET if media_type == "image" else FRAMES_BUCKET,
            "thumbnail_key": thumbnail_key,
            "thumbnail_url": thumbnail_url,
            "media_type": media_type,
            "checksum_sha256": checksum,
            "frames": frames,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        print("UPLOAD_EVENT:", json.dumps(upload_event))

        # Deliver to Track 3 tagger (Azure Function)
        deliver_to_tagger(upload_event)

    return {"statusCode": 200, "body": "ok"}
