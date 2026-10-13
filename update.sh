#!/bin/sh
# Refreshes the card with today's numbers and publishes it.
# Uses the GitHub CLI login already on this machine, so no token is stored
# in the repo or on GitHub.
set -e
cd "$(dirname "$0")"
GH_TOKEN=$(gh auth token) python3 generate.py
git add dark.svg light.svg snake.svg
if git diff --cached --quiet; then
  echo "Card already up to date."
  exit 0
fi
git commit -m "Refresh profile card"
git push
