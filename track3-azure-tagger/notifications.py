import os
import requests


TRACK4_NOTIFY_ENDPOINT = os.environ.get("TRACK4_NOTIFY_ENDPOINT", "")


def notify_file_tagged(record: dict) -> dict:
    """
    Calls Track 4's notify endpoint after Track 3 tags a file.

    If TRACK4_NOTIFY_ENDPOINT is not set, notification is skipped.
    This allows local testing without Track 4 being ready.
    """

    if not TRACK4_NOTIFY_ENDPOINT:
        print("TRACK4_NOTIFY_ENDPOINT not set. Skipping notification.")
        return {
            "status": "skipped",
            "reason": "TRACK4_NOTIFY_ENDPOINT not configured"
        }

    payload = {
        "event_type": "file_tagged",
        "file_id": record["file_id"],
        "owner_sub": record["owner_sub"],
        "owner_email": record.get("owner_email"),
        "media_type": record["media_type"],
        "tags": record["tags"],
        "tag_list": record["tag_list"],
        "s3_bucket": record.get("s3_bucket"),
        "s3_key": record.get("s3_key"),
        "thumbnail_bucket": record.get("thumbnail_bucket"),
        "thumbnail_key": record.get("thumbnail_key"),
        "tagged_at": record.get("tagged_at")
    }

    response = requests.post(
        TRACK4_NOTIFY_ENDPOINT,
        json=payload,
        timeout=10
    )

    response.raise_for_status()

    try:
        return response.json()
    except Exception:
        return {
            "status": "sent",
            "raw_response": response.text
        }
