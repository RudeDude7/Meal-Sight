#!/usr/bin/env bash
# Assembles the folder to push to a Hugging Face Space: the same files the Dockerfile uses (and nothing
# else), plus the Space README that carries the required YAML frontmatter. Run from anywhere.
#   deploy/huggingface/make_space_bundle.sh [output_dir]      default: dist/hf-space (git-ignored)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-$ROOT/dist/hf-space}"
rm -rf "$OUT" && mkdir -p "$OUT/scripts" "$OUT/test_data"
rsync -a --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' --exclude '.mypy_cache' \
      --exclude '.ruff_cache' --exclude 'tests' --exclude 'eval/results' --exclude '.cache' --exclude '.env' --exclude 'seed_meal_history_tmp.py' \
      "$ROOT/backend/" "$OUT/backend/"
cp "$ROOT/scripts/reset_demo_pantry.py" "$OUT/scripts/"
cp "$ROOT/test_data/demo_pantry.json" "$OUT/test_data/"
cp "$ROOT/Dockerfile" "$OUT/Dockerfile"
cp "$ROOT/deploy/huggingface/SPACE_README.md" "$OUT/README.md"
echo "Space bundle written to $OUT ($(find "$OUT" -type f | wc -l | tr -d ' ') files)"
