REQUIRED_UPLOAD_FIELDS = [
    "file_id",
    "owner_sub",
    "s3_bucket",
    "s3_key",
    "s3_url",
    "media_type",
    "checksum_sha256"
]


def validate_upload_event(event: dict) -> None:
    missing = [field for field in REQUIRED_UPLOAD_FIELDS if field not in event]

    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    if event["media_type"] not in ["image", "video"]:
        raise ValueError("media_type must be either 'image' or 'video'")

    if event["media_type"] == "image":
        if not event.get("thumbnail_url"):
            raise ValueError("Image events must include thumbnail_url")

    if event["media_type"] == "video":
        if "frames" not in event:
            raise ValueError("Video events must include frames array")
