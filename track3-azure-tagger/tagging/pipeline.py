def tag_media_file(media_type: str, s3_url: str, frames: list) -> dict:
    """
    Temporary fake tagger.
    Replace later with MegaDetector + SpeciesNet.
    """

    if media_type == "image":
        return {
            "kangaroo": 2
        }

    if media_type == "video":
        return {
            "wombat": 1,
            "kangaroo": 2
        }

    return {}
