#!/usr/bin/env python3
"""Download a labeled fridge-contents dataset from Roboflow Universe and
convert it into MealSight's eval format.

Tries the "aicook" dataset first (516 images, 30 ingredient classes, built
specifically for fridge ingredient detection). Falls back, in order, to:
  - fridgeingredients/fridge-object
  - northumbria-university-newcastle/smart-refrigerator-zryjr
  - food-recipe-ingredient-images-0gnku/food-ingredients-dataset

Downloads the chosen dataset in COCO format to a gitignored cache directory,
selects 30 diverse images, copies them to test_data/images/, and derives
per-image ground-truth labels into test_data/eval_cases/image_ground_truth.csv
plus a provenance write-up. Idempotent: re-running reuses the cached download
and overwrites the derived outputs deterministically rather than duplicating
them.

Run with: uv run --with roboflow --with Pillow scripts/fetch_image_dataset.py
"""

from __future__ import annotations

import csv
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
CACHE_DIR = REPO_ROOT / ".cache" / "roboflow_datasets"
IMAGES_OUT_DIR = REPO_ROOT / "test_data" / "images"
EVAL_CASES_DIR = REPO_ROOT / "test_data" / "eval_cases"
CSV_PATH = EVAL_CASES_DIR / "image_ground_truth.csv"
PROVENANCE_PATH = EVAL_CASES_DIR / "DATASET_PROVENANCE.md"

NUM_IMAGES = 30
NUM_LOW_ITEM_IMAGES = 6  # of the 30, this many are deliberately low-diversity (1-2 items)
LOW_ITEM_THRESHOLD = 2
SPLIT_DIRS = ("train", "valid", "test")
BACKGROUND_CATEGORY_NAMES = {"ingredients", "background", ""}

CATEGORIES = (
    "protein",
    "vegetable",
    "fruit",
    "grain",
    "dairy",
    "condiment",
    "spice",
    "beverage",
    "other",
)


@dataclass
class DatasetCandidate:
    label: str
    workspace: str
    project: str
    version: int
    universe_url: str
    license: str


# License strings below are taken straight from each project's Roboflow API
# metadata (GET /<workspace>/<project>) at the time this script was written.
DATASET_CANDIDATES: list[DatasetCandidate] = [
    DatasetCandidate(
        label="aicook",
        workspace="karel-cornelis-q2qqg",
        project="aicook-lcv4d",
        version=1,
        universe_url="https://universe.roboflow.com/karel-cornelis-q2qqg/aicook-lcv4d",
        license="MIT",
    ),
    DatasetCandidate(
        label="fridgeingredients/fridge-object",
        workspace="fridgeingredients",
        project="fridge-object",
        version=1,
        universe_url="https://universe.roboflow.com/fridgeingredients/fridge-object",
        license="CC BY 4.0",
    ),
    DatasetCandidate(
        label="northumbria-university-newcastle/smart-refrigerator-zryjr",
        workspace="northumbria-university-newcastle",
        project="smart-refrigerator-zryjr",
        version=1,
        universe_url="https://universe.roboflow.com/northumbria-university-newcastle/smart-refrigerator-zryjr",
        license="CC BY 4.0",
    ),
    DatasetCandidate(
        label="food-recipe-ingredient-images-0gnku/food-ingredients-dataset",
        workspace="food-recipe-ingredient-images-0gnku",
        project="food-ingredients-dataset",
        version=1,
        universe_url="https://universe.roboflow.com/food-recipe-ingredient-images-0gnku/food-ingredients-dataset",
        license="CC BY 4.0",
    ),
]

# Explicit source-class -> MealSight-category mapping. Anything not listed here
# falls through to "other" and is logged so the mapping can be reviewed.
CATEGORY_MAP: dict[str, str] = {
    # aicook (30 classes)
    "apple": "fruit",
    "banana": "fruit",
    "beef": "protein",
    "blueberries": "fruit",
    "bread": "grain",
    "butter": "dairy",
    "carrot": "vegetable",
    "cheese": "dairy",
    "chicken": "protein",
    "chicken_breast": "protein",
    "chocolate": "other",
    "corn": "vegetable",
    "eggs": "protein",
    "flour": "grain",
    "goat_cheese": "dairy",
    "green_beans": "vegetable",
    "ground_beef": "protein",
    "ham": "protein",
    "heavy_cream": "dairy",
    "lime": "fruit",
    "milk": "dairy",
    "mushrooms": "vegetable",
    "onion": "vegetable",
    "potato": "vegetable",
    "shrimp": "protein",
    "spinach": "vegetable",
    "strawberries": "fruit",
    "sugar": "other",
    "sweet_potato": "vegetable",
    "tomato": "vegetable",
    # best-effort extras seen in the fallback datasets, in case aicook is unavailable
    "yogurt": "dairy",
    "kiwi": "fruit",
    "salad": "vegetable",
    "cucumber": "vegetable",
    "lemon": "fruit",
    "orange": "fruit",
    "pickles": "condiment",
    "tomato_paste": "condiment",
    "mineral_water": "beverage",
    "water": "beverage",
    "soda": "beverage",
    "juice": "beverage",
    "ketchup": "condiment",
    "mayonnaise": "condiment",
    "mustard": "condiment",
    "pepper": "vegetable",
    "bell_pepper": "vegetable",
    "garlic": "vegetable",
    "broccoli": "vegetable",
    "cabbage": "vegetable",
    "lettuce": "vegetable",
    "rice": "grain",
    "pasta": "grain",
    "sausage": "protein",
    "bacon": "protein",
    "salmon": "protein",
    "fish": "protein",
    "tofu": "protein",
    "beans": "protein",
    "pork": "protein",
    "turkey": "protein",
}


