"""The vision perception prompt.

Base: PROMPT_CONSERVATIVE ("B-conservative") from scripts/
diagnose_vision.py, the winning prompt from scripts/benchmark_vision.py's
multi-sample benchmark (mistral-medium-2505 + B-conservative, mean F1
0.64 at native resolution — see docs/vision_benchmark_report.md). The
model and prompt are both benchmark-determined and are not substituted
here; this module only extends that prompt's requested output.

The one part of the original prompt preserved word for word: explicit
permission to say it cannot identify anything with confidence.
docs/vision_benchmark_report.md's own findings tie prompt A's
catastrophic 0.00 F1 failures directly to the ABSENCE of that
permission — a model with no sanctioned way to say "I'm not sure"
hallucinates a full generic fridge inventory instead of admitting
uncertainty. That escape hatch is exactly what turns into
VisionPerception's own empty-result shape below, so it survives into
this module's structured-JSON version unchanged in spirit, even though
the original benchmark's output format (one pipe-delimited line per
item) is not what's requested here.

Extension: the original prompt asked only for an item name and a
confidence level, one per line. This version asks for the same
information (name, confidence) plus quantity, unit, and freshness per
item, as structured JSON instead of pipe-delimited lines — needed so
mealsight.perception.processor can parse a real schema
(RawVisionPerception) rather than re-deriving the original prompt's own
line-parsing logic. Category is deliberately NOT requested — see
mealsight.pantry.category.resolve_category, which already resolves
99.4% of the seeded recipe corpus and is what analyze_fridge_photo
calls locally instead of ever asking the model for it.
"""

from __future__ import annotations

VISION_PERCEPTION_PROMPT = (
    "Look at this photo carefully. List ONLY food items you can clearly and "
    "directly see in the image. Do not guess, and do not list items just "
    "because they're typical of a fridge or pantry — only list what is "
    "actually visible. If the image is unclear, blank, or you cannot "
    "confidently identify any items, respond with exactly this JSON and "
    "nothing else:\n"
    '{"identified_items": [], "total_items_found": 0, "photo_quality": '
    '"unclear", "notes": "I cannot identify any items with confidence"}\n'
    "\n"
    "Otherwise, respond with valid JSON only (no markdown code fences, no "
    "other commentary) matching exactly this shape:\n"
    "{\n"
    '  "identified_items": [\n'
    "    {\n"
    '      "name": "<specific food name, e.g. \'chicken thighs\' not \'meat\', '
    "\'red bell pepper\' not \'pepper\'>\",\n"
    '      "quantity": <a number, or null if you cannot tell>,\n'
    "      \"unit\": \"<a unit, e.g. 'count', 'lb', 'liter', or null if you "
    'cannot tell>",\n'
    "      \"freshness\": \"<a brief freshness observation, e.g. 'fresh', "
    "'wilted', 'moldy', or null if you cannot tell>\",\n"
    '      "confidence": "<high, medium, or low>"\n'
    "    }\n"
    "  ],\n"
    '  "total_items_found": <the integer count of items in identified_items>,\n'
    '  "photo_quality": "<a brief note on lighting, angle, or clarity>",\n'
    '  "notes": "<any other brief relevant observation, or null>"\n'
    "}\n"
    "\n"
    "Only report a quantity, unit, or freshness value when you can actually "
    "tell from the photo — use null rather than guessing a plausible-sounding "
    "value. Do not include a category or food-group field at all."
)
