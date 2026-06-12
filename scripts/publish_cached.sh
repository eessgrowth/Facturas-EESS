#!/usr/bin/env zsh
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
BRANCH="$(git -C "$ROOT_DIR" branch --show-current)"

if [[ -z "$BRANCH" ]]; then
  echo "No hay branch activa para hacer push." >&2
  exit 1
fi

git -C "$ROOT_DIR" push origin "$BRANCH"
"$ROOT_DIR/scripts/deploy_vercel_cached.sh"
