"""
ML Inference for Track 4 — Query by File
Replicates the exact pipeline from batch.py:
  1. MegaDetector (mdv5a.pt) detects animals + bounding boxes
  2. Crop each detected animal
  3. Classifier (model.pt) identifies species from crops
  4. Return dict of {common_name: count}

Drop this file next to lambdas.py and import from it.
"""

import os
import io
import json
import logging
import tempfile
import boto3
import torch
import torchvision.transforms as transforms
import numpy as np
from PIL import Image

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ─────────────────────────────────────────────────────────────
# Class labels — scientific name → common name mapping
# Order matches model.pt output indices (from batch.py + labels.txt)
# ─────────────────────────────────────────────────────────────

SCIENTIFIC_NAMES = [
    'Alectura_lathami', 'Antechinus_agilis', 'Bos_taurus',
    'Burhinus_grallarius', 'Canis_familiaris', 'Chalcophaps_longirostris',
    'Colluricincla_harmonica', 'Corcorax_melanorhamphos', 'Dacelo_novaeguineae',
    'Dama_dama', 'Eopsaltria_australis', 'Felis_catus',
    'Geopelia_humeralis', 'Gymnorhina_tibicen', 'Homo_sapiens',
    'Isoodon_macrourus', 'Lepus_europaeus', 'Macropus_giganteus',
    'Menura_novaehollandiae', 'Mus_musculus', 'Oryctolagus_cuniculus',
    'Perameles_nasuta', 'Pitta_versicolor', 'Rattus',
    'Rattus_fuscipes', 'Rattus_rattus', 'Strepera_graculina',
    'Sus_scrofa', 'Tachyglossus_aculeatus', 'Thylogale_stigmatica',
    'Trichosurus_caninus', 'Trichosurus_cunninghami', 'Trichosurus_vulpecula',
    'Varanus_varius', 'Vombatus_ursinus', 'Vulpes_vulpes',
    'Wallabia_bicolor', 'Canis_dingo', 'Capra_hircus',
    'Casuarius_casuarius', 'Heteromyias_cinereifrons', 'Hypsiprymnodon_moschatus',
    'Megapodius_reinwardt', 'Notamacropus_rufogriseus', 'Orthonyx_spaldingii',
    'Uromys_caudimaculatus'
]

COMMON_NAMES = [
    'australian brushturkey', 'agile antechinus', 'cattle',
    'bush thick-knee', 'dingo', 'pacific emerald dove',
    'grey shrikethrush', 'white-winged chough', 'laughing kookaburra',
    'fallow deer', 'eastern yellow robin', 'domestic cat',
    'bar-shouldered dove', 'australian magpie', 'human',
    'northern brown bandicoot', 'european hare', 'eastern gray kangaroo',
    'superb lyrebird', 'house mouse', 'european rabbit',
    'long-nosed bandicoot', 'noisy pitta', 'rattus',
    'australian bush rat', 'black rat', 'pied currawong',
    'wild boar', 'australian echidna', 'red-legged pademelon',
    'short-eared possum', 'mountain brushtail opossum', 'common brushtail',
    'lace monitor', 'common wombat', 'red fox',
    'swamp wallaby', 'dingo', 'domestic goat',
    'southern cassowary', 'grey-headed robin', 'musky rat kangaroo',
    'orange-footed scrubfowl', 'red-necked wallaby', 'northern chowchilla',
    'giant white-tailed rat'
]

# Detection settings (from config.yaml)
CONF_THRESH = 0.05   # minimum MegaDetector confidence to accept a crop
SNIP_SIZE   = 600    # crop resize before classifier

# Classifier settings (from batch.py)
CLASSIFIER_INPUT_SIZE = 480
CLASSIFIER_CONF_THRESH = 0.5  # minimum species confidence to count as detected

# ─────────────────────────────────────────────────────────────
# Model cache — downloaded once per Lambda container lifetime
# ─────────────────────────────────────────────────────────────

DETECTOR_LOCAL   = "/tmp/mdv5a.pt"
CLASSIFIER_LOCAL = "/tmp/model.pt"

_detector   = None
_classifier = None
DEVICE      = "cpu"  # Lambda has no GPU


def _download_if_missing(s3_bucket: str, s3_key: str, local_path: str):
    if not os.path.exists(local_path):
        logger.info(f"Downloading s3://{s3_bucket}/{s3_key} → {local_path}")
        boto3.client("s3").download_file(s3_bucket, s3_key, local_path)
        logger.info("Download complete.")


def load_detector():
    global _detector
    if _detector is not None:
        return _detector
    _download_if_missing(
        os.environ["MODEL_BUCKET"],
        os.environ["DETECTOR_KEY"],   # e.g. models/mdv5a.pt
        DETECTOR_LOCAL,
    )
    # MegaDetector is loaded via the megadetector library — we don't torch.load it directly
    # It is invoked via run_detector_batch (see run_megadetector below)
    _detector = True  # sentinel — actual model loaded by megadetector library
    return _detector