def load_env(path: Path) -> dict[str, str]:
    """Minimal .env parser: KEY=VALUE per line, '#' comments, no interpolation."""
    env: dict[str, str] = {}
    if not path.exists():
        logger.warning(".env not found at %s", path)
        return env
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def normalize_class_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def map_category(source_class: str) -> str:
    normalized = normalize_class_name(source_class)
    category = CATEGORY_MAP.get(normalized)
    if category is None:
        logger.warning(
            "Class %r has no explicit category mapping — falling back to 'other'. "
            "Add it to CATEGORY_MAP if this recurs.",
            source_class,
        )
        return "other"
    return category


def download_dataset(candidate: DatasetCandidate, api_key: str) -> Path | None:
    """Download a candidate dataset in COCO format. Returns its root directory
    on success, or None if the candidate is unavailable for any reason."""
    import roboflow  # imported lazily so --help / dry runs don't require it

    location = CACHE_DIR / candidate.label.replace("/", "__")
    try:
        rf = roboflow.Roboflow(api_key=api_key)
        workspace = rf.workspace(candidate.workspace)
        project = workspace.project(candidate.project)
        version = project.version(candidate.version)
        dataset = version.download("coco", location=str(location), overwrite=False)
    except (RuntimeError, KeyError, ValueError, ConnectionError) as exc:
        logger.warning("Dataset candidate %r unavailable: %s", candidate.label, exc)
        return None
    return Path(dataset.location)


def load_coco_split(split_dir: Path) -> tuple[dict[int, str], dict[int, dict[str, Any]], list[dict[str, Any]]]:
    """Returns (category_id -> name, image_id -> image record, annotation list)
    for one COCO split directory. Image records get an absolute 'abs_path' key."""
    annotations_path = split_dir / "_annotations.coco.json"
    payload = json.loads(annotations_path.read_text())

    categories = {
        cat["id"]: cat["name"]
        for cat in payload.get("categories", [])
        if cat["name"] not in BACKGROUND_CATEGORY_NAMES
    }
    images = {}
    for image in payload.get("images", []):
        record = dict(image)
        record["abs_path"] = split_dir / image["file_name"]
        images[image["id"]] = record

    return categories, images, payload.get("annotations", [])


def collect_distinct_classes_per_image(dataset_root: Path) -> dict[Path, set[str]]:
    """Maps each image file path to the set of distinct class names present in it."""
    image_classes: dict[Path, set[str]] = {}

    for split in SPLIT_DIRS:
        split_dir = dataset_root / split
        if not (split_dir / "_annotations.coco.json").exists():
            continue

        categories, images, annotations = load_coco_split(split_dir)
        classes_by_image_id: dict[int, set[str]] = {img_id: set() for img_id in images}
        for ann in annotations:
            category_name = categories.get(ann["category_id"])
            if category_name is None:
                continue
            classes_by_image_id.setdefault(ann["image_id"], set()).add(category_name)

        for image_id, record in images.items():
            classes = classes_by_image_id.get(image_id, set())
            if classes:
                image_classes[record["abs_path"]] = classes

    return image_classes


def select_diverse_images(image_classes: dict[Path, set[str]]) -> list[tuple[Path, set[str]]]:
    """Selects NUM_IMAGES images, preferring high distinct-class counts while
    guaranteeing NUM_LOW_ITEM_IMAGES images with only 1-2 items are included."""
    # Deterministic ordering so reruns against the same download pick the same set.
    ranked = sorted(image_classes.items(), key=lambda item: (-len(item[1]), str(item[0])))

    low_diversity = [item for item in ranked if len(item[1]) <= LOW_ITEM_THRESHOLD]
    high_diversity = [item for item in ranked if len(item[1]) > LOW_ITEM_THRESHOLD]

    selected_low = low_diversity[:NUM_LOW_ITEM_IMAGES]
    remaining_slots = NUM_IMAGES - len(selected_low)
    selected_high = high_diversity[:remaining_slots]

    selected = selected_high + selected_low
    if len(selected) < NUM_IMAGES:
        already = {path for path, _ in selected}
        for path, classes in ranked:
            if path in already:
                continue
            selected.append((path, classes))
            if len(selected) == NUM_IMAGES:
                break

    return sorted(selected, key=lambda item: str(item[0]))[:NUM_IMAGES]


