#!/bin/bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# All notebook IDs
notebooks=(
  '0-397B8A27385EB8E3!14854'
  '0-397B8A27385EB8E3!14867'
  '0-397B8A27385EB8E3!5988'
  '0-397B8A27385EB8E3!14908'
  '0-397B8A27385EB8E3!13507'
  '0-397B8A27385EB8E3!14899'
  '0-397B8A27385EB8E3!14871'
  '0-397B8A27385EB8E3!13606'
  '0-397B8A27385EB8E3!13524'
  '0-397B8A27385EB8E3!13520'
  '0-397B8A27385EB8E3!13850'
  '0-397B8A27385EB8E3!13605'
  '0-397B8A27385EB8E3!13508'
  '0-397B8A27385EB8E3!13570'
  '0-397B8A27385EB8E3!13529'
)
names=(
  'Shadow'
  'Blue Sky Trust'
  "Nathan's Notebook"
  'Travel'
  'Switch'
  'Family Life'
  'Financial'
  'Fractal Seed'
  'Orijin Plus'
  'Pod Foundation'
  'Property'
  'Immigration Stuff'
  'Sky'
  'Interesting Designs'
  'Life'
)

for i in "${!notebooks[@]}"; do
  echo "=== Indexing: ${names[$i]} ==="
  sleep 5
  ./paperless/onenote-export --notebook-id "${notebooks[$i]}" --build-db --index-only 2>&1
  echo ""
done
