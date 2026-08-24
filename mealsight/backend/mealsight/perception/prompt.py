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


def build_extraction_prompt(transcript: str) -> str:
    """The audio-extraction prompt: pulls structured cooking constraints
    out of a voice-memo transcript, run on settings.EXTRACTION_MODEL via
    mealsight.providers' complete_json (which appends its own "respond
    with valid JSON matching the schema" instruction and handles one
    repair attempt on an invalid response — this prompt doesn't need to
    repeat either).

    Same conservative spirit as VISION_PERCEPTION_PROMPT: extract only
    what's actually stated, null for anything not mentioned, never a
    plausible-sounding guess. The one thing unique to spoken language
    this prompt has to handle explicitly that a photo never does:
    people talk in real time and correct themselves mid-sentence — "make
    it for two, actually three" means three servings, not two, and "no
    dairy — oh wait, cheese is fine, just no milk" means avoid_ingredients
    = ["milk"] with dietary_restrictions left empty, not "dairy-free"
    (the correction didn't just change a number, it swapped an entire
    category-level restriction for a single-ingredient one). The prompt
    below spells out that second case specifically, since it's a
    genuinely different kind of correction than "make it three, not
    two" and easy to get only half right.
    """
    return (
        "You are extracting cooking constraints from a transcribed voice memo. "
        "Read the transcript below and extract ONLY what is actually stated. "
        "Never infer, assume, or fill in a plausible-sounding value for anything "
        "the speaker didn't actually say — leave a field null (or, for a list "
        "field, empty) whenever it wasn't mentioned at all.\n"
        "\n"
        "People speak in real time and correct themselves mid-sentence. When "
        "that happens, use the FINAL stated value, not the first one — "
        '"make it for two, actually three" means servings = 3, not 2. This '
        "applies to every field, not just numbers: if someone states a "
        "restriction and then narrows or retracts it "
        '("no dairy — oh wait, cheese is fine, just no milk"), extract the '
        "final, corrected intent — in that example, avoid_ingredients should "
        'include "milk" and dietary_restrictions should NOT include a '
        "dairy-related entry at all, since the broader dairy restriction was "
        "explicitly retracted, not just refined.\n"
        "\n"
        "Distinguish three different things people ask to avoid, and put each "
        "in the right field: a whole category of food (dietary_restrictions — "
        'e.g. "vegetarian", "gluten-free", "dairy-free", "low-sodium"), one '
        'specific ingredient (avoid_ingredients — e.g. "peanuts", "milk"), or '
        'one specific dish or style (avoid_dishes — e.g. "tacos", "fried '
        'food"). A single mention should only ever land in ONE of these three '
        "fields, whichever actually matches what was said.\n"
        "\n"
        "If someone expresses two things that don't fit together (wanting a "
        "very fast meal but also describing a slow-cooked dish, or wanting "
        "something light but also something heavy and fried), do not silently "
        "resolve the contradiction yourself — extract whatever concrete, "
        "literal constraint was actually stated (a stated time limit, for "
        "instance) and describe the tension itself in mood_or_preference "
        "instead of picking a side.\n"
        "\n"
        "Fields to extract:\n"
        "- servings: integer number of people, or null\n"
        "- max_cook_time_minutes: integer minutes, or null\n"
        "- dietary_restrictions: list of whole-category restrictions actually "
        "stated (phrase each simply, e.g. \"vegetarian\", \"dairy-free\", "
        '"gluten-free", "low-sodium" — a fixed vocabulary is applied to '
        "these afterward, so simple, common phrasing matters more than exact "
        "wording)\n"
        "- cuisine_preference: a cuisine name actually mentioned, or null\n"
        "- avoid_ingredients: list of specific ingredients to avoid actually "
        "stated\n"
        "- avoid_dishes: list of specific dishes or dish-styles to avoid "
        "actually stated\n"
        "- mood_or_preference: a brief note on tone/mood/vague preference "
        "actually expressed (e.g. \"tired, wants something easy\"), or null "
        "if nothing like that was expressed\n"
        "- protein_preference: a specific protein actually mentioned (e.g. "
        '"chicken", "salmon") or a general preference actually stated (e.g. '
        '"high-protein"), or null\n'
        "- occasion: a specific occasion actually mentioned (e.g. \"birthday "
        'dinner", "meal prep for the week"), or null\n'
        "- additional_context: any other concretely stated detail worth "
        "keeping that doesn't fit the fields above (e.g. an ingredient "
        "mentioned as already on hand, not yet in the pantry), or null\n"
        "\n"
        f"Transcript:\n\"\"\"\n{transcript}\n\"\"\"\n"
    )
