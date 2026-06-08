from pathlib import Path
from collections import Counter
from model_loader import ensure_models_downloaded
from PIL import Image
import numpy as np
import torch
import torchvision.transforms as transforms

try:
    from megadetector.detection import run_detector_batch
    MEGADETECTOR_AVAILABLE = True
except Exception:
    run_detector_batch = None
    MEGADETECTOR_AVAILABLE = False

from model_config import (
    MEGADETECTOR_MODEL_PATH,
    SPECIES_MODEL_PATH,
    LOWER_CONF,
    SNIP_SIZE
)


CLASSES = [
    'Alectura_lathami', 'Antechinus_agilis', 'Bos_taurus',
    'Burhinus_grallarius', 'Canis_familiaris',
    'Chalcophaps_longirostris', 'Colluricincla_harmonica',
    'Corcorax_melanorhamphos', 'Dacelo_novaeguineae',
    'Dama_dama', 'Eopsaltria_australis', 'Felis_catus',
    'Geopelia_humeralis', 'Gymnorhina_tibicen', 'Homo_sapiens',
    'Isoodon_macrourus', 'Lepus_europaeus', 'Macropus_giganteus',
    'Menura_novaehollandiae', 'Mus_musculus', 'Oryctolagus_cuniculus',
    'Perameles_nasuta', 'Pitta_versicolor', 'Rattus',
    'Rattus_fuscipes', 'Rattus_rattus', 'Strepera_graculina',
    'Sus_scrofa', 'Tachyglossus_aculeatus', 'Thylogale_stigmatica',
    'Trichosurus_caninus', 'Trichosurus_cunninghami',
    'Trichosurus_vulpecula', 'Varanus_varius', 'Vombatus_ursinus',
    'Vulpes_vulpes', 'Wallabia_bicolor', 'Canis_dingo',
    'Capra_hircus', 'Casuarius_casuarius', 'Heteromyias_cinereifrons',
    'Hypsiprymnodon_moschatus', 'Megapodius_reinwardt',
    'Notamacropus_rufogriseus', 'Orthonyx_spaldingii',
    'Uromys_caudimaculatus'
]


COMMON_NAMES = {
    "Alectura_lathami": "australian brushturkey",
    "Canis_dingo": "dingo",
    "Macropus_giganteus": "eastern gray kangaroo",
    "Vombatus_ursinus": "common wombat",
    "Wallabia_bicolor": "swamp wallaby",
    "Thylogale_stigmatica": "red-legged pademelon",
    "Tachyglossus_aculeatus": "australian echidna",
    "Vulpes_vulpes": "red fox",
    "Felis_catus": "domestic cat",
    "Gymnorhina_tibicen": "australian magpie",
    "Dacelo_novaeguineae": "laughing kookaburra",
    "Megapodius_reinwardt": "orange-footed scrubfowl"
}


def get_device():
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


DEVICE = get_device()

_species_model = None

transform = transforms.Compose([
    transforms.Resize((480, 480)),
    transforms.ToTensor(),
])

def load_species_model():
    """
    Load SpeciesNet model once and reuse it.
    """
    global _species_model

    if _species_model is None:
        ensure_models_downloaded()

        model = torch.load(
            SPECIES_MODEL_PATH,
            map_location=DEVICE,
            weights_only=False
        )
        model.eval()
        model.to(DEVICE)
        _species_model = model

    return _species_model

def crop_animal_detections(image_path: str, output_dir: str = "/tmp/crops") -> list[str]:
    """
    Run MegaDetector if available.
    If MegaDetector is not installed yet, fall back to classifying the full image.
    """
    image_path = str(image_path)

    if not MEGADETECTOR_AVAILABLE:
        print("MegaDetector not available yet. Using full image as fallback.")
        return [image_path]

    ensure_models_downloaded()

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    md_results = run_detector_batch.load_and_run_detector_batch(
        image_file_names=[image_path],
        model_file=MEGADETECTOR_MODEL_PATH
    )

    crop_paths = []

    if not md_results:
        print("No MegaDetector results. Using full image as fallback.")
        return [image_path]

    entry = md_results[0]
    detections = entry.get("detections", [])

    img = Image.open(image_path).convert("RGB")
    width, height = img.size

    crop_num = 0

    for detection in detections:
        conf = detection.get("conf", 0)
        category = detection.get("category")

        if category != "1":
            continue

        if conf < LOWER_CONF:
            continue

        x, y, w, h = detection["bbox"]

        left = int(x * width)
        top = int(y * height)
        right = int((x + w) * width)
        bottom = int((y + h) * height)

        crop = img.crop((left, top, right, bottom))
        resized = crop.resize((SNIP_SIZE, SNIP_SIZE), Image.BILINEAR)

        crop_file = output_path / f"{Path(image_path).stem}-{crop_num}.jpg"
        resized.save(crop_file)

        crop_paths.append(str(crop_file))
        crop_num += 1

    if not crop_paths:
        print("No animal crops found. Using full image as fallback.")
        return [image_path]

    return crop_paths

@torch.no_grad()
def classify_crop(crop_path: str) -> tuple[str, float]:
    """
    Classify one cropped animal image.
    Returns scientific species name and confidence.
    """
    model = load_species_model()

    img = Image.open(crop_path).convert("RGB")
    img = transform(img)
    img = img.unsqueeze(0)
    img = img.permute(0, 2, 3, 1)
    img = img.to(DEVICE)

    logits = model(img)
    probs = torch.softmax(logits, dim=1)[0].cpu().numpy()

    best_idx = int(np.argmax(probs))
    species = CLASSES[best_idx]
    confidence = float(probs[best_idx])

    return species, confidence


def tag_local_image(image_path: str) -> dict:
    """
    Full local image tagging pipeline.
    Returns common-name tag counts.
    Example:
    {
      "dingo": 1,
      "eastern gray kangaroo": 2
    }
    """
    crop_paths = crop_animal_detections(image_path)

    if not crop_paths:
        return {}

    predictions = []

    for crop_path in crop_paths:
        species, confidence = classify_crop(crop_path)

        common_name = COMMON_NAMES.get(species, species)
        predictions.append(common_name)

        print(f"Prediction: {common_name} ({species}) confidence={confidence:.4f}")

    return dict(Counter(predictions))
