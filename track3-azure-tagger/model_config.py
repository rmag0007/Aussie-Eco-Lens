import os

MEGADETECTOR_MODEL_PATH = os.environ.get("MEGADETECTOR_MODEL_PATH", "./models/mdv5a.pt")
SPECIES_MODEL_PATH = os.environ.get("SPECIES_MODEL_PATH", "./models/model.pt")
MODEL_VERSION = os.environ.get("MODEL_VERSION", "speciesnet-v1")
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.5"))
