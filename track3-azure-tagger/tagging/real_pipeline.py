from pathlib import Path
from collections import Counter
import re

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


# Scientific/model label -> clean display/common name.
# Includes every label currently present in CLASSES.
COMMON_NAMES = {
    "Alectura_lathami": "australian brushturkey",
    "Antechinus_agilis": "agile antechinus",
    "Bos_taurus": "cattle",
    "Burhinus_grallarius": "bush stone-curlew",
    "Canis_familiaris": "dog",
    "Chalcophaps_longirostris": "brush bronzewing",
    "Colluricincla_harmonica": "grey shrike-thrush",
    "Corcorax_melanorhamphos": "white-winged chough",
    "Dacelo_novaeguineae": "laughing kookaburra",
    "Dama_dama": "fallow deer",
    "Eopsaltria_australis": "eastern yellow robin",
    "Felis_catus": "cat",
    "Geopelia_humeralis": "bar-shouldered dove",
    "Gymnorhina_tibicen": "australian magpie",
    "Homo_sapiens": "person",
    "Isoodon_macrourus": "northern brown bandicoot",
    "Lepus_europaeus": "brown hare",
    "Macropus_giganteus": "eastern grey kangaroo",
    "Menura_novaehollandiae": "superb lyrebird",
    "Mus_musculus": "house mouse",
    "Oryctolagus_cuniculus": "rabbit",
    "Perameles_nasuta": "long-nosed bandicoot",
    "Pitta_versicolor": "noisy pitta",
    "Rattus": "rat",
    "Rattus_fuscipes": "bush rat",
    "Rattus_rattus": "black rat",
    "Strepera_graculina": "pied currawong",
    "Sus_scrofa": "wild pig",
    "Tachyglossus_aculeatus": "short-beaked echidna",
    "Thylogale_stigmatica": "red-legged pademelon",
    "Trichosurus_caninus": "short-eared possum",
    "Trichosurus_cunninghami": "mountain brushtail possum",
    "Trichosurus_vulpecula": "common brushtail possum",
    "Varanus_varius": "lace monitor",
    "Vombatus_ursinus": "common wombat",
    "Vulpes_vulpes": "red fox",
    "Wallabia_bicolor": "swamp wallaby",
    "Canis_dingo": "dingo",
    "Capra_hircus": "goat",
    "Casuarius_casuarius": "southern cassowary",
    "Heteromyias_cinereifrons": "ashy robin",
    "Hypsiprymnodon_moschatus": "musky rat-kangaroo",
    "Megapodius_reinwardt": "orange-footed scrubfowl",
    "Notamacropus_rufogriseus": "red-necked wallaby",
    "Orthonyx_spaldingii": "chowchilla",
    "Uromys_caudimaculatus": "giant white-tailed rat",
}