def load_classifier():
    global _classifier
    if _classifier is not None:
        return _classifier
    _download_if_missing(
        os.environ["MODEL_BUCKET"],
        os.environ["CLASSIFIER_KEY"],  # e.g. models/model.pt
        CLASSIFIER_LOCAL,
    )
    model = torch.load(CLASSIFIER_LOCAL, map_location=DEVICE, weights_only=False)
    model.eval()
    model.to(DEVICE)
    _classifier = model
    logger.info("Classifier loaded.")
    return _classifier


# ─────────────────────────────────────────────────────────────
# Step 1 — Run MegaDetector on an image file path
# Returns list of detections: [{bbox, conf, category}, ...]
# ─────────────────────────────────────────────────────────────

def run_megadetector(image_path: str) -> list:
    """
    Runs MegaDetector on a single image.
    Returns raw detections list from MegaDetector.
    """
    from megadetector.detection import run_detector_batch
    load_detector()
    results = run_detector_batch.load_and_run_detector_batch(
        image_file_names=[image_path],
        model_file=DETECTOR_LOCAL,
    )
    if not results:
        return []
    return results[0].get("detections", [])


# ─────────────────────────────────────────────────────────────
# Step 2 — Crop detected animals from image
# Returns list of PIL Image crops
# ─────────────────────────────────────────────────────────────

def crop_detections(image_path: str, detections: list) -> list:
    crops = []
    img = Image.open(image_path).convert("RGB")
    W, H = img.size

    for detection in detections:
        # Only process animal detections (category "1")
        if detection.get("category") != "1":
            continue
        if detection.get("conf", 0) < CONF_THRESH:
            continue

        x, y, w, h = detection["bbox"]
        left   = int(x * W)
        top    = int(y * H)
        right  = int((x + w) * W)
        bottom = int((y + h) * H)

        crop = img.crop((left, top, right, bottom))
        resized = crop.resize((SNIP_SIZE, SNIP_SIZE), Image.BILINEAR)
        crops.append(resized)

    return crops


# ─────────────────────────────────────────────────────────────
# Step 3 — Classify a single cropped PIL image
# Returns common name of top species if confidence >= threshold
# ─────────────────────────────────────────────────────────────

transform = transforms.Compose([
    transforms.Resize((CLASSIFIER_INPUT_SIZE, CLASSIFIER_INPUT_SIZE)),
    transforms.ToTensor(),
])

def classify_crop(crop: Image.Image) -> str | None:
    """
    Runs the species classifier on a single cropped image.
    Returns the common name of the top prediction, or None if below threshold.
    """
    classifier = load_classifier()

    img_tensor = transform(crop)           # C,H,W
    img_tensor = img_tensor.unsqueeze(0)   # B,C,H,W
    img_tensor = img_tensor.permute(0, 2, 3, 1)  # B,H,W,C  ← required by this model
    img_tensor = img_tensor.to(DEVICE)

    with torch.no_grad():
        logits = classifier(img_tensor)

    probs = torch.softmax(logits, dim=1)[0].cpu().numpy()
    best_idx = int(np.argmax(probs))
    best_conf = float(probs[best_idx])

    logger.info(f"Top prediction: {COMMON_NAMES[best_idx]} ({best_conf:.3f})")

    if best_conf < CLASSIFIER_CONF_THRESH:
        return None  # not confident enough

    return COMMON_NAMES[best_idx]


# ─────────────────────────────────────────────────────────────
# Main entry point — called from lambdas.py
# ─────────────────────────────────────────────────────────────

def run_ml_model_on_file(file_bytes: bytes, file_type: str) -> dict:
    """
    Full pipeline: MegaDetector → crop → classify.
    Returns dict of {common_name: count} e.g. {"eastern gray kangaroo": 2}
    File is processed from memory via /tmp — never written to S3.
    """
    # Write bytes to /tmp so MegaDetector and PIL can read it
    suffix = ".mp4" if file_type == "video" else ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir="/tmp") as f:
        f.write(file_bytes)
        tmp_path = f.name

    try:
        if file_type == "video":
            image_paths = extract_frames(tmp_path)
        else:
            image_paths = [tmp_path]

        tag_counts = {}

        for image_path in image_paths:
            detections = run_megadetector(image_path)
            crops = crop_detections(image_path, detections)

            for crop in crops:
                species = classify_crop(crop)
                if species:
                    tag_counts[species] = tag_counts.get(species, 0) + 1

            # Clean up frame files (not the original)
            if image_path != tmp_path:
                os.remove(image_path)

        return tag_counts

    finally:
        # Always clean up the original temp file
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# ─────────────────────────────────────────────────────────────
# Video frame extraction — 1 frame per second
# ─────────────────────────────────────────────────────────────

def extract_frames(video_path: str) -> list:
    """
    Extracts 1 frame per second from a video.
    Returns list of file paths to extracted frame images in /tmp.
    """
    import cv2
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 1
    frame_interval = max(1, int(fps))

    frame_paths = []
    frame_index = 0
    saved_index = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        if frame_index % frame_interval == 0:
            frame_path = f"/tmp/frame_{saved_index:04d}.jpg"
            import cv2
            cv2.imwrite(frame_path, frame)
            frame_paths.append(frame_path)
            saved_index += 1
        frame_index += 1

    cap.release()
    logger.info(f"Extracted {len(frame_paths)} frames from video.")
    return frame_paths
