#!/bin/bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
./paperless/onenote-export --notebook-id '0-397B8A27385EB8E3!13529' --build-db --formats md
