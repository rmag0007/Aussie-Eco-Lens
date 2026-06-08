import os
import requests


TRACK4_NOTIFY_ENDPOINT = os.environ.get(
    "TRACK4_NOTIFY_ENDPOINT",
    "https://pjt56rikpk.execute-api.ap-southeast-2.amazonaws.com/prod/notifications/notify"
)


def notify_file_tagged(record: dict) -> dict:
    """
    Notify Track 4 after a file has been tagged and saved to Cosmos DB.
    Track 4 handles subscriptions and email/SNS delivery.
    """

    payload = {
        "event_type": "file_tagged",
        "file_id": record["file_id"],
        "owner_sub": record["owner_sub"],
        "media_type": record["media_type"],
        "tags": record["tags"],
        "tag_list": record["tag_list"],
        "s3_bucket": record.get("s3_bucket"),
        "s3_key": record.get("s3_key"),
        "thumbnail_bucket": record.get("thumbnail_bucket"),
        "thumbnail_key": record.get("thumbnail_key"),
        "tagged_at": record.get("tagged_at")
    }

    try:
        response = requests.post(
            TRACK4_NOTIFY_ENDPOINT,
            json=payload,
            headers={
                "Content-Type": "application/json"
            },
            timeout=10
        )

        response.raise_for_status()

        try:
            return response.json()
        except Exception:
            return {
                "message": "Notification request sent",
                "raw_response": response.text
            }

    except requests.RequestException as e:
        return {
            "message": "Notification request failed",
            "error": str(e)
        }
