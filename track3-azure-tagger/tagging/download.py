from pathlib import Path
import requests


def download_presigned_url(url: str, output_path: str, timeout: int = 30) -> str:
    """
    Downloads an image/video frame from a presigned S3 URL.
    No AWS credentials needed.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    response = requests.get(url, timeout=timeout)
    response.raise_for_status()

    output.write_bytes(response.content)
    return str(output)