# Query/user/model variations -> canonical common name.
# This is useful because different tracks/users may use scientific names,
# underscores, American spelling, common names, or short aliases.
ALIASES = {
    # Wild pig / feral pig / boar
    "sus scrofa": "wild pig",
    "sus_scrofa": "wild pig",
    "wild pig": "wild pig",
    "feral pig": "wild pig",
    "pig": "wild pig",
    "boar": "wild pig",
    "wild boar": "wild pig",
    "feral boar": "wild pig",

    # Brushturkey / scrubfowl
    "alectura lathami": "australian brushturkey",
    "alectura_lathami": "australian brushturkey",
    "australian brushturkey": "australian brushturkey",
    "australian brush turkey": "australian brushturkey",
    "brush turkey": "australian brushturkey",
    "brushturkey": "australian brushturkey",
    "bush turkey": "australian brushturkey",

    "megapodius reinwardt": "orange-footed scrubfowl",
    "megapodius_reinwardt": "orange-footed scrubfowl",
    "orange footed scrubfowl": "orange-footed scrubfowl",
    "orange-footed scrubfowl": "orange-footed scrubfowl",
    "scrubfowl": "orange-footed scrubfowl",

    # Kangaroos / wallabies / pademelons
    "macropus giganteus": "eastern grey kangaroo",
    "macropus_giganteus": "eastern grey kangaroo",
    "eastern grey kangaroo": "eastern grey kangaroo",
    "eastern gray kangaroo": "eastern grey kangaroo",
    "kangaroo": "eastern grey kangaroo",

    "wallabia bicolor": "swamp wallaby",
    "wallabia_bicolor": "swamp wallaby",
    "swamp wallaby": "swamp wallaby",
    "wallaby": "swamp wallaby",

    "notamacropus rufogriseus": "red-necked wallaby",
    "notamacropus_rufogriseus": "red-necked wallaby",
    "red necked wallaby": "red-necked wallaby",
    "red-necked wallaby": "red-necked wallaby",

    "thylogale stigmatica": "red-legged pademelon",
    "thylogale_stigmatica": "red-legged pademelon",
    "red legged pademelon": "red-legged pademelon",
    "red-legged pademelon": "red-legged pademelon",
    "pademelon": "red-legged pademelon",

    # Wombat / echidna
    "vombatus ursinus": "common wombat",
    "vombatus_ursinus": "common wombat",
    "common wombat": "common wombat",
    "wombat": "common wombat",

    "tachyglossus aculeatus": "short-beaked echidna",
    "tachyglossus_aculeatus": "short-beaked echidna",
    "short beaked echidna": "short-beaked echidna",
    "short-beaked echidna": "short-beaked echidna",
    "australian echidna": "short-beaked echidna",
    "echidna": "short-beaked echidna",

    # Canids / cats
    "canis dingo": "dingo",
    "canis_dingo": "dingo",
    "dingo": "dingo",

    "canis familiaris": "dog",
    "canis_familiaris": "dog",
    "dog": "dog",
    "domestic dog": "dog",

    "vulpes vulpes": "red fox",
    "vulpes_vulpes": "red fox",
    "fox": "red fox",
    "red fox": "red fox",

    "felis catus": "cat",
    "felis_catus": "cat",
    "cat": "cat",
    "domestic cat": "cat",
    "feral cat": "cat",

    # Deer / livestock
    "dama dama": "fallow deer",
    "dama_dama": "fallow deer",
    "fallow deer": "fallow deer",
    "deer": "fallow deer",

    "bos taurus": "cattle",
    "bos_taurus": "cattle",
    "cattle": "cattle",
    "cow": "cattle",
    "cows": "cattle",
    "bull": "cattle",

    "capra hircus": "goat",
    "capra_hircus": "goat",
    "goat": "goat",

    # Rabbits / hares / rodents
    "oryctolagus cuniculus": "rabbit",
    "oryctolagus_cuniculus": "rabbit",
    "rabbit": "rabbit",
    "european rabbit": "rabbit",

    "lepus europaeus": "brown hare",
    "lepus_europaeus": "brown hare",
    "hare": "brown hare",
    "brown hare": "brown hare",

    "mus musculus": "house mouse",
    "mus_musculus": "house mouse",
    "mouse": "house mouse",
    "house mouse": "house mouse",

    "rattus": "rat",
    "rat": "rat",
    "rattus fuscipes": "bush rat",
    "rattus_fuscipes": "bush rat",
    "bush rat": "bush rat",
    "rattus rattus": "black rat",
    "rattus_rattus": "black rat",
    "black rat": "black rat",

    "uromys caudimaculatus": "giant white-tailed rat",
    "uromys_caudimaculatus": "giant white-tailed rat",
    "giant white tailed rat": "giant white-tailed rat",
    "giant white-tailed rat": "giant white-tailed rat",

    # Bandicoots / possums
    "isoodon macrourus": "northern brown bandicoot",
    "isoodon_macrourus": "northern brown bandicoot",
    "northern brown bandicoot": "northern brown bandicoot",
    "bandicoot": "northern brown bandicoot",

    "perameles nasuta": "long-nosed bandicoot",
    "perameles_nasuta": "long-nosed bandicoot",
    "long nosed bandicoot": "long-nosed bandicoot",
    "long-nosed bandicoot": "long-nosed bandicoot",

    "trichosurus caninus": "short-eared possum",
    "trichosurus_caninus": "short-eared possum",
    "short eared possum": "short-eared possum",
    "short-eared possum": "short-eared possum",

    "trichosurus cunninghami": "mountain brushtail possum",
    "trichosurus_cunninghami": "mountain brushtail possum",
    "mountain brushtail possum": "mountain brushtail possum",

    "trichosurus vulpecula": "common brushtail possum",
    "trichosurus_vulpecula": "common brushtail possum",
    "brushtail possum": "common brushtail possum",
    "common brushtail possum": "common brushtail possum",
    "possum": "common brushtail possum",

    # Birds
    "burhinus grallarius": "bush stone-curlew",
    "burhinus_grallarius": "bush stone-curlew",
    "bush stone curlew": "bush stone-curlew",
    "bush stone-curlew": "bush stone-curlew",

    "chalcophaps longirostris": "brush bronzewing",
    "chalcophaps_longirostris": "brush bronzewing",
    "brush bronzewing": "brush bronzewing",

    "colluricincla harmonica": "grey shrike-thrush",
    "colluricincla_harmonica": "grey shrike-thrush",
    "gray shrike thrush": "grey shrike-thrush",
    "grey shrike thrush": "grey shrike-thrush",
    "grey shrike-thrush": "grey shrike-thrush",

    "corcorax melanorhamphos": "white-winged chough",
    "corcorax_melanorhamphos": "white-winged chough",
    "white winged chough": "white-winged chough",
    "white-winged chough": "white-winged chough",

    "dacelo novaeguineae": "laughing kookaburra",
    "dacelo_novaeguineae": "laughing kookaburra",
    "kookaburra": "laughing kookaburra",
    "laughing kookaburra": "laughing kookaburra",

    "eopsaltria australis": "eastern yellow robin",
    "eopsaltria_australis": "eastern yellow robin",
    "eastern yellow robin": "eastern yellow robin",

    "geopelia humeralis": "bar-shouldered dove",
    "geopelia_humeralis": "bar-shouldered dove",
    "bar shouldered dove": "bar-shouldered dove",
    "bar-shouldered dove": "bar-shouldered dove",

    "gymnorhina tibicen": "australian magpie",
    "gymnorhina_tibicen": "australian magpie",
    "magpie": "australian magpie",
    "australian magpie": "australian magpie",

    "menura novaehollandiae": "superb lyrebird",
    "menura_novaehollandiae": "superb lyrebird",
    "lyrebird": "superb lyrebird",
    "superb lyrebird": "superb lyrebird",

    "pitta versicolor": "noisy pitta",
    "pitta_versicolor": "noisy pitta",
    "noisy pitta": "noisy pitta",

    "strepera graculina": "pied currawong",
    "strepera_graculina": "pied currawong",
    "currawong": "pied currawong",
    "pied currawong": "pied currawong",

    "casuarius casuarius": "southern cassowary",
    "casuarius_casuarius": "southern cassowary",
    "cassowary": "southern cassowary",
    "southern cassowary": "southern cassowary",

    "heteromyias cinereifrons": "ashy robin",
    "heteromyias_cinereifrons": "ashy robin",
    "ashy robin": "ashy robin",

    "orthonyx spaldingii": "chowchilla",
    "orthonyx_spaldingii": "chowchilla",
    "chowchilla": "chowchilla",

    # Reptiles / others
    "varanus varius": "lace monitor",
    "varanus_varius": "lace monitor",
    "lace monitor": "lace monitor",
    "goanna": "lace monitor",
    "monitor lizard": "lace monitor",

    "hypsiprymnodon moschatus": "musky rat-kangaroo",
    "hypsiprymnodon_moschatus": "musky rat-kangaroo",
    "musky rat kangaroo": "musky rat-kangaroo",
    "musky rat-kangaroo": "musky rat-kangaroo",

    # Human / generic labels
    "homo sapiens": "person",
    "homo_sapiens": "person",
    "human": "person",
    "person": "person",
}


