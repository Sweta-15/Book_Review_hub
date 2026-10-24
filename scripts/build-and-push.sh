#!/usr/bin/env bash
# Build the three microservice images and push them to Docker Hub.
# Usage: ./scripts/build-and-push.sh <dockerhub-username> [tag]
#   (run `docker login` first)
# Set PLATFORMS=linux/amd64,linux/arm64 to build multi-architecture images
# (needed if you build on an Apple Silicon Mac but deploy to a cloud provider).
set -euo pipefail
cd "$(dirname "$0")/.."
USER_NAME="${1:?Usage: $0 <dockerhub-username> [tag]}"
TAG="${2:-1.0}"

for svc in frontend books-service reviews-service; do
  image="${USER_NAME}/bookhub-${svc}:${TAG}"
  echo "==> ${image}"
  if [ -n "${PLATFORMS:-}" ]; then
    docker buildx build --platform "${PLATFORMS}" -t "${image}" --push "./${svc}"
  else
    docker build -t "${image}" "./${svc}"
    docker push "${image}"
  fi
done
echo "Done. Images pushed for user ${USER_NAME} with tag ${TAG}."
