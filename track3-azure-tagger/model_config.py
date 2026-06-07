import os

MEGADETECTOR_MODEL_PATH = os.environ.get(
    "MEGADETECTOR_MODEL_PATH",
    "models/mdv5a.pt"
)

SPECIES_MODEL_PATH = os.environ.get(
    "SPECIES_MODEL_PATH",
    "models/model.pt"
)

MODEL_VERSION = os.environ.get(
    "MODEL_VERSION",
    "speciesnet-v1"
)

LOWER_CONF = float(os.environ.get("LOWER_CONF", "0.05"))
SNIP_SIZE = int(os.environ.get("SNIP_SIZE", "600"))
