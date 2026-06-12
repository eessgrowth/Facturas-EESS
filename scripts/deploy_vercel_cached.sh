#!/usr/bin/env zsh
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
CACHE_DIR="${VERCEL_DEPLOY_CACHE_DIR:-$ROOT_DIR/.vercel-deploy-cache/facturas-eess}"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/facturas-eess-head.XXXXXX")"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$CACHE_DIR"
git -C "$ROOT_DIR" archive HEAD | tar -x -C "$TMP_DIR"

if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete --exclude='.vercel/' "$TMP_DIR"/ "$CACHE_DIR"/
else
  find "$CACHE_DIR" -mindepth 1 -maxdepth 1 ! -name '.vercel' -exec rm -rf {} +
  (cd "$TMP_DIR" && tar -cf - .) | (cd "$CACHE_DIR" && tar -xf -)
fi

cd "$CACHE_DIR"

if [[ ! -f ".vercel/project.json" ]]; then
  vercel link --yes --project facturas-eess --scope eessgrowths-projects
fi

vercel deploy --prod --yes
