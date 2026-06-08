from notifications import notify_file_tagged

record = {
    "file_id": "test-file-001",
    "owner_sub": "test-user-123",
    "media_type": "image",
    "tags": {
        "eastern gray kangaroo": 2,
        "dingo": 1
    },
    "tag_list": [
        "eastern gray kangaroo",
        "dingo"
    ],
    "s3_bucket": "bucket-name",
    "s3_key": "file-key",
    "thumbnail_bucket": "bucket-name",
    "thumbnail_key": "thumb-key",
    "tagged_at": "2026-06-07T00:00:00Z"
}

response = notify_file_tagged(record)
print(response)
