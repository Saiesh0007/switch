#!/usr/bin/env bash
# Only needed if `docker compose pull` fails with "denied: denied" on ghcr.io
# (seen on one Docker Desktop install, for every ghcr.io image, even public ones).
# Fetches the public Switch images with crane in a clean container, then loads them.
set -euo pipefail
VERSION="${1:-0.31.0}"
for img in switch-core gateway setup; do
  ref="ghcr.io/sandbox-quantum/$img:$VERSION"
  echo "==> $ref"
  docker run --rm gcr.io/go-containerregistry/crane:latest \
    pull --platform=linux/amd64 "$ref" /dev/stdout | docker load
done
