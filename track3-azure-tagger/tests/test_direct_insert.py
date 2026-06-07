from datetime import datetime, timezone

from database.cosmos_db import save_file_record
from tagging.pipeline import tag_media_file

event = {
    "file_id": "direct-test-img-001",
    "owner_sub": "test-user-123",
    "s3_bucket": "ecolens-raw",
    "s3_key": "uploads/test-user-123/direct-test-img-001.jpg",
    "s3_url": "https://ecolens-raw.s3.amazonaws.com/uploads/test-user-123/direct-test-img-001.jpg",
    "thumbnail_bucket": "ecolens-thumbs",
    "thumbnail_key": "thumbs/test-user-123/direct-test-img-001.jpg",
    "thumbnail_url": "https://ecolens-thumbs.s3.amazonaws.com/thumbs/test-user-123/direct-test-img-001.jpg",
    "media_type": "image",
    "checksum_sha256": "directfakechecksum",
    "frames": [],
    "uploaded_at": "2026-06-04T10:30:00Z"
}

tags = tag_media_file(
    media_type=event["media_type"],
    s3_url=event["s3_url"],
    frames=event["frames"]
)

now = datetime.now(timezone.utc).isoformat()

record = {
    "id": event["file_id"],
    "file_id": event["file_id"],
    "owner_sub": event["owner_sub"],
    "owner_email": "test@example.com",
    "media_type": event["media_type"],
    "checksum_sha256": event["checksum_sha256"],
    "s3_bucket": event["s3_bucket"],
    "s3_key": event["s3_key"],
    "s3_url": event["s3_url"],
    "thumbnail_bucket": event["thumbnail_bucket"],
    "thumbnail_key": event["thumbnail_key"],
    "thumbnail_url": event["thumbnail_url"],
    "frames": event["frames"],
    "tags": tags,
    "tag_list": list(tags.keys()),
    "status": "tagged",
    "uploaded_at": event["uploaded_at"],
    "tagged_at": now,
    "updated_at": now
}

save_file_record(record)

print("Inserted direct test record:", event["file_id"])
