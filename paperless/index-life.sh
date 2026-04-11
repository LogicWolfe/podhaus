#!/bin/bash
set -euo pipefail
cd /home/nathan/repos/podhaus
./paperless/onenote-export --notebook-id '0-397B8A27385EB8E3!13529' --build-db --index-only
