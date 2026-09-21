#!/bin/sh
# One-shot browser verification entrypoint.
#   1. exact-integer unit tests (no browser needed, pure Node)
#   2. real headless-Chromium page submission regression
# Exits non-zero if either stage fails.
set -e

target="${1:-${WEB_URL:-http://web:80}}"

echo "== frontend exact-integer unit tests =="
node --test src/

echo
echo "== real-browser page submission regression =="
exec node e2e/browser_audit.mjs "$target"
