# Upload Event Contract (Track 1 → Track 3)

When a new file lands in `ecolens-raw`, Track 1's `ingest-trigger` Lambda
emits this JSON. Track 3's tagging function consumes it.

## Access note (private buckets)
All S3 buckets are private (`BlockPublicAccess: true`). To let Track 3's Azure
Function read objects without AWS credentials, `s3_url` (and each `frames[].s3_url`
once video extraction is added) is a **presigned GET URL valid for 1 hour**.

Track 3 does a plain HTTPS GET:
```python
resp = requests.get(s3_url, timeout=30)
img_bytes = resp.content
```

For long-term DB storage, persist `s3_bucket + s3_key` (not the presigned URL,
which expires). Track 4 generates fresh presigned URLs on demand when serving
query responses.

## Schema
```json
{
  "file_id": "uuid-v4",
  "owner_sub": "cognito-user-sub",
  "s3_bucket": "ecolens-raw",
  "s3_key": "uploads/{user_sub}/{file_id}.jpg",
  "s3_url": "https://ecolens-raw.s3.amazonaws.com/...",
  "thumbnail_bucket": "ecolens-thumbs",
  "thumbnail_key": "thumbs/{user_sub}/{file_id}.jpg",
  "thumbnail_url": "https://ecolens-thumbs.s3.amazonaws.com/...",
  "media_type": "image",
  "checksum_sha256": "a3f9...",
  "frames": [],
  "uploaded_at": "2026-06-04T10:30:00Z"
}
```

For videos:
- `media_type` = `"video"`
- `thumbnail_url` = `null`
- `frames` = array of `{"second": 0, "s3_key": "frames/..."}` per extracted frame

## Delivery
TBD — initially logged to CloudWatch. Final method (HTTP POST vs. SNS topic
vs. EventBridge) to be agreed by week 2 with Track 3.

## Duplicates
If the file is a duplicate (checksum match), NO event is emitted.
The S3 object is deleted from `ecolens-raw`.
