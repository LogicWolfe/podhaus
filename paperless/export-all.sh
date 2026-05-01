#!/bin/bash
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Ascending size — Life last so smaller notebooks finish first and surface
# any pipeline issues before committing to the 800+-page run.
notebooks=(
  '0-397B8A27385EB8E3!14854'  # Shadow              1
  '0-397B8A27385EB8E3!14867'  # Blue Sky Trust      4
  '0-397B8A27385EB8E3!5988'   # Nathan's Notebook   5
  '0-397B8A27385EB8E3!14908'  # Travel              6
  '0-397B8A27385EB8E3!14871'  # Financial           8
  '0-397B8A27385EB8E3!13507'  # Switch              9
  '0-397B8A27385EB8E3!14899'  # Family Life         10
  '0-397B8A27385EB8E3!13606'  # Fractal Seed        14
  '0-397B8A27385EB8E3!13524'  # Orijin Plus         18
  '0-397B8A27385EB8E3!13850'  # Property            20
  '0-397B8A27385EB8E3!13520'  # Pod Foundation      22
  '0-397B8A27385EB8E3!13605'  # Immigration Stuff   24
  '0-397B8A27385EB8E3!13508'  # Sky                 25
  '0-397B8A27385EB8E3!13570'  # Interesting Designs 51
  '0-397B8A27385EB8E3!13529'  # Life                894
)
names=(
  'Shadow' 'Blue Sky Trust' "Nathan's Notebook" 'Travel' 'Financial'
  'Switch' 'Family Life' 'Fractal Seed' 'Orijin Plus' 'Property'
  'Pod Foundation' 'Immigration Stuff' 'Sky' 'Interesting Designs' 'Life'
)

failed=()
for i in "${!notebooks[@]}"; do
  echo ""
  echo "================================================================"
  echo "=== [$((i+1))/${#notebooks[@]}] Exporting: ${names[$i]}"
  echo "================================================================"
  if ! ./paperless/onenote-export --notebook-id "${notebooks[$i]}" --build-db --formats md; then
    echo ">>> FAILED: ${names[$i]} (exit $?)" >&2
    failed+=("${names[$i]}")
  fi
  sleep 5
done

echo ""
echo "================================================================"
if [ "${#failed[@]}" -eq 0 ]; then
  echo "=== All 15 notebooks completed without errors."
else
  echo "=== ${#failed[@]} notebook(s) failed: ${failed[*]}"
  exit 1
fi
echo "================================================================"
