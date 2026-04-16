#!/bin/bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

notebooks=(
  '0-397B8A27385EB8E3!13605'
  '0-397B8A27385EB8E3!13508'
  '0-397B8A27385EB8E3!13570'
  '0-397B8A27385EB8E3!13529'
)
names=(
  'Immigration Stuff'
  'Sky'
  'Interesting Designs'
  'Life'
)

for i in "${!notebooks[@]}"; do
  echo "=== Exporting: ${names[$i]} (sleeping 30s first) ==="
  sleep 30
  ./paperless/onenote-export --notebook-id "${notebooks[$i]}" --build-db --formats md
  echo ""
done
