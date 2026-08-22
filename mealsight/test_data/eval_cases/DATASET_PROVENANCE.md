# Dataset Provenance

- **Dataset used:** aicook
- **Roboflow URL:** https://universe.roboflow.com/karel-cornelis-q2qqg/aicook-lcv4d
- **License:** MIT
- **Source image count (full dataset):** 516
- **Classes (30):** apple, banana, beef, blueberries, bread, butter, carrot, cheese, chicken, chicken_breast, chocolate, corn, eggs, flour, goat_cheese, green_beans, ground_beef, ham, heavy_cream, lime, milk, mushrooms, onion, potato, shrimp, spinach, strawberries, sugar, sweet_potato, tomato
- **Download date:** 2026-08-22
- **Images selected for MealSight eval:** 30 (test_data/images/photo_01.jpg .. photo_30.jpg)

## Selection method

Images were ranked by distinct-class count (duplicate boxes of the same class
in one image count once). The 24 highest-diversity
images were selected, plus 6 images with only 1-2 distinct
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
aicook - v1 original-images
==============================

This dataset was exported via roboflow.ai on November 23, 2021 at 8:57 AM GMT

It includes 516 images.
Ingredients are annotated in COCO format.

The following pre-processing was applied to each image:
* Auto-orientation of pixel data (with EXIF-orientation stripping)

No image augmentation techniques were applied.
```