def write_images_and_csv(selected: list[tuple[Path, set[str]]]) -> list[dict[str, str]]:
    IMAGES_OUT_DIR.mkdir(parents=True, exist_ok=True)
    EVAL_CASES_DIR.mkdir(parents=True, exist_ok=True)

    # Clean previously derived photos so reruns don't leave stale files behind
    # if the selection changes across a re-download.
    for stale in IMAGES_OUT_DIR.glob("photo_*.jpg"):
        stale.unlink()

    rows: list[dict[str, str]] = []
    for index, (source_path, classes) in enumerate(selected, start=1):
        photo_id = f"photo_{index:02d}"
        dest_path = IMAGES_OUT_DIR / f"{photo_id}.jpg"
        with Image.open(source_path) as img:
            img.convert("RGB").save(dest_path, format="JPEG", quality=92)

        for source_class in sorted(classes):
            rows.append(
                {
                    "photo_id": photo_id,
                    "item_name": source_class.replace("_", " "),
                    "source_class": source_class,
                    "category": map_category(source_class),
                }
            )

    with CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["photo_id", "item_name", "source_class", "category"])
        writer.writeheader()
        writer.writerows(rows)

    return rows


def write_provenance(candidate: DatasetCandidate, dataset_root: Path, class_names: list[str], image_count: int) -> None:
    readme_path = dataset_root / "README.roboflow.txt"
    readme_text = readme_path.read_text(errors="replace").strip() if readme_path.exists() else (
        "(no README.roboflow.txt in this export)"
    )

    content = f"""# Dataset Provenance

- **Dataset used:** {candidate.label}
- **Roboflow URL:** {candidate.universe_url}
- **License:** {candidate.license}
- **Source image count (full dataset):** {image_count}
- **Classes ({len(class_names)}):** {", ".join(sorted(class_names))}
- **Download date:** {date.today().isoformat()}
- **Images selected for MealSight eval:** {NUM_IMAGES} (test_data/images/photo_01.jpg .. photo_{NUM_IMAGES:02d}.jpg)

## Selection method

Images were ranked by distinct-class count (duplicate boxes of the same class
in one image count once). The {NUM_IMAGES - NUM_LOW_ITEM_IMAGES} highest-diversity
images were selected, plus {NUM_LOW_ITEM_IMAGES} images with only 1-2 distinct
items, so the eval set isn't all easy cases.

## Known limitations

- These are object-detection labels: they say an item is present, not how many
  units of it there are, and carry no freshness/expiry ground truth.
- Many datasets of this kind (including several fallback candidates) were shot
  in a single fridge with a fixed camera position, so lighting, angle, and
  shelf layout are far less varied than real-world MealSight usage will be.
- Class taxonomies vary a lot across fridge-detection datasets; the
  category mapping in `scripts/fetch_image_dataset.py` (CATEGORY_MAP) was
  written by hand for the classes seen at generation time and should be
  reviewed if a different fallback dataset is ever used.

## Export readme (from Roboflow)

```
{readme_text}
```
"""
    PROVENANCE_PATH.write_text(content)


def main() -> int:
    env = load_env(ENV_PATH)
    api_key = env.get("ROBOFLOW_API_KEY")
    if not api_key:
        logger.error("ROBOFLOW_API_KEY not set in .env — cannot download from Roboflow")
        return 1

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    dataset_root: Path | None = None
    used_candidate: DatasetCandidate | None = None
    for candidate in DATASET_CANDIDATES:
        logger.info("Trying dataset candidate: %s", candidate.label)
        dataset_root = download_dataset(candidate, api_key)
        if dataset_root is not None:
            used_candidate = candidate
            logger.info("Using dataset: %s (downloaded to %s)", candidate.label, dataset_root)
            break
        logger.warning("Falling back from %s to the next candidate.", candidate.label)

    if dataset_root is None or used_candidate is None:
        logger.error("All dataset candidates failed — no fridge dataset could be downloaded.")
        return 1

    image_classes = collect_distinct_classes_per_image(dataset_root)
    if len(image_classes) < NUM_IMAGES:
        logger.error(
            "Only %d annotated images available in %s, need at least %d.",
            len(image_classes),
            used_candidate.label,
            NUM_IMAGES,
        )
        return 1

    selected = select_diverse_images(image_classes)
    rows = write_images_and_csv(selected)

    all_classes = {cls for classes in image_classes.values() for cls in classes}
    write_provenance(used_candidate, dataset_root, sorted(all_classes), len(image_classes))

    other_count = sum(1 for row in rows if row["category"] == "other")
    logger.info(
        "Wrote %d images and %d ground-truth rows (%d rows mapped to 'other').",
        len(selected),
        len(rows),
        other_count,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
