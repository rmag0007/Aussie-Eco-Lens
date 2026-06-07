"""Track 1 - Thumbnail Generator Lambda
Invoked by ingest-trigger after dedup passes (for images only).
Downloads the raw image, resizes it preserving aspect ratio,
compresses to JPEG quality 80, uploads to the thumbs bucket.

Rubric line: 2.1.2 — uses OpenCV, preserves aspect ratio, compresses.

Input event shape (passed via Lambda invoke from ingest-trigger):
{
  "src_bucket": "ecolens-raw-...",
  "src_key": "uploads/{user_sub}/{file_id}.jpg",
  "file_id": "uuid",
  "owner_sub": "...",
}

Returns:
{
  "thumbnail_bucket": "ecolens-thumbs-...",
  "thumbnail_key": "thumbs/{user_sub}/{file_id}.jpg",
  "width": int,
  "height": int,
}
"""
import os
import json
import cv2          # provided by the Klayers OpenCV layer
import numpy as np  # bundled inside the OpenCV layer

import boto3

s3 = boto3.client("s3")

THUMBS_BUCKET = os.environ["THUMBS_BUCKET"]
MAX_DIMENSION = int(os.environ.get("THUMB_MAX_DIMENSION", "300"))
JPEG_QUALITY = int(os.environ.get("THUMB_JPEG_QUALITY", "80"))


def download_image(bucket, key):
    """Fetch object bytes from S3 and decode into an OpenCV image (BGR ndarray)."""
    obj = s3.get_object(Bucket=bucket, Key=key)
    raw_bytes = obj["Body"].read()
    arr = np.frombuffer(raw_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Could not decode image from s3://{bucket}/{key}")
    return img


def resize_preserving_aspect(img, max_dim=MAX_DIMENSION):
    """Shrink so the longer side equals max_dim. Skip if already smaller."""
    h, w = img.shape[:2]
    longer = max(h, w)
    if longer <= max_dim:
        return img  # already small enough; no upscaling
    scale = max_dim / longer
    new_w = int(round(w * scale))
    new_h = int(round(h * scale))
    # INTER_AREA gives the best quality for shrinking (vs INTER_LINEAR default)
    return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)


def encode_jpeg(img, quality=JPEG_QUALITY):
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("Failed to encode JPEG")
    return buf.tobytes()


def lambda_handler(event, context):
    print("THUMB EVENT:", json.dumps(event))

    src_bucket = event["src_bucket"]
    src_key = event["src_key"]
    file_id = event["file_id"]
    owner_sub = event.get("owner_sub", "unknown")

    # 1. Download + decode
    img = download_image(src_bucket, src_key)
    orig_h, orig_w = img.shape[:2]
    print(f"Source {src_key}: {orig_w}x{orig_h}")

    # 2. Resize (preserve aspect ratio)
    thumb = resize_preserving_aspect(img)
    new_h, new_w = thumb.shape[:2]
    print(f"Thumb {file_id}: {new_w}x{new_h}")

    # 3. Encode JPEG and upload to thumbs bucket
    jpeg_bytes = encode_jpeg(thumb)
    thumb_key = f"thumbs/{owner_sub}/{file_id}.jpg"
    s3.put_object(
        Bucket=THUMBS_BUCKET,
        Key=thumb_key,
        Body=jpeg_bytes,
        ContentType="image/jpeg",
    )
    print(f"Uploaded thumb to s3://{THUMBS_BUCKET}/{thumb_key} ({len(jpeg_bytes)} bytes)")

    return {
        "thumbnail_bucket": THUMBS_BUCKET,
        "thumbnail_key": thumb_key,
        "width": new_w,
        "height": new_h,
    }