def normalise_key(value: str) -> str:
    """
    Normalise labels so variations like:
    'Sus_scrofa', 'sus scrofa', 'Wild-Pig'
    all become comparable keys.
    """
    if not value:
        return ""

    value = str(value).strip().lower()
    value = value.replace("_", " ")
    value = value.replace("-", " ")
    value = re.sub(r"\s+", " ", value)
    return value


def to_common_name(label: str) -> str:
    """
    Convert model/scientific/common labels into one clean common display name.
    """
    if not label:
        return "unknown"

    raw = str(label).strip()
    key = normalise_key(raw)

    if key in ALIASES:
        return ALIASES[key]

    # Try direct class label lookup first, e.g. "Sus_scrofa".
    if raw in COMMON_NAMES:
        return COMMON_NAMES[raw]

    # Try normalised COMMON_NAMES lookup, e.g. "sus scrofa".
    for scientific_name, common_name in COMMON_NAMES.items():
        if normalise_key(scientific_name) == key:
            return common_name

    # Fallback: make unknown labels readable instead of returning underscores.
    return raw.replace("_", " ").strip()


def normalise_tags_dict(tags: dict) -> dict:
    """
    Converts labels and combines duplicates.

    Example:
        {"Sus_scrofa": 1, "pig": 1}
    becomes:
        {"wild pig": 2}
    """
    cleaned = {}

    for label, count in tags.items():
        common = to_common_name(label)
        cleaned[common] = cleaned.get(common, 0) + int(count)

    return cleaned


