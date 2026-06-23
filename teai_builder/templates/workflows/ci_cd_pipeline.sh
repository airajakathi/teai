#!/usr/bin/env bash
set -euo pipefail

if [[ ! -d .git ]]; then
  echo "Run this from the repository root."
  exit 1
fi

git add .
git commit -m "ci: prepare pipeline changes" || true
git push origin "$(git branch --show-current)"
