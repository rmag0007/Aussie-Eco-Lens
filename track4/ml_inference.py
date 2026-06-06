"""
ML Inference for Track 4 — Query by File
All heavy imports (torch, torchvision, numpy, PIL, cv2) are lazy —
loaded only when /query/file is actually called.
This lets all other endpoints work without torch installed.
"""

import os
import io
import logging
import tempfile
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ─── Constants ───────────────────────────────────────────────
DETECTOR_LOCAL   = "/tmp/mdv5a.pt"
CLASSIFIER_LOCAL = "/tmp/model.pt"
CONF_THRESH      = 0.05
SNIP_SIZE        = 600
CLASSIFIER_INPUT = 480
CLASSIFIER_CONF  = 0.5
DEVICE           = "cpu"

SCIENTIFIC_NAMES = [
    'Alectura_lathami','Antechinus_agilis','Bos_taurus','Burhinus_grallarius',
    'Canis_familiaris','Chalcophaps_longirostris','Colluricincla_harmonica',
    'Corcorax_melanorhamphos','Dacelo_novaeguineae','Dama_dama',
    'Eopsaltria_australis','Felis_catus','Geopelia_humeralis','Gymnorhina_tibicen',
    'Homo_sapiens','Isoodon_macrourus','Lepus_europaeus','Macropus_giganteus',
    'Menura_novaehollandiae','Mus_musculus','Oryctolagus_cuniculus',
    'Perameles_nasuta','Pitta_versicolor','Rattus','Rattus_fuscipes',
    'Rattus_rattus','Strepera_graculina','Sus_scrofa','Tachyglossus_aculeatus',
    'Thylogale_stigmatica','Trichosurus_caninus','Trichosurus_cunninghami',
    'Trichosurus_vulpecula','Varanus_varius','Vombatus_ursinus','Vulpes_vulpes',
    'Wallabia_bicolor','Canis_dingo','Capra_hircus','Casuarius_casuarius',
    'Heteromyias_cinereifrons','Hypsiprymnodon_moschatus','Megapodius_reinwardt',
    'Notamacropus_rufogriseus','Orthonyx_spaldingii','Uromys_caudimaculatus'
]

COMMON_NAMES = [
    'australian brushturkey','agile antechinus','cattle','bush thick-knee',
    'dingo','pacific emerald dove','grey shrikethrush','white-winged chough',
    'laughing kookaburra','fallow deer','eastern yellow robin','domestic cat',
    'bar-shouldered dove','australian magpie','human','northern brown bandicoot',
    'european hare','eastern gray kangaroo','superb lyrebird','house mouse',
    'european rabbit','long-nosed bandicoot','noisy pitta','rattus',
    'australian bush rat','black rat','pied currawong','wild boar',
    'australian echidna','red-legged pademelon','short-eared possum',
    'mountain brushtail opossum','common brushtail','lace monitor',
    'common wombat','red fox','swamp wallaby','dingo','domestic goat',
    'southern cassowary','grey-headed robin','musky rat kangaroo',
    'orange-footed scrubfowl','red-necked wallaby','northern chowchilla',
    'giant white-tailed rat'
]

# ─── Model cache ─────────────────────────────────────────────
_classifier = None

def _download_if_missing(bucket, key, local_path):
    if not os.path.exists(local_path):
        logger.info(f"Downloading s3://{bucket}/{key} → {local_path}")
        boto3.client("s3").download_file(bucket, key, local_path)

def load_classifier():
    global _classifier
    if _classifier is not None:
        return _classifier
    import torch
    _download_if_missing(
        os.environ["MODEL_BUCKET"],
        os.environ["CLASSIFIER_KEY"],
        CLASSIFIER_LOCAL,
    )
    model = torch.load(CLASSIFIER_LOCAL, map_location=DEVICE, weights_only=False)
    model.eval()
    _classifier = model
    logger.info("Classifier loaded.")
    return _classifier

# ─── MegaDetector ────────────────────────────────────────────

def run_megadetector(image_path):
    from megadetector.detection import run_detector_batch
    _download_if_missing(
        os.environ["MODEL_BUCKET"],
        os.environ["DETECTOR_KEY"],
        DETECTOR_LOCAL,
    )
    results = run_detector_batch.load_and_run_detector_batch(
        image_file_names=[image_path],
        model_file=DETECTOR_LOCAL,
    )
    if not results:
        return []
    return results[0].get("detections", [])

# ─── Crop detections ─────────────────────────────────────────

def crop_detections(image_path, detections):
    from PIL import Image as PILImage
    crops = []
    img = PILImage.open(image_path).convert("RGB")
    W, H = img.size
    for det in detections:
        if det.get("category") != "1":
            continue
        if det.get("conf", 0) < CONF_THRESH:
            continue
        x, y, w, h = det["bbox"]
        crop = img.crop((int(x*W), int(y*H), int((x+w)*W), int((y+h)*H)))
        crops.append(crop.resize((SNIP_SIZE, SNIP_SIZE), PILImage.BILINEAR))
    return crops

# ─── Classify one crop ───────────────────────────────────────

def classify_crop(crop):
    import torch
    import torchvision.transforms as transforms
    import numpy as np

    transform = transforms.Compose([
        transforms.Resize((CLASSIFIER_INPUT, CLASSIFIER_INPUT)),
        transforms.ToTensor(),
    ])

    classifier = load_classifier()
    t = transform(crop).unsqueeze(0).permute(0, 2, 3, 1).to(DEVICE)

    with torch.no_grad():
        logits = classifier(t)

    probs = torch.softmax(logits, dim=1)[0].cpu().numpy()
    best_idx = int(np.argmax(probs))
    best_conf = float(probs[best_idx])

    logger.info(f"Top: {COMMON_NAMES[best_idx]} ({best_conf:.3f})")

    if best_conf < CLASSIFIER_CONF:
        return None
    return COMMON_NAMES[best_idx]

# ─── Video frame extraction ──────────────────────────────────

def extract_frames(video_path):
    import cv2
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 1
    interval = max(1, int(fps))
    paths = []
    idx = saved = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        if idx % interval == 0:
            p = f"/tmp/frame_{saved:04d}.jpg"
            cv2.imwrite(p, frame)
            paths.append(p)
            saved += 1
        idx += 1
    cap.release()
    return paths

# ─── Main entry point ────────────────────────────────────────

def run_ml_model_on_file(file_bytes: bytes, file_type: str) -> dict:
    suffix = ".mp4" if file_type == "video" else ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir="/tmp") as f:
        f.write(file_bytes)
        tmp_path = f.name

    try:
        image_paths = extract_frames(tmp_path) if file_type == "video" else [tmp_path]
        tag_counts = {}

        for image_path in image_paths:
            detections = run_megadetector(image_path)
            for crop in crop_detections(image_path, detections):
                species = classify_crop(crop)
                if species:
                    tag_counts[species] = tag_counts.get(species, 0) + 1
            if image_path != tmp_path:
                os.remove(image_path)

        return tag_counts
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)