def normalise_tag_list(tag_list: list[str]) -> list[str]:
    """
    Normalise a tag list and remove duplicates.
    """
    return sorted(set(to_common_name(tag) for tag in tag_list))


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
    If MegaDetector is not installed or fails, fall back to classifying the full image.
    """
    image_path = str(image_path)

    if not MEGADETECTOR_AVAILABLE:
        print("MegaDetector not available yet. Using full image as fallback.")
        return [image_path]

    ensure_models_downloaded()

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        md_results = run_detector_batch.load_and_run_detector_batch(
            image_file_names=[image_path],
            model_file=MEGADETECTOR_MODEL_PATH
        )
    except Exception as e:
        print(f"MegaDetector failed at runtime. Using full image as fallback. Error: {e}")
        return [image_path]

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

        # MegaDetector category "1" means animal.
        if category != "1":
            continue

        if conf < LOWER_CONF:
            continue

        x, y, w, h = detection["bbox"]

        left = max(0, int(x * width))
        top = max(0, int(y * height))
        right = min(width, int((x + w) * width))
        bottom = min(height, int((y + h) * height))

        if right <= left or bottom <= top:
            continue

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
    Full image tagging pipeline.
    Returns normalised common-name tag counts.

    Example:
    {
      "dingo": 1,
      "eastern grey kangaroo": 2,
      "wild pig": 1
    }
    """
    crop_paths = crop_animal_detections(image_path)

    if not crop_paths:
        return {}

    predictions = []

    for crop_path in crop_paths:
        species, confidence = classify_crop(crop_path)

        common_name = to_common_name(species)
        predictions.append(common_name)

        print(f"Prediction: {common_name} ({species}) confidence={confidence:.4f}")

    return normalise_tags_dict(dict(Counter(predictions)))


def get_detector_mode():
    return "megadetector" if MEGADETECTOR_AVAILABLE else "fallback"
