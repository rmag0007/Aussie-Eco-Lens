import os
from pathlib import Path

from azure.storage.blob import BlobServiceClient


MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/tmp/models"))

MODEL_BLOB_CONNECTION_STRING = os.environ["MODEL_BLOB_CONNECTION_STRING"]
MODEL_BLOB_CONTAINER = os.environ.get("MODEL_BLOB_CONTAINER", "models")

MEGADETECTOR_BLOB_NAME = os.environ.get("MEGADETECTOR_BLOB_NAME", "mdv5a.pt")
SPECIES_MODEL_BLOB_NAME = os.environ.get("SPECIES_MODEL_BLOB_NAME", "model.pt")


def download_blob_if_missing(blob_name: str, local_path: Path) -> str:
    local_path.parent.mkdir(parents=True, exist_ok=True)

    if local_path.exists() and local_path.stat().st_size > 0:
        print(f"Model already exists locally: {local_path}")
        return str(local_path)

    print(f"Downloading model from Blob Storage: {blob_name} -> {local_path}")

    blob_service_client = BlobServiceClient.from_connection_string(
        MODEL_BLOB_CONNECTION_STRING
    )

    blob_client = blob_service_client.get_blob_client(
        container=MODEL_BLOB_CONTAINER,
        blob=blob_name
    )

    with open(local_path, "wb") as model_file:
        model_file.write(blob_client.download_blob().readall())

    print(f"Downloaded model: {local_path}")
    return str(local_path)


def ensure_models_downloaded() -> tuple[str, str]:
    megadetector_path = MODEL_DIR / MEGADETECTOR_BLOB_NAME
    species_model_path = MODEL_DIR / SPECIES_MODEL_BLOB_NAME

    download_blob_if_missing(MEGADETECTOR_BLOB_NAME, megadetector_path)
    download_blob_if_missing(SPECIES_MODEL_BLOB_NAME, species_model_path)

    return str(megadetector_path), str(species_model_path)
