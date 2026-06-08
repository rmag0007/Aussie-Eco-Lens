from tagging.download import download_presigned_url
from tagging.real_pipeline import tag_local_image


def tag_media_file(media_type: str, s3_url: str, frames: list) -> dict:
    """
    Track 3 tagging pipeline:
    - downloads image/frame using presigned S3 URL
    - runs SpeciesNet model
    - returns species tag counts

    Current mode:
    - MegaDetector is optional.
    - If MegaDetector is unavailable, the full image is classified.
    """

    if media_type == "image":
        local_path = download_presigned_url(
            url=s3_url,
            output_path="/tmp/current_image.jpg"
        )

        return tag_local_image(local_path)

    if media_type == "video":
        combined_tags = {}

        for frame in frames:
            frame_url = frame.get("s3_url")
            if not frame_url:
                continue

            second = frame.get("second", "unknown")

            local_path = download_presigned_url(
                url=frame_url,
                output_path=f"/tmp/frame_{second}.jpg"
            )

            frame_tags = tag_local_image(local_path)

            for tag, count in frame_tags.items():
                combined_tags[tag] = combined_tags.get(tag, 0) + count

        return combined_tags

    return {}
